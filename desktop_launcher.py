"""SaveVido native Windows desktop launcher with incremental update support."""
import json, os, re, shutil, subprocess, sys, threading, time
from pathlib import Path
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AZANKHAN.SaveVido")
    except Exception:
        pass
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
os.environ.setdefault("QT_OPENGL", "software")
from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QSystemTrayIcon
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from werkzeug.serving import make_server
import requests
import app as savevido_app
from app import app

HOST, PORT = "127.0.0.1", int(os.getenv("PORT", "5000"))
APP_URL = f"http://{HOST}:{PORT}"
REPO = "AzanKhan-pk/conver-my-files-to-installer-and-apk-with-GPT"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))
ICON_PATH = RESOURCE_ROOT / "static" / "savevido.ico"
if not ICON_PATH.is_file():
    ICON_PATH = RESOURCE_ROOT / "static" / "icon-512.png"

def read_app_version():
    try:
        external = APP_ROOT / "build_info.json"
        version_file = external if external.is_file() else RESOURCE_ROOT / "build_info.json"
        return str(json.loads(version_file.read_text(encoding="utf-8-sig")).get("version") or "0.0.0")
    except Exception:
        return "0.0.0"

APP_VERSION = read_app_version()

def version_tuple(value):
    parts = re.findall(r"\d+", str(value))
    return tuple(int(part) for part in parts) if parts else (0,)

RELEASE_CONFIG_URL = f"https://raw.githubusercontent.com/{REPO}/savevido-central-platform/platform/release-config.json"


def update_is_mandatory(version):
    """Make an update required 48 hours after it is first detected."""
    state_file = Path(savevido_app.APP_DATA_DIR) / "update-reminder.json"
    now = time.time()
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if state.get("version") != version:
            raise ValueError("different update version")
        first_seen = float(state.get("first_seen", now))
    except Exception:
        first_seen = now
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps({"version": version, "first_seen": first_seen}), encoding="utf-8")
        except OSError:
            pass
    return now - first_seen >= 48 * 60 * 60

def pending_update_requirement():
    """Read the locally remembered 48-hour update deadline when offline."""
    state_file = Path(savevido_app.APP_DATA_DIR) / "update-reminder.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        version = str(state.get("version") or "")
        first_seen = float(state.get("first_seen") or 0)
        if not version or first_seen <= 0 or version_tuple(version) <= version_tuple(APP_VERSION):
            return "", False
        return version, (time.time() - first_seen) >= 48 * 60 * 60
    except Exception:
        return "", False

class UpdateChecker(QObject):
    finished = Signal(dict)

    def check(self):
        def worker():
            try:
                response = requests.get(RELEASE_CONFIG_URL, timeout=(8, 20), headers={"Cache-Control": "no-cache"})
                response.raise_for_status()
                config = response.json()
                windows = (config.get("channels") or {}).get("windows") or {}
                tag = str(windows.get("version") or config.get("current_version") or "").lstrip("v")
                if not tag:
                    raise ValueError("The SaveVido release version is missing.")
                if version_tuple(tag) <= version_tuple(APP_VERSION):
                    try:
                        (Path(savevido_app.APP_DATA_DIR) / "update-reminder.json").unlink(missing_ok=True)
                    except OSError:
                        pass
                    self.finished.emit({"status": "current", "current_version": APP_VERSION})
                    return

                manifest_url = f"https://github.com/{REPO}/releases/download/v{tag}/SaveVido-Update-Manifest.json"
                manifest_response = requests.get(manifest_url, timeout=(8, 30), headers={"Cache-Control": "no-cache"})
                manifest_response.raise_for_status()
                latest_manifest = manifest_response.json()
                installer_url = str(windows.get("download_url") or "")
                patch_url = str(latest_manifest.get("patch_url") or "")
                patch_hash = str(latest_manifest.get("patch_sha256") or "")
                if not patch_url.startswith("https://") or len(patch_hash) != 64:
                    self.finished.emit({"status": "bootstrap", "version": tag, "installer_url": installer_url, "mandatory": update_is_mandatory(tag)})
                    return

                # Follow delta manifests backwards so older installations can update in stages.
                chain = [(tag, manifest_url, latest_manifest)]
                base_version = str(latest_manifest.get("base_version") or "")
                visited = set()
                while base_version and version_tuple(base_version) != version_tuple(APP_VERSION):
                    if base_version in visited or len(chain) >= 20:
                        break
                    visited.add(base_version)
                    previous_url = f"https://github.com/{REPO}/releases/download/v{base_version}/SaveVido-Update-Manifest.json"
                    previous_response = requests.get(previous_url, timeout=(8, 30), headers={"Cache-Control": "no-cache"})
                    if not previous_response.ok:
                        break
                    previous_manifest = previous_response.json()
                    previous_patch = str(previous_manifest.get("patch_url") or "")
                    previous_hash = str(previous_manifest.get("patch_sha256") or "")
                    if str(previous_manifest.get("version") or "") != base_version or not previous_patch.startswith("https://") or len(previous_hash) != 64:
                        break
                    chain.append((base_version, previous_url, previous_manifest))
                    base_version = str(previous_manifest.get("base_version") or "")

                if not base_version or version_tuple(base_version) != version_tuple(APP_VERSION):
                    self.finished.emit({"status": "bootstrap", "version": tag, "installer_url": installer_url, "mandatory": update_is_mandatory(tag)})
                    return
                manifest_urls = [item[1] for item in reversed(chain)]
                self.finished.emit({"status": "available", "version": tag, "manifest_urls": manifest_urls, "mandatory": update_is_mandatory(tag)})
            except Exception as exc:
                pending_version, mandatory = pending_update_requirement()
                self.finished.emit({"status": "error", "version": pending_version, "mandatory": mandatory, "message": f"Update check failed: {exc}. Please check your internet connection and try again."})
        threading.Thread(target=worker, name="SaveVidoUpdateCheck", daemon=True).start()

server = make_server(HOST, PORT, app, threaded=True)
server_thread = threading.Thread(target=server.serve_forever, name="SaveVidoLocalServer", daemon=True)

class UpdatePage(QWebEnginePage):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() == "savevido":
            if url.host() == "check-updates":
                self.window.check_updates()
            elif url.host() == "install-update":
                self.window.install_update()
            elif url.host() == "restart-app":
                self.window.restart_app()
            elif url.host() == "account":
                QDesktopServices.openUrl(QUrl("https://savevido-central-platform.vercel.app/account.html"))
            elif url.host() == "download-full-installer":
                if self.window.pending_installer_url:
                    QDesktopServices.openUrl(QUrl(self.window.pending_installer_url))
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

class SaveVidoWindow(QMainWindow):
    def __init__(self, checker, qt_app):
        super().__init__()
        self.checker, self.qt_app = checker, qt_app
        self.pending_manifest_urls = []
        self.pending_installer_url = None
        self.pending_version = None
        self.silent_check = False
        self.update_helper = None
        self.update_status_file = Path(savevido_app.APP_DATA_DIR) / "update-status.json"
        self.update_poll = QTimer(self)
        self.update_poll.setInterval(400)
        self.update_poll.timeout.connect(self.poll_update_status)
        self.setWindowTitle(f"SaveVido {APP_VERSION} — Video Downloader")
        self.setMinimumSize(900, 650)
        self.resize(1180, 780)
        if ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.browser = QWebEngineView(self)
        self.browser.setPage(UpdatePage(self, self.browser))
        self.browser.setUrl(QUrl(f"{APP_URL}/?desktop=1"))
        self.setCentralWidget(self.browser)
        self.checker.finished.connect(self.on_update_result)
        QTimer.singleShot(2500, self.show_update_status)

    def show_update_status(self):
        status_file = Path(savevido_app.APP_DATA_DIR) / "update-status.json"
        try:
            if not status_file.is_file():
                return
            data = json.loads(status_file.read_text(encoding="utf-8"))
            status_file.unlink(missing_ok=True)
            if data.get("status") == "installed":
                self.dispatch("savevido-update-installed", data)
            elif data.get("status") == "failed":
                self.dispatch("savevido-update-failed", data)
        except Exception:
            pass

    def dispatch(self, name, data):
        payload = json.dumps(data).replace("</", "<\\/")
        self.browser.page().runJavaScript(f"window.dispatchEvent(new CustomEvent('{name}', {{detail: {payload}}}));")

    def check_updates(self, silent=False):
        self.silent_check = silent
        if not silent:
            self.dispatch("savevido-update-result", {"status": "checking", "current_version": APP_VERSION})
        self.checker.check()

    def on_update_result(self, data):
        self.pending_manifest_urls = data.get("manifest_urls") or ([data["manifest_url"]] if data.get("manifest_url") else [])
        self.pending_installer_url = data.get("installer_url")
        self.pending_version = data.get("version")
        if not self.silent_check or data.get("status") in ("available", "bootstrap") or data.get("mandatory"):
            self.dispatch("savevido-update-result", data)
        self.silent_check = False

    def install_update(self):
        if not self.pending_manifest_urls:
            if self.pending_installer_url:
                QDesktopServices.openUrl(QUrl(self.pending_installer_url))
            else:
                self.dispatch("savevido-update-result", {"status": "error", "message": "The update is not ready. Check for updates again."})
            return
        updater = APP_ROOT / "SaveVidoUpdater.exe"
        if getattr(sys, "frozen", False):
            # Run the helper from the user-data folder so the delta can safely
            # replace SaveVidoUpdater.exe inside the installation directory.
            helper_dir = Path(savevido_app.APP_DATA_DIR) / "updater-cache"
            helper_dir.mkdir(parents=True, exist_ok=True)
            helper_copy = helper_dir / f"SaveVidoUpdater-{os.getpid()}.exe"
            shutil.copy2(updater, helper_copy)
            command = [str(helper_copy), "--manifest-urls", *self.pending_manifest_urls, "--base-version", APP_VERSION, "--app-root", str(APP_ROOT)]
        else:
            command = [sys.executable, str(APP_ROOT / "updater.py"), "--manifest-urls", *self.pending_manifest_urls, "--base-version", APP_VERSION, "--app-root", str(APP_ROOT)]
        self.update_status_file.parent.mkdir(parents=True, exist_ok=True)
        self.update_status_file.unlink(missing_ok=True)
        command += ["--wait-pid", str(os.getpid()), "--status-file", str(self.update_status_file)]
        if not Path(command[0]).exists():
            self.dispatch("savevido-update-result", {"status": "error", "message": "The updater component is missing. Please install the latest full SaveVido setup once."})
            return
        try:
            self.dispatch("savevido-update-installing", {"version": self.pending_version})
            self.update_helper = subprocess.Popen(command, cwd=str(APP_ROOT), close_fds=True)
            self.update_poll.start()
        except Exception as exc:
            self.dispatch("savevido-update-result", {"status": "error", "message": f"Could not start the updater: {exc}"})

    def poll_update_status(self):
        try:
            data = json.loads(self.update_status_file.read_text(encoding="utf-8"))
        except Exception:
            if self.update_helper is not None and self.update_helper.poll() is not None:
                self.update_poll.stop()
                self.dispatch("savevido-update-failed", {"message": "The updater stopped before reporting a result. Please try again."})
            return
        state = data.get("status")
        if state in ("downloading", "verifying"):
            self.dispatch("savevido-update-progress", data)
        elif state == "ready":
            self.update_poll.stop()
            self.dispatch("savevido-update-ready", data)
            self.update_status_file.unlink(missing_ok=True)
            # Keep SaveVido open; the updater waits until the user exits manually.
        elif state == "failed":
            self.update_poll.stop()
            self.dispatch("savevido-update-failed", data)
            self.update_status_file.unlink(missing_ok=True)
        elif state == "installed":
            self.update_poll.stop()
            self.dispatch("savevido-update-installed", data)
            self.update_status_file.unlink(missing_ok=True)

    def restart_app(self):
        exe = APP_ROOT / "SaveVido.exe"
        if exe.is_file():
            subprocess.Popen([str(exe)], cwd=str(APP_ROOT), close_fds=True)
        self.qt_app.quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

def open_downloads_folder():
    folder = Path(savevido_app.DOWNLOAD_ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt": os.startfile(str(folder))
    elif sys.platform == "darwin": subprocess.Popen(["open", str(folder)])
    else: subprocess.Popen(["xdg-open", str(folder)])

def main():
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("SaveVido")
    qt_app.setQuitOnLastWindowClosed(False)
    if ICON_PATH.is_file(): qt_app.setWindowIcon(QIcon(str(ICON_PATH)))
    # Ask once. The default choice is Decline; the owner token is never present here.
    consent_file = Path(savevido_app.APP_DATA_DIR) / "telemetry-consent.json"
    consent = None
    try:
        consent = bool(json.loads(consent_file.read_text(encoding="utf-8")).get("enabled"))
    except Exception:
        consent = None
    if consent is None:
        choice = QMessageBox.question(
            None, "SaveVido privacy choice",
            "Would you like to share anonymous app-open and download success/failure events, app version, file type and source website hostname to help improve SaveVido? The service may estimate country/city from network metadata. It does not receive your raw IP, full media URL, file name or downloaded file. Choose No to disable analytics.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        consent = choice == QMessageBox.StandardButton.Yes
        try:
            consent_file.write_text(json.dumps({"enabled": consent}), encoding="utf-8")
        except OSError:
            pass
    savevido_app.configure_telemetry(APP_VERSION, enabled=consent)
    if consent:
        savevido_app.send_telemetry("app_open")

    server_thread.start()
    checker = UpdateChecker(qt_app)
    window = SaveVidoWindow(checker, qt_app)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), qt_app)
        tray.setToolTip("SaveVido — Video Downloader")
        menu = QMenu()
        open_action = QAction("Open SaveVido", qt_app)
        open_action.triggered.connect(lambda: (window.show(), window.raise_(), window.activateWindow()))
        check_action = QAction("Check for updates", qt_app)
        check_action.triggered.connect(window.check_updates)
        folder_action = QAction("Open downloads folder", qt_app)
        folder_action.triggered.connect(open_downloads_folder)
        exit_action = QAction("Exit SaveVido", qt_app)
        exit_action.triggered.connect(qt_app.quit)
        menu.addAction(open_action); menu.addAction(check_action); menu.addAction(folder_action)
        menu.addSeparator(); menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: (window.show(), window.raise_(), window.activateWindow()) if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
    else:
        QMessageBox.warning(window, "SaveVido", "The system tray is unavailable. SaveVido will remain open in its app window.")
    window.show()
    if savevido_app.TELEMETRY_ENABLED:
        heartbeat = QTimer(qt_app)
        heartbeat.setInterval(5 * 60 * 1000)
        heartbeat.timeout.connect(lambda: savevido_app.send_telemetry("app_heartbeat"))
        heartbeat.start()
    timer = QTimer(qt_app)
    timer.setInterval(6 * 60 * 60 * 1000)
    timer.timeout.connect(lambda: window.check_updates(silent=True))
    timer.start()
    QTimer.singleShot(5000, lambda: window.check_updates(silent=True))
    qt_app.aboutToQuit.connect(server.shutdown)
    qt_app.aboutToQuit.connect(server.server_close)
    sys.exit(qt_app.exec())

if __name__ == "__main__":
    main()

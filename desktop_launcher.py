"""SaveVido native Windows desktop launcher with incremental update support."""
import json, os, re, subprocess, sys, threading
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
ICON_PATH = RESOURCE_ROOT / "static" / "icon-512.png"

def read_app_version():
    try:
        return str(json.loads((RESOURCE_ROOT / "build_info.json").read_text(encoding="utf-8-sig")).get("version") or "0.0.0")
    except Exception:
        return "0.0.0"

APP_VERSION = read_app_version()

def version_tuple(value):
    parts = re.findall(r"\d+", str(value))
    return tuple(int(part) for part in parts) if parts else (0,)

class UpdateChecker(QObject):
    finished = Signal(dict)
    def check(self):
        def worker():
            try:
                response = requests.get(RELEASE_API, headers={"Accept": "application/vnd.github+json"}, timeout=(5, 15))
                response.raise_for_status()
                release = response.json()
                tag = str(release.get("tag_name", "")).lstrip("v")
                if not tag or version_tuple(tag) <= version_tuple(APP_VERSION):
                    self.finished.emit({"status": "current", "current_version": APP_VERSION})
                    return
                assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
                manifest_url = assets.get("SaveVido-Update-Manifest.json")
                if not manifest_url:
                    self.finished.emit({"status": "bootstrap", "version": tag, "installer_url": assets.get("SaveVido-Setup.exe", "")})
                    return
                self.finished.emit({"status": "available", "version": tag, "manifest_url": manifest_url})
            except Exception as exc:
                self.finished.emit({"status": "error", "message": f"Could not check for updates. Please check your internet connection and try again. ({exc})"})
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
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

class SaveVidoWindow(QMainWindow):
    def __init__(self, checker, qt_app):
        super().__init__()
        self.checker, self.qt_app = checker, qt_app
        self.pending_manifest_url = None
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

    def dispatch(self, name, data):
        payload = json.dumps(data).replace("</", "<\\/")
        self.browser.page().runJavaScript(f"window.dispatchEvent(new CustomEvent('{name}', {{detail: {payload}}}));")

    def check_updates(self):
        self.dispatch("savevido-update-result", {"status": "checking", "current_version": APP_VERSION})
        self.checker.check()

    def on_update_result(self, data):
        self.pending_manifest_url = data.get("manifest_url")
        self.dispatch("savevido-update-result", data)

    def install_update(self):
        if not self.pending_manifest_url:
            return
        updater = APP_ROOT / "SaveVidoUpdater.exe"
        if getattr(sys, "frozen", False):
            command = [str(updater), "--manifest-url", self.pending_manifest_url, "--app-root", str(APP_ROOT), "--restart"]
        else:
            command = [sys.executable, str(APP_ROOT / "updater.py"), "--manifest-url", self.pending_manifest_url, "--app-root", str(APP_ROOT), "--restart"]
        if not Path(command[0]).exists():
            self.dispatch("savevido-update-result", {"status": "error", "message": "The updater component is missing. Please install the latest bootstrap version."})
            return
        self.dispatch("savevido-update-installing", {})
        subprocess.Popen(command, cwd=str(APP_ROOT), close_fds=True)
        QTimer.singleShot(700, self.qt_app.quit)

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
    timer = QTimer(qt_app)
    timer.setInterval(6 * 60 * 60 * 1000)
    timer.timeout.connect(window.check_updates)
    timer.start()
    QTimer.singleShot(5000, window.check_updates)
    qt_app.aboutToQuit.connect(server.shutdown)
    qt_app.aboutToQuit.connect(server.server_close)
    sys.exit(qt_app.exec())

if __name__ == "__main__":
    main()

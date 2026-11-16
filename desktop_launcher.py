"""SaveVido native Windows desktop launcher.

The downloader runs locally in a background Flask server. The interface is
rendered inside the app's own Qt WebEngine window; it never opens Chrome.
"""
import json
import os
import re
import subprocess
import sys

# Give Windows a stable application identity so the taskbar groups the
# running window with the installed SaveVido shortcut and uses its S icon.
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AZANKHAN.SaveVido")
    except Exception:
        pass
import threading
from pathlib import Path

# Work around legacy graphics drivers on older Windows PCs.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
os.environ.setdefault("QT_OPENGL", "software")

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from werkzeug.serving import make_server
import requests

import app as savevido_app
from app import app

HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "5000"))
APP_URL = f"http://{HOST}:{PORT}"
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))
ICON_PATH = RESOURCE_ROOT / "static" / "icon-512.png"
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/AzanKhan-pk/conver-my-files-to-installer-and-apk-with-GPT/savevido-central-platform/platform/release-config.json"


def read_app_version():
    try:
        data = json.loads((RESOURCE_ROOT / "build_info.json").read_text(encoding="utf-8-sig"))
        return str(data.get("version") or "0.0.0")
    except Exception:
        return "0.0.0"


APP_VERSION = read_app_version()


def version_tuple(value):
    parts = re.findall(r"\d+", str(value))
    return tuple(int(part) for part in parts) if parts else (0,)


class UpdateChecker(QObject):
    update_available = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.offered_version = None

    def check(self):
        def worker():
            try:
                response = requests.get(UPDATE_MANIFEST_URL, timeout=(5, 10))
                response.raise_for_status()
                manifest = response.json()
                channel = manifest.get("channels", {}).get("windows", {})
                latest = str(channel.get("version") or manifest.get("current_version") or "")
                download_url = str(channel.get("download_url") or "")
                if (
                    latest
                    and download_url.startswith("https://")
                    and version_tuple(latest) > version_tuple(APP_VERSION)
                    and latest != self.offered_version
                ):
                    self.offered_version = latest
                    self.update_available.emit(latest, download_url)
            except Exception:
                # Offline or unavailable update service must never stop the downloader.
                pass

        threading.Thread(target=worker, name="SaveVidoUpdateCheck", daemon=True).start()

server = make_server(HOST, PORT, app, threaded=True)
server_thread = threading.Thread(
    target=server.serve_forever,
    name="SaveVidoLocalServer",
    daemon=True,
)


class SaveVidoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SaveVido {APP_VERSION} — Video Downloader")
        self.setMinimumSize(900, 650)
        self.resize(1180, 780)
        if ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.browser = QWebEngineView(self)
        self.browser.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.browser.setUrl(QUrl(APP_URL))
        self.setCentralWidget(self.browser)

    def closeEvent(self, event):
        # Keep the downloader available in the notification area.
        event.ignore()
        self.hide()


def open_downloads_folder():
    folder = Path(savevido_app.DOWNLOAD_ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(folder))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def main():
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("SaveVido")
    qt_app.setQuitOnLastWindowClosed(False)
    if ICON_PATH.is_file():
        qt_app.setWindowIcon(QIcon(str(ICON_PATH)))

    server_thread.start()
    window = SaveVidoWindow()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            window,
            "SaveVido",
            "The system tray is unavailable. SaveVido will remain open in its app window.",
        )
    else:
        tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), qt_app)
        tray.setToolTip("SaveVido — Video Downloader")
        menu = QMenu()
        open_action = QAction("Open SaveVido", qt_app)
        open_action.triggered.connect(lambda: (window.show(), window.raise_(), window.activateWindow()))
        folder_action = QAction("Open downloads folder", qt_app)
        folder_action.triggered.connect(open_downloads_folder)
        exit_action = QAction("Exit SaveVido", qt_app)
        exit_action.triggered.connect(qt_app.quit)
        menu.addAction(open_action)
        menu.addAction(folder_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: (window.show(), window.raise_(), window.activateWindow())
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        tray.show()

    window.show()

    # Check shortly after startup and then every six hours. The check runs in
    # a worker thread; all dialogs and browser actions stay on the Qt UI thread.
    updater = UpdateChecker(qt_app)

    def show_update_notice(version, download_url):
        answer = QMessageBox.question(
            window,
            "SaveVido update available",
            f"SaveVido {version} is available. You are using version {APP_VERSION}.\\n\\n"
            "Would you like to download and install the update now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(download_url))

    updater.update_available.connect(show_update_notice)
    update_timer = QTimer(qt_app)
    update_timer.setInterval(6 * 60 * 60 * 1000)
    update_timer.timeout.connect(updater.check)
    update_timer.start()
    QTimer.singleShot(5000, updater.check)

    qt_app.aboutToQuit.connect(server.shutdown)
    qt_app.aboutToQuit.connect(server.server_close)
    exit_code = qt_app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

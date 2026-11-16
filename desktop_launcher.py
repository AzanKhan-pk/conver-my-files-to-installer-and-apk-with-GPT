"""SaveVido native Windows desktop launcher.

The downloader runs locally in a background Flask server. The interface is
rendered inside the app's own Qt WebEngine window; it never opens Chrome.
"""
import os
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

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from werkzeug.serving import make_server

import app as savevido_app
from app import app

HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "5000"))
APP_URL = f"http://{HOST}:{PORT}"
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))
ICON_PATH = RESOURCE_ROOT / "static" / "icon-512.png"

server = make_server(HOST, PORT, app, threaded=True)
server_thread = threading.Thread(
    target=server.serve_forever,
    name="SaveVidoLocalServer",
    daemon=True,
)


class SaveVidoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SaveVido — Video Downloader")
        self.setMinimumSize(900, 650)
        self.resize(1180, 780)
        if ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self.browser = QWebEngineView(self)
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
    qt_app.aboutToQuit.connect(server.shutdown)
    qt_app.aboutToQuit.connect(server.server_close)
    exit_code = qt_app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

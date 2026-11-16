"""SaveVido Windows tray launcher.

Run with: python desktop_launcher.py
The Flask download engine stays alive while the browser window is closed.
Interrupted jobs are persisted and can be resumed after SaveVido is restarted.
"""
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

# Use the bundled FFmpeg tools when running the packaged Windows application.
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BUNDLED_FFMPEG = APP_ROOT / "ffmpeg"
if BUNDLED_FFMPEG.is_dir():
    os.environ["PATH"] = str(BUNDLED_FFMPEG) + os.pathsep + os.environ.get("PATH", "")

import pystray
from PIL import Image, ImageDraw
from werkzeug.serving import make_server

import app as savevido_app
from app import app

HOST = "127.0.0.1"
PORT = int(os.getenv("PORT", "5000"))
APP_URL = f"http://{HOST}:{PORT}"


def make_icon_image():
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = resource_root / "static" / "logo.png"
    if icon_path.is_file():
        try:
            return Image.open(icon_path).convert("RGBA").resize((64, 64))
        except Exception:
            pass

    image = Image.new("RGBA", (64, 64), (18, 20, 32, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((5, 5, 59, 59), radius=13, fill=(180, 235, 70, 255))
    draw.text((17, 17), "S", fill=(18, 20, 32, 255))
    return image


def open_savevido(icon, item):
    webbrowser.open(APP_URL)


def open_downloads_folder(icon, item):
    folder = Path(savevido_app.DOWNLOAD_ROOT)
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(folder))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def exit_savevido(icon, item):
    icon.stop()
    threading.Thread(target=server.shutdown, daemon=True).start()


server = make_server(HOST, PORT, app, threaded=True)
server_thread = threading.Thread(
    target=server.serve_forever,
    name="SaveVidoServer",
    daemon=True,
)


def main():
    server_thread.start()
    webbrowser.open(APP_URL)
    menu = pystray.Menu(
        pystray.MenuItem("Open SaveVido", open_savevido, default=True),
        pystray.MenuItem("Open downloads folder", open_downloads_folder),
        pystray.MenuItem("Exit SaveVido", exit_savevido),
    )
    icon = pystray.Icon("SaveVido", make_icon_image(), "SaveVido", menu)
    try:
        icon.run()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()

import os
import re
import shutil
import subprocess
import sys
import smtplib
import sqlite3
import json
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
import requests
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from yt_dlp.utils import DownloadCancelled as YtDlpStopSignal
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)

BASE_DIR = Path(__file__).resolve().parent

# Keep writable user data out of Program Files / the bundled application folder.
if getattr(sys, "frozen", False) and os.name == "nt":
    APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SaveVido"
else:
    APP_DATA_DIR = BASE_DIR
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DATA_DIR / "analytics.db"

# Keep partial downloads outside the OS temp directory so they survive
# reboots and Windows temporary-file cleanup.
# Prefer a simple C:\\Downloads\\SaveVido destination on Windows. If the
# machine restricts writes to the drive root, fall back to the user's Downloads.
if os.name == "nt":
    DEFAULT_DOWNLOAD_ROOT = Path(os.getenv("SystemDrive", "C:")) / "Downloads" / "SaveVido"
else:
    DEFAULT_DOWNLOAD_ROOT = Path.home() / "Downloads" / "SaveVido"
DOWNLOAD_ROOT = Path(os.getenv("SAVEVIDO_DOWNLOAD_DIR", str(DEFAULT_DOWNLOAD_ROOT))).expanduser()
try:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    DOWNLOAD_ROOT = (Path.home() / "Downloads" / "SaveVido").expanduser()
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_ROOT = DOWNLOAD_ROOT / ".jobs"
JOBS_ROOT.mkdir(parents=True, exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY", "change-this-secret-key"
)

# Optional, consent-based telemetry. No owner/database secret is shipped in SaveVido.
TELEMETRY_ENDPOINT = "https://savevido-owner-dashboard.vercel.app/api/track"
TELEMETRY_ENABLED = False
TELEMETRY_APP_VERSION = "unknown"
TELEMETRY_SESSION_ID = None


def configure_telemetry(app_version="unknown", enabled=False):
    """Enable anonymous analytics only after the user opts in at first launch."""
    global TELEMETRY_ENABLED, TELEMETRY_APP_VERSION, TELEMETRY_SESSION_ID
    TELEMETRY_ENABLED = bool(enabled)
    TELEMETRY_APP_VERSION = str(app_version or "unknown")[:32]
    if not TELEMETRY_ENABLED:
        return
    session_file = APP_DATA_DIR / "telemetry-session-id"
    try:
        value = session_file.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ValueError("invalid analytics session id")
    except Exception:
        value = uuid.uuid4().hex
        try:
            session_file.write_text(value, encoding="utf-8")
        except OSError:
            pass
    TELEMETRY_SESSION_ID = value


def send_telemetry(event_type, source_url=None, error=None, file_type=None):
    """Fire-and-forget; analytics failures must never slow or break a download."""
    if not TELEMETRY_ENABLED or not TELEMETRY_SESSION_ID:
        return
    if event_type not in {"app_open", "app_heartbeat", "download_succeeded", "download_failed"}:
        return
    try:
        source_host = (urlparse(str(source_url)).hostname or "").lower()[:180] if source_url else None
        message = ""
        if error:
            message = re.sub(r"https?://\S+", "[source URL hidden]", str(error), flags=re.I)
            message = re.sub(r"(?i)(token|password|secret|key)=([^&\s]+)", r"\1=[hidden]", message)
            message = re.sub(r"\s+", " ", message).strip()[:180]
        payload = {
            "event_type": event_type, "platform": "windows",
            "session_id": TELEMETRY_SESSION_ID, "app_version": TELEMETRY_APP_VERSION,
            "source_host": source_host, "file_type": str(file_type or "")[:12] or None,
            "error_code": ("network_error" if error and "network" in message.lower() else "download_error") if error else None,
            "error_message": message or None,
        }
        def deliver():
            try:
                requests.post(TELEMETRY_ENDPOINT, json=payload, timeout=(2, 3))
            except Exception:
                app.logger.debug("SaveVido telemetry delivery skipped", exc_info=True)
        threading.Thread(target=deliver, name="SaveVidoTelemetry", daemon=True).start()
    except Exception:
        app.logger.debug("SaveVido telemetry preparation skipped", exc_info=True)



MIN_VALID_FILE_BYTES = 1024

QUALITY_HEIGHTS = {
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "4K": 2160,
}


ALLOWED_HOSTS = {
    # YouTube
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "ytimg.com", "i.ytimg.com", "img.youtube.com",
    "googlevideo.com",

    # TikTok
    "tiktok.com", "www.tiktok.com",
    "vm.tiktok.com", "vt.tiktok.com",
    "tiktokcdn.com", "tiktokv.com",
    "tiktokcdn-us.com", "muscdn.com",
    "byteoversea.com",

    # Instagram
    "instagram.com", "www.instagram.com",
    "cdninstagram.com", "scontent.cdninstagram.com",
    "fbcdn.net",

    # Facebook
    "facebook.com", "www.facebook.com",
    "m.facebook.com", "fb.watch",
    "fbcdn.net", "fbsbx.com",
    "video.xx.fbcdn.net",

    # X / Twitter
    "twitter.com", "www.twitter.com",
    "x.com", "www.x.com",
    "twimg.com", "pbs.twimg.com",
    "video.twimg.com",

    # Reddit
    "reddit.com", "www.reddit.com",
    "old.reddit.com", "new.reddit.com",
    "v.redd.it", "redd.it",
    "redditmedia.com", "redditstatic.com",
    "preview.redd.it",

    # Vimeo
    "vimeo.com", "www.vimeo.com",
    "player.vimeo.com",
    "i.vimeocdn.com", "vod-progressive.akamaized.net",

    # Dailymotion
    "dailymotion.com", "www.dailymotion.com",
    "dai.ly", "dmcdn.net",
    "s1.dmcdn.net",

    # Twitch
    "twitch.tv", "www.twitch.tv",
    "m.twitch.tv", "clips.twitch.tv",
    "ttvnw.net", "jtvnw.net",
    "twitchcdn.net",

    # SoundCloud
    "soundcloud.com", "www.soundcloud.com",
    "snd.sc", "sndcdn.com",

    # Bilibili
    "bilibili.com", "www.bilibili.com",
    "b23.tv", "hdslb.com",
    "bilivideo.com",

    # Pinterest
    "pinterest.com", "www.pinterest.com",
    "pin.it", "www.pin.it",
    "i.pinimg.com", "images.pinimg.com",
    "v.pinimg.com",

    # Image hosting
    "imgur.com", "i.imgur.com",
    "imagebam.com", "imageshack.com",
    "postimg.cc", "postimages.org",

    # Common CDN / media hosting
    "cloudinary.com",
    "res.cloudinary.com",
    "akamaized.net",
    "akamaihd.net",
    "cloudfront.net",
    "fastly.net",
    "cdn.jsdelivr.net",
    "images.unsplash.com",
}


# yt-dlp source hosts enabled by SaveVido.
# Keep this list limited to mainstream/general-purpose platforms; yt-dlp's
# full extractor catalogue also contains adult-content and other unsuitable sources.
SAFE_YTDLP_SOURCE_HOSTS = {
    "tiktok.com", "instagram.com", "facebook.com", "fb.watch",
    "twitter.com", "x.com", "reddit.com", "redd.it", "v.redd.it",
    "vimeo.com", "dailymotion.com", "dai.ly", "twitch.tv",
    "soundcloud.com", "snd.sc", "bilibili.com", "b23.tv",
    "pinterest.com", "pin.it", "archive.org", "bandcamp.com",
    "mixcloud.com", "streamable.com", "rumble.com",
}


DOWNLOAD_JOBS = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()
JOB_LAST_PERSISTED = {}

FFMPEG_PATH = (
    os.getenv("FFMPEG_PATH")
    or shutil.which("ffmpeg")
)

FFPROBE_PATH = (
    os.getenv("FFPROBE_PATH")
    or shutil.which("ffprobe")
)

FFMPEG_AVAILABLE = bool(FFMPEG_PATH and FFPROBE_PATH)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                platform TEXT NOT NULL,
                quality TEXT NOT NULL,
                file_type TEXT NOT NULL,
                source_url TEXT,
                created_at TEXT NOT NULL,
                job_id TEXT,
                file_path TEXT,
                file_size INTEGER
            );

            CREATE TABLE IF NOT EXISTS download_jobs (
                job_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        # Migrate existing SaveVido databases without deleting old history.
        existing_columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(downloads)"
            ).fetchall()
        }
        for column, definition in (
            ("job_id", "TEXT"),
            ("file_path", "TEXT"),
            ("file_size", "INTEGER"),
        ):
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE downloads ADD COLUMN {column} {definition}"
                )


def load_download_location():
    """Restore the user's chosen download folder from local app settings."""
    global DOWNLOAD_ROOT, JOBS_ROOT
    with get_db() as connection:
        row = connection.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = ?",
            ("download_root",),
        ).fetchone()
    if row:
        candidate = Path(row["setting_value"]).expanduser()
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            DOWNLOAD_ROOT = candidate.resolve()
            JOBS_ROOT = DOWNLOAD_ROOT / ".jobs"
            JOBS_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError:
            app.logger.exception("Could not restore SaveVido download folder")


def save_job_state(job):
    """Persist one job snapshot so it survives app and computer restarts."""
    if not job or not job.get("id"):
        return
    payload = json.dumps(job, ensure_ascii=False)
    with get_db() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO download_jobs(job_id, payload, updated_at)
            VALUES (?, ?, ?)
            """,
            (job["id"], payload, now_iso()),
        )


def restore_download_jobs():
    """Load saved jobs and turn interrupted jobs into resumable paused jobs."""
    with get_db() as connection:
        rows = connection.execute(
            "SELECT job_id, payload FROM download_jobs"
        ).fetchall()

    for row in rows:
        try:
            job = json.loads(row["payload"])
            if job.get("status") in {
                "starting", "preparing", "downloading", "processing"
            }:
                job["status"] = "paused"
                job["speed"] = 0
                job["eta"] = None
                job["pause_requested"] = False
                job["cancel_requested"] = False
                job["error"] = "App restarted. Press Resume to continue."
            DOWNLOAD_JOBS[job["id"]] = job
            save_job_state(job)
        except (ValueError, TypeError, KeyError):
            app.logger.exception("Could not restore a saved download job")


def now_iso():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def send_notification(subject, body):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("NOTIFICATION_EMAIL")

    if not all([
        smtp_host,
        smtp_username,
        smtp_password,
        recipient,
    ]):
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_username
    message["To"] = recipient
    message.set_content(body)

    try:
        with smtplib.SMTP(
            smtp_host, smtp_port, timeout=15
        ) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(message)

    except Exception as error:
        app.logger.warning(
            "Notification email failed: %s", error
        )


def clean_url(value):
    value = (value or "").strip()

    if not value:
        raise ValueError("Please enter a video URL.")

    if "://" not in value:
        value = "https://" + value

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Please enter a valid HTTP or HTTPS URL.")

    if not host or not parsed.netloc:
        raise ValueError("Please enter a valid video URL.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid video URL.")

    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Please enter a public website URL.")

    # Exact domain-boundary matching prevents lookalike hosts such as
    # youtube.com.example.org from being treated as YouTube.
    safe_host = any(
        host == domain or host.endswith("." + domain)
        for domain in SAFE_YTDLP_SOURCE_HOSTS
    )
    if not safe_host:
        raise ValueError(
            f"This platform is not enabled in SaveVido: {host}"
        )

    return value



def platform_for(url):
    host = (urlparse(url).hostname or "").lower()
    host = host.removeprefix("www.")

    if host in {
        "youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
        "youtu.be",
    }:
        return "YouTube"

    if host in {
        "tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }:
        return "TikTok"

    if host == "instagram.com":
        return "Instagram"

    if host in {
        "facebook.com",
        "m.facebook.com",
        "fb.com",
        "fb.watch",
    }:
        return "Facebook"

    if host in {"twitter.com", "x.com"}:
        return "X / Twitter"

    if host in {
        "reddit.com",
        "old.reddit.com",
        "new.reddit.com",
        "v.redd.it",
        "redd.it",
    }:
        return "Reddit"

    if host in {"vimeo.com", "player.vimeo.com"}:
        return "Vimeo"

    if host in {"dailymotion.com", "dai.ly"}:
        return "Dailymotion"

    if host in {
        "twitch.tv",
        "clips.twitch.tv",
        "m.twitch.tv",
    }:
        return "Twitch"

    if host in {"soundcloud.com", "snd.sc"}:
        return "SoundCloud"

    if host in {"bilibili.com", "b23.tv"}:
        return "Bilibili"

    if host in {
        "pinterest.com",
        "pin.it",
        "i.pinimg.com",
        "images.pinimg.com",
    }:
        return "Pinterest"

    return host or "Unknown"



def strip_ansi(text):
    return ANSI_ESCAPE_RE.sub("", text or "")


def humanize_error(error):
    message = strip_ansi(str(error)).strip()

    if message.startswith("ERROR: "):
        message = message[len("ERROR: "):]

    lowered = message.lower()

    if "unsupported url" in lowered:
        return (
            "The extractor does not support this URL. "
            "Allowing a domain does not guarantee that "
            "yt-dlp can download its media."
        )

    if "private video" in lowered or (
        "private" in lowered and "video" in lowered
    ):
        return "This media is private and cannot be downloaded."

    if "timed out" in lowered or "timeout" in lowered:
        return (
            "The social media site took too long to respond. "
            "Please try again shortly; the app stopped waiting to avoid a long delay."
        )

    if (
        ("permission denied" in lowered or "unable to open database file" in lowered)
        and ("cookie" in lowered or "cookies" in lowered)
    ):
        return (
            "The browser's cookie database could not be read. "
            "Close Chrome completely, then restart the app and try again. "
            "If it still fails, your browser may restrict access to its cookie store. "
            "Only use your own authorized account session; never share cookie files."
        )

    if any(word in lowered for word in (
        "login", "sign in", "cookies"
    )):
        return (
            "This media requires an authorized session. In the local app, "
            "enable 'Use my browser session' and try again. If the browser "
            "cookie database is locked, close the browser and restart the app. "
            "Use only content your account is allowed to view."
        )

    if "drm" in lowered:
        return "This media is DRM-protected."

    if "geo" in lowered and "restrict" in lowered:
        return "This media is region-restricted."

    if "video unavailable" in lowered:
        return "The media is unavailable or the URL is incorrect."

    if (
        "no video formats" in lowered
        or "requested format is not available" in lowered
    ):
        return (
            "No suitable media format was found. "
            "Try another quality."
        )

    if "ffprobe" in lowered or "ffmpeg" in lowered:
        return (
            "FFmpeg could not process this media. "
            "Check the server installation."
        )

    if not message:
        return "An unknown error occurred."

    return message[:300]
def is_network_error(error):
    message = str(error).lower()
    return any(item in message for item in (
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "connection refused",
        "network is unreachable",
        "temporary failure",
        "incomplete read",
        "remote end closed",
        "connection error",
        "urlopen error",
        "http error 429",
        "http error 502",
        "http error 503",
        "http error 504",
    ))


def find_stop_signal(error):
    seen = set()
    current = error

    while current is not None and id(current) not in seen:
        if isinstance(current, YtDlpStopSignal):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__

    return None


def base_ydl_options():
    options = {
        # Shorter retry/timeout windows keep metadata fetching responsive.
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 1,
        "socket_timeout": 12,
        # Parallel fragment requests can improve supported media downloads.
        "concurrent_fragment_downloads": 4,
    }

    if FFMPEG_PATH:
        ffmpeg_path = Path(FFMPEG_PATH)
        options["ffmpeg_location"] = str(
            ffmpeg_path.parent
            if ffmpeg_path.is_file()
            else ffmpeg_path
        )

    cookies_path = os.getenv("COOKIES_FILE", "").strip()

    if Path(cookies_path).is_file():
        options["cookiefile"] = cookies_path

    return options


def extract_info_with_retry(url, download=False, options=None):
    options = options or base_ydl_options()

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=download)

    except Exception as error:
        if find_stop_signal(error):
            raise

        host = (urlparse(url).hostname or "").lower()
        match = re.search(r"/video/(\d+)", url)

        if "tiktok.com" in host and match:
            retry_url = (
                "https://www.tiktok.com/@_/video/"
                + match.group(1)
            )

            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(
                    retry_url, download=download
                )

        raise


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"
}

# Safe, non-adult source platforms enabled for image preview/selection.
# Other video-only platforms continue through the existing yt-dlp route.
SAFE_IMAGE_SOURCE_HOSTS = {
    "tiktok.com", "instagram.com", "facebook.com", "fb.com", "fb.watch",
    "pinterest.com", "pin.it", "x.com", "twitter.com", "reddit.com", "redd.it",
    "youtube.com", "youtube-nocookie.com", "youtu.be",
    "vimeo.com", "dailymotion.com", "dai.ly",
    "twitch.tv", "soundcloud.com", "snd.sc",
    "bilibili.com", "b23.tv", "imgur.com",
    "postimg.cc", "postimages.org", "imageshack.com",
    # Public image/CDN hosts used by the supported safe platforms
    "i.pinimg.com", "images.pinimg.com", "fbcdn.net", "fbsbx.com",
    "cdninstagram.com", "tiktokcdn.com", "tiktokv.com",
    "byteoversea.com", "twimg.com", "redditmedia.com",
    "ytimg.com", "vimeocdn.com", "dmcdn.net",
    "ttvnw.net", "jtvnw.net", "twitchcdn.net", "sndcdn.com",
    "hdslb.com", "cloudinary.com", "res.cloudinary.com",
    "cloudfront.net", "fastly.net", "images.unsplash.com",
}

def validate_image_source_url(url):
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not any(host == domain or host.endswith("." + domain)
               for domain in SAFE_IMAGE_SOURCE_HOSTS):
        raise ValueError(
            "Image selection is enabled only for supported, safe image platforms."
        )


def facebook_request_session():
    """Create a session using cookies only when the user explicitly configures them."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    })

    return session


def normalize_gallery_url(url):
    """Normalize social post links and safely resolve supported short links."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")

    # Resolve Facebook share links to the final Facebook post URL.
    # This is a normal public redirect request, not an authentication bypass.
    should_resolve_facebook = (
        host in {"facebook.com", "m.facebook.com"}
        and parsed.path.startswith("/share/")
    )
    if host in {"pin.it", "fb.watch"} or should_resolve_facebook:
        try:
            response = facebook_request_session().get(
                url,
                allow_redirects=True,
                timeout=(5, 10),
            )
            final = urlparse(response.url)
            final_host = (final.hostname or "").lower().removeprefix("www.")
            allowed_hosts = (
                {"pinterest.com", "m.pinterest.com"}
                if host == "pin.it"
                else {"facebook.com", "m.facebook.com", "fb.watch"}
            )
            if (
                final.scheme in {"http", "https"}
                and (final_host in allowed_hosts or
                     (host != "pin.it" and final_host.endswith(".facebook.com")))
            ):
                if host == "pin.it":
                    match = re.search(r"/pin/(\d+)", final.path)
                    if match:
                        return f"https://www.pinterest.com/pin/{match.group(1)}/"
                return response.url.split("#", 1)[0]
        except requests.RequestException as error:
            app.logger.warning("Could not resolve %s link: %s", host, error)

    # Normalize Instagram post links by dropping tracking query parameters.
    if host == "instagram.com" and re.match(r"^/(p|reel|tv)/[^/]+", parsed.path):
        return "https://www.instagram.com" + parsed.path.rstrip("/") + "/"

    # Remove Pinterest tracking suffixes while preserving the numeric pin ID.
    if host in {"pinterest.com", "m.pinterest.com"}:
        match = re.search(r"/pin/(\d+)", parsed.path)
        if match:
            return f"https://www.pinterest.com/pin/{match.group(1)}/"

    return url.split("#", 1)[0]


def _is_platform_image_url(media_url, platform):
    """Accept normal image extensions and extensionless URLs from trusted CDNs."""
    try:
        parsed = urlparse(media_url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        extension = Path(parsed.path).suffix.lower()
        if extension:
            return extension in IMAGE_EXTENSIONS
        if platform == "Facebook":
            return (
                host.endswith("fbcdn.net") or host.endswith("fbsbx.com")
            ) and bool(parsed.path)
        if platform == "Instagram":
            return host.endswith("cdninstagram.com") or host.endswith("fbcdn.net")
    except Exception:
        return False
    return False


def facebook_page_image_urls(url):
    """Extract image URLs that Facebook itself exposes in the accessible page HTML."""
    try:
        response = facebook_request_session().get(
            url,
            allow_redirects=True,
            timeout=(6, 10),
        )
    except requests.Timeout as error:
        raise TimeoutError(
            "Facebook took too long to respond while checking this post."
        ) from error
    except requests.RequestException as error:
        app.logger.warning("Could not read Facebook post page: %s", error)
        return []

    final = urlparse(response.url)
    final_host = (final.hostname or "").lower().removeprefix("www.")
    if not (
        final_host == "facebook.com"
        or final_host.endswith(".facebook.com")
    ):
        return []

    if (
        "/login" in final.path.lower()
        or "/checkpoint" in final.path.lower()
        or response.status_code in {401, 403}
    ):
        raise PermissionError(
            "Facebook requires an authorized session to read this post. "
            "Only content your account is allowed to view can be processed."
        )

    if response.status_code >= 400:
        app.logger.info("Facebook post page returned HTTP %s", response.status_code)
        return []

    # Facebook embeds CDN URLs with escaped slashes and HTML entities.
    page = (response.text or "")
    page = page.replace("\\/", "/").replace("\\u0026", "&")
    from html import unescape
    page = unescape(page)

    image_urls = []
    pattern = re.compile(r"""https?://[^\s"'<>\\]+""", re.IGNORECASE)
    for candidate in pattern.findall(page):
        candidate = candidate.rstrip("),;]")
        if _is_platform_image_url(candidate, "Facebook"):
            if candidate not in image_urls:
                image_urls.append(candidate)
        if len(image_urls) >= 50:
            break

    return image_urls


def facebook_photo_page_urls(url):
    """Find individual photo pages embedded in an accessible Facebook post."""
    try:
        response = facebook_request_session().get(
            url,
            allow_redirects=True,
            timeout=(6, 10),
        )
    except requests.Timeout as error:
        raise TimeoutError(
            "Facebook took too long to respond while checking this post."
        ) from error
    except requests.RequestException as error:
        app.logger.warning("Could not read Facebook photo page links: %s", error)
        return []

    final = urlparse(response.url)
    final_host = (final.hostname or "").lower().removeprefix("www.")
    if not (final_host == "facebook.com" or final_host.endswith(".facebook.com")):
        return []
    if "/login" in final.path.lower() or "/checkpoint" in final.path.lower() or response.status_code in {401, 403}:
        raise PermissionError(
            "Facebook requires an authorized session to read this post. "
            "Only content your account is allowed to view can be processed."
        )
    if response.status_code >= 400:
        return []

    page = (response.text or "").replace("\\/", "/")
    photo_ids = []
    patterns = (
        r"/photo/\?[^\"']*fbid=(\d{6,})",
        r'"fbid"\s*:\s*"?(\d{6,})',
        r"[?&]fbid=(\d{6,})",
    )
    for pattern in patterns:
        for photo_id in re.findall(pattern, page, flags=re.IGNORECASE):
            if photo_id not in photo_ids:
                photo_ids.append(photo_id)

    return [
        f"https://www.facebook.com/photo/?fbid={photo_id}"
        for photo_id in photo_ids[:50]
    ]


def run_gallery_dl_urls(url, browser_cookies=None):
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--get-urls",
    ]

    # Browser cookies are used only after an explicit per-request opt-in
    # from the local desktop app. Never read a server/developer session.
    if browser_cookies:
        allowed_browsers = {"chrome", "edge", "firefox"}
        if browser_cookies not in allowed_browsers:
            raise ValueError("Choose Chrome, Edge, or Firefox for local session access.")
        command.extend(["--cookies-from-browser", browser_cookies])

    urls = [url] if isinstance(url, str) else list(url)
    command.extend(urls)
    source_platform = platform_for(urls[0]) if urls else "unknown"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=18 if source_platform in {"Facebook", "Instagram"} else 35,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        app.logger.warning("gallery-dl timed out for %s: %s", source_platform, error)
        raise TimeoutError(
            f"{source_platform} image extraction timed out after the short response window."
        ) from error
    except OSError as error:
        app.logger.warning("gallery-dl could not process %s: %s", source_platform, error)
        return []

    diagnostic = (result.stderr or "") + "\n" + (result.stdout or "")
    if result.returncode != 0:
        app.logger.warning(
            "gallery-dl extraction failed for %s (exit %s): %s",
            source_platform,
            result.returncode,
            diagnostic[-1200:],
        )

    image_urls = []
    for line in result.stdout.splitlines():
        media_url = line.strip()
        if not media_url.startswith(("https://", "http://")):
            continue
        if _is_platform_image_url(media_url, source_platform) and media_url not in image_urls:
            image_urls.append(media_url)

    if not image_urls and source_platform == "Instagram":
        lowered = diagnostic.lower()
        if (
            ("permission denied" in lowered or "unable to open database file" in lowered)
            and ("cookie" in lowered or "cookies" in lowered)
        ):
            raise PermissionError(
                "Chrome's cookie database could not be read. "
                "Close Chrome completely and restart the app, then try again. "
                "If access is still denied, use another supported, explicitly authorized session method."
            )
        if any(term in lowered for term in (
            "redirect to login", "login required", "login_required",
            "authentication required", "requires authentication",
            "cookies", "please log in",
        )):
            raise PermissionError(
                "Instagram requires an authorized session to access this post. "
                "In the local app, enable 'Use my browser session' and try again. "
                "Only content your account is allowed to view can be processed."
            )
        if any(term in lowered for term in (
            "checkpoint", "challenge_required", "challenge page",
        )):
            raise PermissionError(
                "Instagram is requesting an account security check, so this post "
                "cannot be read by the extractor right now."
            )
        if any(term in lowered for term in (
            "429", "too many requests", "rate limit",
        )):
            raise RuntimeError(
                "Instagram is temporarily limiting requests. Wait a while and try again."
            )

    return image_urls


def get_gallery_image_urls(url, browser_cookies=None):
    url = normalize_gallery_url(url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    is_facebook = (
        host == "facebook.com"
        or host.endswith(".facebook.com")
        or host == "fb.watch"
    )

    if is_facebook:
        # Prefer image URLs explicitly present in the accessible public page.
        # Facebook is not a supported URL in some gallery-dl releases.
        image_urls = facebook_page_image_urls(url)
        if image_urls:
            return image_urls

        # Some accessible posts expose individual photo pages rather than
        # direct CDN URLs. Try those pages as a compatibility fallback.
        photo_pages = facebook_photo_page_urls(url)
        if photo_pages:
            image_urls = run_gallery_dl_urls(photo_pages)
            if image_urls:
                return image_urls
            return facebook_page_image_urls(photo_pages[0])

        return []

    return run_gallery_dl_urls(
        url,
        browser_cookies=browser_cookies if platform_for(url) == "Instagram" else None,
    )


def get_media_info(url):
    # Fetch metadata with a short, bounded network wait. Keep the more
    # resilient defaults for the actual download operation.
    options = base_ydl_options()
    options.update({
        # Fetch is a preview operation: do not spend a long time retrying
        # an unresponsive social site. Actual downloads keep base retries.
        "retries": 0,
        "extractor_retries": 0,
        "socket_timeout": 8,
    })
    return extract_info_with_retry(url, download=False, options=options)


def format_duration(info):
    if info.get("duration_string"):
        return info["duration_string"]

    duration = info.get("duration")

    if duration is None:
        return "Not available"

    duration = int(duration)
    hours, remainder = divmod(duration, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"

    return f"{minutes}:{seconds:02d}"


def format_views(info):
    views = info.get("view_count")

    if isinstance(views, (int, float)):
        return f"{int(views):,}"

    return "Not available"


def choose_video_format(info, requested_height):
    formats = info.get("formats") or []

    heights = sorted({
        int(item["height"])
        for item in formats
        if item.get("height")
        and item.get("vcodec") not in (None, "none")
    })

    available = [
        height for height in heights
        if height <= requested_height
    ]

    source_height = (
        max(available)
        if available
        else min(heights) if heights else requested_height
    )

    selector = f"[height<={requested_height}]"

    if FFMPEG_AVAILABLE:
        selected = (
            f"bestvideo{selector}+bestaudio/"
            f"best{selector}/best"
        )
    else:
        selected = (
            f"best{selector}[acodec!=none]/"
            "best[acodec!=none][vcodec!=none]/best"
        )

    return selected, source_height


def new_download_job(url, mode, quality):
    job_id = uuid.uuid4().hex
    temp_dir = JOBS_ROOT / job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    job = {
        "id": job_id,
        "created_at": now_iso(),
        "url": url,
        "mode": mode,
        "quality": quality,
        "status": "starting",
        "percent": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed": 0,
        "eta": None,
        "error": None,
        "file_path": None,
        "filename": None,
        "title": None,
        "platform": platform_for(url),
        "file_type": "MP3" if mode == "audio" else "MP4",
        "temp_dir": str(temp_dir),
        "pause_requested": False,
        "cancel_requested": False,
    }

    with DOWNLOAD_JOBS_LOCK:
        DOWNLOAD_JOBS[job_id] = job
    save_job_state(job)
    return job_id


def get_job(job_id):
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
    if job:
        return job

    with get_db() as connection:
        row = connection.execute(
            "SELECT payload FROM download_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if not row:
        return None

    try:
        job = json.loads(row["payload"])
    except (ValueError, TypeError):
        return None

    with DOWNLOAD_JOBS_LOCK:
        DOWNLOAD_JOBS[job_id] = job
    return job


def update_job(job_id, persist=True, **values):
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if job:
            job.update(values)
            snapshot = dict(job)
        else:
            snapshot = None
    if snapshot and persist:
        save_job_state(snapshot)
        JOB_LAST_PERSISTED[job_id] = time.monotonic()


def cleanup_job_files(job):
    if job and job.get("temp_dir"):
        shutil.rmtree(job["temp_dir"], ignore_errors=True)


def progress_hook(job_id):
    def hook(data):
        job = get_job(job_id)
        if not job:
            raise YtDlpStopSignal("Download job no longer exists.")

        if job.get("cancel_requested") or job.get("pause_requested"):
            raise YtDlpStopSignal("Download stopped by user.")

        if data.get("status") == "downloading":
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or 0
            )
            percent = downloaded / total * 100 if total else 0
            # A resumed yt-dlp transfer can report a fresh fragment counter.
            # Never let the visible progress move backwards from the saved state.
            downloaded = max(downloaded, int(job.get("downloaded_bytes") or 0))
            total = total or int(job.get("total_bytes") or 0)
            percent = max(
                float(job.get("percent") or 0),
                downloaded / total * 100 if total else 0,
            )
            now = time.monotonic()
            persist = now - JOB_LAST_PERSISTED.get(job_id, 0) >= 2.0
            update_job(
                job_id,
                persist=persist,
                status="downloading",
                downloaded_bytes=downloaded,
                total_bytes=total,
                percent=round(min(percent, 100), 2),
                speed=float(data.get("speed") or 0),
                eta=data.get("eta"),
            )
        elif data.get("status") == "finished":
            update_job(
                job_id,
                status="processing",
                percent=100,
                speed=0,
                eta=0,
            )
    return hook


def find_output_file(temp_dir, mode):
    expected_ext = ".mp3" if mode == "audio" else ".mp4"
    candidates = [
        path for path in Path(temp_dir).glob("*")
        if path.is_file()
        and path.suffix.lower() == expected_ext
        and not path.name.endswith(".part")
    ]
    if not candidates:
        raise RuntimeError(
            f"No completed {expected_ext[1:].upper()} file was produced. "
            "The source may not provide this format."
        )

    final_path = max(candidates, key=lambda path: path.stat().st_size)
    if final_path.stat().st_size < MIN_VALID_FILE_BYTES:
        raise RuntimeError("The downloaded file is empty or incomplete.")

    with final_path.open("rb") as handle:
        header = handle.read(32).lstrip().lower()
    if header.startswith(b"<!doctype") or header.startswith(b"<html"):
        raise RuntimeError("The source returned an HTML error page.")

    return final_path, final_path.stat().st_size


def make_saved_filename(title, extension):
    """Keep the source's real title and add a small SaveVido attribution."""
    clean_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(title or "video"))
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" .")[:150].rstrip(" .")
    if not clean_title:
        clean_title = "video"
    if clean_title.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[1-9]", clean_title.upper()):
        clean_title = "_" + clean_title

    attribution = " (Downloaded from SaveVido)"
    candidate = DOWNLOAD_ROOT / f"{clean_title}{attribution}{extension}"
    number = 2
    while candidate.exists():
        candidate = DOWNLOAD_ROOT / f"{clean_title} ({number}){attribution}{extension}"
        number += 1
    return candidate


def run_download_job(job_id):
    job = get_job(job_id)
    if not job:
        return

    temp_dir = Path(job["temp_dir"])
    url = job["url"]
    mode = job["mode"]
    quality = job["quality"]

    try:
        if not temp_dir.is_dir():
            temp_dir.mkdir(parents=True, exist_ok=True)

        update_job(job_id, status="preparing", error=None)
        info = get_media_info(url)
        title = info.get("title") or "video"
        update_job(job_id, title=title)

        options = base_ydl_options()
        options.update({
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [progress_hook(job_id)],
            "continuedl": True,
            "nopart": False,
        })

        if mode == "audio":
            if not FFMPEG_AVAILABLE:
                raise RuntimeError("MP3 conversion requires FFmpeg and ffprobe.")
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            file_type = "MP3"
        else:
            requested_height = QUALITY_HEIGHTS.get(quality, 720)
            selected_format, source_height = choose_video_format(
                info, requested_height
            )
            app.logger.info(
                "Quality=%s, selected height=%s", quality, source_height
            )
            options["format"] = selected_format
            if FFMPEG_AVAILABLE:
                options["merge_output_format"] = "mp4"
            file_type = "MP4"

        update_job(job_id, status="downloading")
        with yt_dlp.YoutubeDL(options) as ydl:
            # Reuse the metadata already fetched above instead of asking the
            # source for the same page a second time (often a costly request).
            downloaded_info = ydl.process_ie_result(info, download=True)

        final_path, final_size = find_output_file(temp_dir, mode)
        title = downloaded_info.get("title") or title
        # Move the finished media out of the hidden job workspace into the
        # single SaveVido download folder, using the original media title.
        destination = make_saved_filename(title, final_path.suffix.lower())
        shutil.move(str(final_path), str(destination))
        final_path = destination
        final_size = final_path.stat().st_size
        platform = platform_for(url)

        with get_db() as connection:
            connection.execute(
                """
                INSERT INTO downloads
                (title, platform, quality, file_type, source_url, created_at,
                 job_id, file_path, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title, platform, quality, file_type, url, now_iso(),
                    job_id, str(final_path), final_size,
                ),
            )

        update_job(
            job_id,
            status="completed",
            downloaded_bytes=final_size,
            total_bytes=final_size,
            percent=100,
            speed=0,
            eta=0,
            file_path=str(final_path),
            filename=final_path.name,
            title=title,
            platform=platform,
            file_type=file_type,
            file_size=final_size,
        )
        send_telemetry("download_succeeded", source_url=url, file_type=file_type)

    except Exception as error:
        if find_stop_signal(error):
            current_job = get_job(job_id) or {}
            if current_job.get("cancel_requested"):
                update_job(
                    job_id,
                    status="cancelled",
                    cancel_requested=False,
                )
                cleanup_job_files(current_job)
            else:
                update_job(
                    job_id,
                    status="paused",
                    pause_requested=False,
                    speed=0,
                )
            return

        app.logger.exception("Download job failed")
        current_job = get_job(job_id) or {}
        send_telemetry("download_failed", source_url=url, error=humanize_error(error), file_type=current_job.get("file_type"))
        if is_network_error(error):
            update_job(
                job_id,
                status="network_error",
                error="Network error. Check your connection and try resuming.",
                speed=0,
            )
        else:
            update_job(
                job_id,
                status="error",
                error=humanize_error(error),
                speed=0,
            )


@app.route("/api/location-consent", methods=["GET", "POST"])
def location_consent():
    """Persist the one-time location choice locally for this Windows installation."""
    consent_file = APP_DATA_DIR / "location-consent.json"
    if request.method == "GET":
        try:
            value = json.loads(consent_file.read_text(encoding="utf-8"))
            decision = value.get("decision") if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            decision = None
        return jsonify({"decision": decision if decision in ("allowed", "denied") else None})
    payload = request.get_json(silent=True) or {}
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in ("allowed", "denied"):
        return jsonify({"error": "Invalid location consent choice."}), 400
    try:
        consent_file.write_text(json.dumps({"decision": decision, "updated_at": now_iso()}), encoding="utf-8")
    except OSError:
        return jsonify({"error": "Could not save this setting on your device."}), 500
    return jsonify({"ok": True, "decision": decision})


@app.get("/share")
def android_pwa_share_target():
    # Web Share Target support for Android-installed SaveVido PWA.
    shared_url = (
        request.args.get("url")
        or request.args.get("text")
        or ""
    ).strip()
    return render_template("index.html", shared_url=shared_url)


@app.route("/")
def index():
    with get_db() as connection:
        connection.execute(
            "INSERT INTO visits(created_at) VALUES (?)",
            (now_iso(),),
        )
    # On Vercel, serve the official platform page with the app preview and
    # platform download cards. Keep the real downloader UI for the local app.
    if os.getenv("VERCEL") == "1":
        return send_from_directory(
            BASE_DIR / "platform",
            "index.html",
            max_age=0,
        )
    return render_template("index.html")


@app.get("/release-config.json")
def release_config():
    # Read the manifest from the GitHub branch at request time. This means the
    # already-deployed website sees each successfully published release without
    # waiting for a separate Vercel deployment.
    manifest_url = (
        "https://raw.githubusercontent.com/"
        "AzanKhan-pk/conver-my-files-to-installer-and-apk-with-GPT/"
        "savevido-central-platform/platform/release-config.json"
    )
    try:
        manifest_response = requests.get(manifest_url, timeout=8)
        manifest_response.raise_for_status()
        manifest_data = manifest_response.json()
        if not isinstance(manifest_data, dict):
            raise ValueError("Release manifest must be a JSON object.")
        response = jsonify(manifest_data)
    except Exception:
        # Keep the last bundled manifest available if GitHub is temporarily down.
        response = send_from_directory(
            BASE_DIR / "platform",
            "release-config.json",
            mimetype="application/json",
            max_age=0,
        )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/platform/<path:filename>")
def platform_asset(filename):
    return send_from_directory(
        BASE_DIR / "platform",
        filename,
        max_age=0,
    )


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/ads.txt")
def ads_txt():
    return send_from_directory(BASE_DIR, "ads.txt")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(
        BASE_DIR, "manifest.json",
        mimetype="application/manifest+json"
    )


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(
        BASE_DIR, "service-worker.js",
        mimetype="application/javascript"
    )
    response.headers["Cache-Control"] = "no-cache"
    return response

@app.post("/api/info")
def api_info():
    try:
        payload = request.get_json(silent=True) or {}
        raw_url = (payload.get("url") or "").strip()

        if not raw_url:
            return jsonify({
                "ok": False,
                "error": "Please enter a video URL."
            }), 400

        url = clean_url(raw_url)

        # Retrieve metadata using the configured yt-dlp options.
        info = get_media_info(url)

        if not info:
            return jsonify({
                "ok": False,
                "error": "Could not retrieve media information."
            }), 400

        return jsonify({
            "ok": True,
            "video": {
                "id": info.get("id"),
                "title": info.get("title") or "Untitled media",
                "creator": (
                    info.get("uploader")
                    or info.get("channel")
                    or "Unknown creator"
                ),
                "duration": format_duration(info),
                "views": format_views(info),
                "thumbnail": info.get("thumbnail"),
                "platform": platform_for(url),
                "url": url,
            },
        })

    except ValueError as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 400

    except Exception as error:
        app.logger.warning(
            "Media info error: %s", error
        )
        return jsonify({
            "ok": False,
            "error": humanize_error(error),
        }), 400

    except Exception as error:
        app.logger.warning("Info error: %s", error)
        return jsonify({
            "ok": False,
            "error": humanize_error(error),
        }), 400


@app.post("/api/images/info")
def api_images_info():
    try:
        payload = request.get_json(silent=True) or {}
        raw_url = (payload.get("url") or "").strip()

        if not raw_url:
            return jsonify({
                "ok": False,
                "error": "Please enter an image post URL."
            }), 400

        url = clean_url(raw_url)
        validate_image_source_url(url)

        use_browser_session = payload.get("use_browser_session") is True
        browser_name = payload.get("browser") or "chrome"
        browser_cookies = None
        if use_browser_session:
            if request.remote_addr not in {"127.0.0.1", "::1", "localhost"}:
                raise PermissionError(
                    "Browser-session access is available only in the local desktop app. "
                    "A hosted website cannot read cookies from your device."
                )
            if platform_for(url) != "Instagram":
                raise ValueError(
                    "The optional browser session is currently supported for Instagram image posts only."
                )
            if browser_name not in {"chrome", "edge", "firefox"}:
                raise ValueError("Choose Chrome, Edge, or Firefox.")
            browser_cookies = browser_name

        image_urls = get_gallery_image_urls(
            url,
            browser_cookies=browser_cookies,
        )

        if not image_urls:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            is_facebook = (
                host == "facebook.com"
                or host.endswith(".facebook.com")
                or host == "fb.watch"
            )
            message = (
                "Facebook did not expose any individual photo links. "
                "The post may require login, may not be visible to your account, "
                "or may contain no extractable photos. Only content you are authorized to view can be processed."
                if is_facebook
                else "No supported images found in this post."
            )
            return jsonify({
                "ok": False,
                "error": message
            }), 400

        return jsonify({
            "ok": True,
            "count": len(image_urls),
            "platform": platform_for(url),
            "images": [
                {
                    "id": index + 1,
                    "url": image_url
                }
                for index, image_url in enumerate(image_urls)
            ]
        })

    except Exception as error:
        app.logger.exception("Image extraction failed")
        return jsonify({
            "ok": False,
            "error": humanize_error(error)
        }), 400


@app.post("/api/images/download")
def api_images_download():
    """Build a ZIP containing user-selected images from a supported public post."""
    try:
        payload = request.get_json(silent=True) or {}
        url = clean_url(payload.get("url", ""))
        validate_image_source_url(url)

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if not host:
            raise ValueError("Please provide a valid public post URL.")

        raw_ids = payload.get("image_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValueError("Select at least one image to download.")
        if len(raw_ids) > 50:
            raise ValueError("Select no more than 50 images at a time.")

        try:
            selected_ids = sorted({int(value) for value in raw_ids})
        except (TypeError, ValueError):
            raise ValueError("The selected image list is invalid.")

        use_browser_session = payload.get("use_browser_session") is True
        browser_name = payload.get("browser") or "chrome"
        browser_cookies = None
        if use_browser_session:
            if request.remote_addr not in {"127.0.0.1", "::1", "localhost"}:
                raise PermissionError(
                    "Browser-session access is available only in the local desktop app. "
                    "A hosted website cannot read cookies from your device."
                )
            if platform_for(url) != "Instagram":
                raise ValueError(
                    "The optional browser session is currently supported for Instagram image posts only."
                )
            if browser_name not in {"chrome", "edge", "firefox"}:
                raise ValueError("Choose Chrome, Edge, or Firefox.")
            browser_cookies = browser_name

        image_urls = get_gallery_image_urls(
            url,
            browser_cookies=browser_cookies,
        )
        if not image_urls:
            return jsonify({
                "ok": False,
                "error": "No supported images could be found in this post."
            }), 400

        if any(image_id < 1 or image_id > len(image_urls) for image_id in selected_ids):
            raise ValueError("One or more selected images are no longer available. Fetch the album again.")

        archive_buffer = BytesIO()
        total_downloaded = 0

        with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
            for image_id in selected_ids:
                image_url = image_urls[image_id - 1]
                image_host = (urlparse(image_url).hostname or "").lower()
                trusted_host = any(
                    image_host == suffix.lstrip(".") or image_host.endswith(suffix)
                    for suffix in (
                        # TikTok
                        ".tiktokcdn.com", ".tiktokv.com",
                        ".byteoversea.com", ".ibytedtos.com",
                        # Instagram / Facebook
                        ".fbcdn.net", ".fbsbx.com",
                        ".cdninstagram.com",
                        # Pinterest
                        ".pinimg.com",
                        # X / Twitter
                        ".twimg.com",
                        # Reddit
                        ".redditmedia.com", ".redd.it",
                        # Other supported, non-adult media platforms
                        ".ytimg.com",
                        ".vimeocdn.com",
                        ".dmcdn.net",
                        ".ttvnw.net", ".jtvnw.net", ".twitchcdn.net",
                        ".sndcdn.com",
                        ".hdslb.com",
                    )
                )
                if not trusted_host:
                    raise ValueError("The platform returned an unexpected image host.")

                response = requests.get(
                    image_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=(10, 45),
                    stream=True,
                )
                response.raise_for_status()

                image_buffer = BytesIO()
                image_size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    image_size += len(chunk)
                    total_downloaded += len(chunk)
                    if image_size > 25 * 1024 * 1024 or total_downloaded > 100 * 1024 * 1024:
                        raise ValueError("The selected images exceed the download size limit.")
                    image_buffer.write(chunk)

                content_type = (response.headers.get("Content-Type") or "").lower()
                if not content_type.startswith("image/"):
                    raise ValueError(f"{platform_for(url)} returned a file that is not an image.")

                extension = Path(urlparse(image_url).path).suffix.lower()
                if extension not in IMAGE_EXTENSIONS:
                    extension = ".jpg"

                archive.writestr(
                    f"image_{image_id:03d}{extension}",
                    image_buffer.getvalue(),
                )

        archive_buffer.seek(0)
        return send_file(
            archive_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{platform_for(url).lower().replace(' ', '-')}-images.zip",
        )

    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except requests.RequestException as error:
        app.logger.warning("%s image download request failed: %s", platform_for(url), error)
        return jsonify({
            "ok": False,
            "error": f"An image could not be downloaded from {platform_for(url)}. Please fetch the gallery again and retry."
        }), 502
    except Exception as error:
        app.logger.exception("TikTok image ZIP creation failed")
        return jsonify({
            "ok": False,
            "error": humanize_error(error)
        }), 500

@app.post("/api/download")
def api_download():
    try:
        payload = request.get_json(silent=True) or {}
        url = clean_url(payload.get("url", ""))
        mode = payload.get("mode", "video")
        quality = payload.get("quality", "720p")

        if mode not in {"video", "audio"}:
            raise ValueError("Unsupported media type.")

        if mode == "video" and quality not in QUALITY_HEIGHTS:
            raise ValueError("Unsupported video quality.")

        job_id = new_download_job(url, mode, quality)

        threading.Thread(
            target=run_download_job,
            args=(job_id,),
            daemon=True,
        ).start()

        return jsonify({"ok": True, "job_id": job_id})

    except Exception as error:
        app.logger.exception("Could not start download")
        return jsonify({
            "ok": False,
            "error": humanize_error(error),
        }), 400


@app.get("/api/download/<job_id>/status")
def download_status(job_id):
    job = get_job(job_id)

    if not job:
        return jsonify({
            "ok": False,
            "error": "Download job not found.",
        }), 404

    return jsonify({
        "ok": True,
        "job": {
            "id": job["id"],
            "status": job["status"],
            "percent": round(float(job.get("percent", 0)), 2),
            "downloaded_bytes": job.get("downloaded_bytes", 0),
            "total_bytes": job.get("total_bytes", 0),
            "speed": job.get("speed", 0),
            "eta": job.get("eta"),
            "error": job.get("error"),
            "title": job.get("title"),
            "filename": job.get("filename"),
            "file_size": job.get("file_size", 0),
            "file_path": job.get("file_path"),
            "platform": job.get("platform"),
            "quality": job.get("quality"),
            "file_type": job.get("file_type"),
            "mode": job.get("mode"),
        },
    })


@app.post("/api/download/<job_id>/pause")
def pause_download(job_id):
    job = get_job(job_id)

    if not job:
        return jsonify({
            "ok": False,
            "error": "Download job not found.",
        }), 404

    if job["status"] not in {"starting", "preparing", "downloading", "processing"}:
        return jsonify({
            "ok": False,
            "error": "Download is not currently running.",
        }), 400

    update_job(job_id, pause_requested=True)
    return jsonify({"ok": True})


@app.post("/api/download/<job_id>/resume")
def resume_download(job_id):
    job = get_job(job_id)

    if not job:
        return jsonify({
            "ok": False,
            "error": "Download job not found.",
        }), 404

    if job["status"] not in {"paused", "network_error"}:
        return jsonify({
            "ok": False,
            "error": "Download is not paused or waiting for network.",
        }), 400

    update_job(
        job_id,
        status="starting",
        pause_requested=False,
        cancel_requested=False,
        error=None,
    )

    threading.Thread(
        target=run_download_job,
        args=(job_id,),
        daemon=True,
    ).start()

    return jsonify({"ok": True})


@app.post("/api/download/<job_id>/cancel")
def cancel_download(job_id):
    job = get_job(job_id)

    if not job:
        return jsonify({
            "ok": False,
            "error": "Download job not found.",
        }), 404

    if job.get("status") in {"paused", "network_error"}:
        update_job(
            job_id,
            status="cancelled",
            cancel_requested=False,
            pause_requested=False,
            speed=0,
        )
        cleanup_job_files(job)
    else:
        update_job(job_id, cancel_requested=True)
    return jsonify({"ok": True})


@app.get("/api/download/<job_id>/file")
def download_file(job_id):
    job = get_job(job_id)

    if not job:
        return jsonify({
            "ok": False,
            "error": "Download job not found.",
        }), 404

    if job["status"] != "completed":
        return jsonify({
            "ok": False,
            "error": "Download is not ready yet.",
        }), 409

    path = Path(job.get("file_path") or "")
    job_dir = Path(job.get("temp_dir") or "").resolve()

    if (
        not path.is_file()
        or not path.resolve().is_relative_to(job_dir)
    ):
        return jsonify({
            "ok": False,
            "error": "Downloaded file is missing.",
        }), 404

    extension = "mp3" if job["mode"] == "audio" else "mp4"

    safe_name = re.sub(
        r"[^\w\s.-]", "",
        job.get("title") or "video"
    ).strip()[:90] or "video"

    return send_file(
        path,
        as_attachment=True,
        download_name=f"{safe_name}.{extension}",
        mimetype=(
            "audio/mpeg" if extension == "mp3"
            else "video/mp4"
        ),
    )


@app.get("/api/download-location")
def get_download_location():
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"ok": False, "error": "Available only in the local desktop app."}), 403
    return jsonify({"ok": True, "path": str(DOWNLOAD_ROOT)})


@app.post("/api/browse-location")
def browse_download_location():
    global DOWNLOAD_ROOT, JOBS_ROOT
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"ok": False, "error": "Available only in the local desktop app."}), 403

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title="Choose SaveVido download folder",
            initialdir=str(DOWNLOAD_ROOT),
            mustexist=True,
        )
        root.destroy()

        if not selected:
            return jsonify({"ok": True, "cancelled": True, "path": str(DOWNLOAD_ROOT)})

        selected_path = Path(selected).expanduser().resolve()
        selected_path.mkdir(parents=True, exist_ok=True)

        with get_db() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO app_settings(setting_key, setting_value)
                VALUES (?, ?)
                """,
                ("download_root", str(selected_path)),
            )

        DOWNLOAD_ROOT = selected_path
        JOBS_ROOT = DOWNLOAD_ROOT / ".jobs"
        JOBS_ROOT.mkdir(parents=True, exist_ok=True)
        return jsonify({"ok": True, "path": str(DOWNLOAD_ROOT)})

    except Exception as error:
        app.logger.warning("Could not choose download folder: %s", error)
        return jsonify({
            "ok": False,
            "error": "Could not open the folder picker. Use the local Windows desktop app.",
        }), 500


@app.get("/api/history")
def api_download_history():
    with get_db() as connection:
        rows = connection.execute(
            """
            SELECT id, title, platform, quality, file_type, job_id,
                   file_path, file_size, created_at
            FROM downloads
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
        job_rows = connection.execute(
            "SELECT payload, updated_at FROM download_jobs ORDER BY updated_at DESC"
        ).fetchall()

    items = [
        {
            "id": row["id"],
            "title": row["title"],
            "platform": row["platform"],
            "quality": row["quality"],
            "file_type": row["file_type"],
            "job_id": row["job_id"],
            "file_path": row["file_path"],
            "file_size": row["file_size"] or 0,
            "created_at": row["created_at"],
            "status": "completed",
            "file_exists": bool(
                row["file_path"] and Path(row["file_path"]).is_file()
            ),
        }
        for row in rows
    ]

    resumable_states = {
        "paused", "network_error", "starting", "preparing",
        "downloading", "processing",
    }
    for job_row in job_rows:
        try:
            job = json.loads(job_row["payload"])
        except (ValueError, TypeError):
            continue
        if job.get("status") not in resumable_states:
            continue
        job_path = Path(job.get("file_path") or "")
        items.append({
            "id": None,
            "title": job.get("title") or "Download in progress",
            "platform": job.get("platform") or "",
            "quality": job.get("quality") or "",
            "file_type": job.get("file_type") or "",
            "job_id": job.get("id"),
            "file_path": job.get("file_path"),
            "file_size": job.get("file_size") or job.get("downloaded_bytes") or 0,
            "created_at": job.get("created_at") or job_row["updated_at"],
            "status": job.get("status"),
            "percent": job.get("percent") or 0,
            "downloaded_bytes": job.get("downloaded_bytes") or 0,
            "total_bytes": job.get("total_bytes") or 0,
            "error": job.get("error"),
            "file_exists": bool(job_path.is_file()),
        })

    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jsonify({"ok": True, "items": items[:100]})


@app.delete("/api/history/<int:history_id>")
def delete_download_history_item(history_id):
    # This removes only the history row. The downloaded file is untouched.
    with get_db() as connection:
        cursor = connection.execute(
            "DELETE FROM downloads WHERE id = ?",
            (history_id,),
        )
    if cursor.rowcount == 0:
        return jsonify({"ok": False, "error": "History item not found."}), 404
    return jsonify({"ok": True})


@app.post("/api/download/<job_id>/open-folder")
def open_download_folder(job_id):
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"ok": False, "error": "Folder access is available only in the local desktop app."}), 403

    job = get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Download job not found."}), 404

    folder = Path(job.get("temp_dir") or "").resolve()
    if folder.name != job_id or folder.parent.name != ".jobs" or not folder.is_dir():
        return jsonify({"ok": False, "error": "Download folder is not available."}), 404

    try:
        if os.name == "nt":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as error:
        app.logger.warning("Could not open download folder: %s", error)
        return jsonify({"ok": False, "error": "Could not open the download folder."}), 500

    return jsonify({"ok": True})


@app.post("/api/comments")
def api_comments():
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()[:80]
    comment = (payload.get("comment") or "").strip()[:1000]

    if len(name) < 2 or len(comment) < 3:
        return jsonify({
            "ok": False,
            "error": "Add your name and a useful comment.",
        }), 400

    timestamp = now_iso()

    with get_db() as connection:
        connection.execute(
            """
            INSERT INTO comments(name, comment, created_at)
            VALUES (?, ?, ?)
            """,
            (name, comment, timestamp),
        )

    send_notification(
        "SaveVido: new feedback",
        f"User name: {name}\nComment: {comment}\nDate/time: {timestamp}",
    )

    return jsonify({
        "ok": True,
        "message": "Thanks, your feedback is saved.",
    })


@app.route("/admin")
def admin():
    if request.args.get("key") != os.getenv(
        "ADMIN_KEY", "change-admin-key"
    ):
        return "Admin access denied.", 403

    with get_db() as connection:
        visits = connection.execute(
            "SELECT COUNT(*) AS count FROM visits"
        ).fetchone()["count"]

        downloads = connection.execute(
            "SELECT COUNT(*) AS count FROM downloads"
        ).fetchone()["count"]

        comments = connection.execute(
            "SELECT COUNT(*) AS count FROM comments"
        ).fetchone()["count"]

        top_videos = connection.execute(
            """
            SELECT title, COUNT(*) AS count
            FROM downloads
            GROUP BY title
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()

        platforms = connection.execute(
            """
            SELECT platform, COUNT(*) AS count
            FROM downloads
            GROUP BY platform
            ORDER BY count DESC
            """
        ).fetchall()

    return render_template(
        "index.html",
        admin_data={
            "visits": visits,
            "downloads": downloads,
            "comments": comments,
            "top_videos": top_videos,
            "platforms": platforms,
        },
    )


@app.route("/googledd736139896dc604.html")
def google_verification():
    return send_from_directory(
        BASE_DIR, "googledd736139896dc604.html"
    )


@app.get("/about")
def about():
    return render_template("about.html")


@app.get("/how-to-use")
def how_to_use():
    return render_template("how-to-use.html")


@app.get("/faq")
def faq():
    return render_template("faq.html")


@app.get("/terms")
def terms():
    return render_template("terms.html")  

    

init_db()
load_download_location()
restore_download_jobs()

if not FFMPEG_AVAILABLE:
    app.logger.warning(
        "FFmpeg/ffprobe not found. MP3 conversion and merging "
        "separate video/audio streams may not work."
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )

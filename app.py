import os
import re
import shutil
import subprocess
import sys
import smtplib
import sqlite3
import tempfile
import threading
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
DB_PATH = BASE_DIR / "analytics.db"

DOWNLOAD_ROOT = Path(tempfile.gettempdir()) / "SaveVido_downloads"
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY", "change-this-secret-key"
)

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

    # TikTok
    "tiktok.com", "www.tiktok.com",
    "vm.tiktok.com", "vt.tiktok.com",

    # Instagram
    "instagram.com", "www.instagram.com",

    # Facebook
    "facebook.com", "www.facebook.com",
    "m.facebook.com", "fb.watch",

    # X / Twitter
    "twitter.com", "www.twitter.com",
    "x.com", "www.x.com",

    # Reddit
    "reddit.com", "www.reddit.com",
    "old.reddit.com", "new.reddit.com",
    "v.redd.it", "redd.it",

    # Vimeo
    "vimeo.com", "www.vimeo.com",
    "player.vimeo.com",

    # Dailymotion
    "dailymotion.com", "www.dailymotion.com",
    "dai.ly",

    # Twitch
    "twitch.tv", "www.twitch.tv",
    "m.twitch.tv", "clips.twitch.tv",

    # SoundCloud
    "soundcloud.com", "www.soundcloud.com",
    "snd.sc",

    # Bilibili
    "bilibili.com", "www.bilibili.com",
    "b23.tv",

    # Pinterest
    "pinterest.com", "www.pinterest.com",
    "pin.it", "www.pin.it",
    "i.pinimg.com", "images.pinimg.com",

    # Darkero
    "darkero.co",
    "www.darkero.co",
    "darkero.com",
    "www.darkero.com",
    "files.darkero.com",

    # Baddielatina
    "baddielatina.com",
    "www.baddielatina.com",
    "files.baddielatina.com",
}

DOWNLOAD_JOBS = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()

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
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


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
        raise ValueError(
            "Please enter a valid HTTP or HTTPS URL."
        )

    if not host or not parsed.netloc:
        raise ValueError("Please enter a valid video URL.")

    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid video URL.")

    # Existing supported domains
    allowed_bare = {
        domain.lower().rstrip(".").removeprefix("www.")
        for domain in ALLOWED_HOSTS
    }

    bare_host = host.removeprefix("www.")

    # Allow Baddielatina and its subdomains
    is_baddielatina = (
        bare_host == "baddielatina.com"
        or bare_host.endswith(".baddielatina.com")
    )

    if bare_host not in allowed_bare and not is_baddielatina:
        raise ValueError(
            f"This platform is not currently supported: {host}"
        )

    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Please enter a public website URL.")

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
        "darkero.co",
        "darkero.com",
        "files.darkero.com",
    }:
        return "Darkero"

    # Baddielatina
    if host in {
        "baddielatina.com",
        "files.baddielatina.com",
    }:
        return "Baddielatina"

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

    if any(word in lowered for word in (
        "login", "sign in", "cookies"
    )):
        return (
            "This media requires authentication. "
            "Use only authorized access."
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
"retries": 10,
"fragment_retries": 10,
"extractor_retries": 3,
"socket_timeout": 30,
    }

    if FFMPEG_PATH:
        ffmpeg_path = Path(FFMPEG_PATH)
        options["ffmpeg_location"] = str(
            ffmpeg_path.parent
            if ffmpeg_path.is_file()
            else ffmpeg_path
        )

    cookies_path = os.getenv(
        "COOKIES_FILE",
        str(BASE_DIR / "cookies.txt")
    )

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


def get_gallery_image_urls(url):
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gallery_dl",
                "--get-urls",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

    except (subprocess.TimeoutExpired, OSError):
        return []

    image_urls = []

    for line in result.stdout.splitlines():
        media_url = line.strip()

        if not media_url.startswith(("https://", "http://")):
            continue

        extension = Path(urlparse(media_url).path).suffix.lower()

        if extension in IMAGE_EXTENSIONS and media_url not in image_urls:
            image_urls.append(media_url)

    return image_urls

def get_media_info(url):
    return extract_info_with_retry(url, download=False)


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

    temp_dir = Path(tempfile.mkdtemp(
        prefix="SaveVido_",
        dir=DOWNLOAD_ROOT
    ))

    job = {
        "id": job_id,
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

    return job_id


def get_job(job_id):
    with DOWNLOAD_JOBS_LOCK:
        return DOWNLOAD_JOBS.get(job_id)


def update_job(job_id, **values):
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)

        if job:
            job.update(values)


def cleanup_job_files(job):
    if job and job.get("temp_dir"):
        shutil.rmtree(
            job["temp_dir"],
            ignore_errors=True
        )


def progress_hook(job_id):
    def hook(data):
        job = get_job(job_id)

        if not job:
            raise YtDlpStopSignal(
                "Download job no longer exists."
            )

        if (
            job.get("cancel_requested")
            or job.get("pause_requested")
        ):
            raise YtDlpStopSignal(
                "Download stopped by user."
            )

        if data.get("status") == "downloading":
            downloaded = int(
                data.get("downloaded_bytes") or 0
            )

            total = int(
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or 0
            )

            percent = (
                downloaded / total * 100
                if total else 0
            )

            update_job(
                job_id,
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
    expected_ext = (
        ".mp3" if mode == "audio" else ".mp4"
    )

    candidates = [
        path
        for path in Path(temp_dir).glob("*")
        if path.is_file()
        and path.suffix.lower() == expected_ext
        and not path.name.endswith(".part")
    ]

    if not candidates:
        raise RuntimeError(
            f"No completed {expected_ext[1:].upper()} "
            "file was produced. The source may not "
            "provide this format."
        )

    final_path = max(
        candidates,
        key=lambda path: path.stat().st_size
    )

    if final_path.stat().st_size < MIN_VALID_FILE_BYTES:
        raise RuntimeError(
            "The downloaded file is empty or incomplete."
        )

    with final_path.open("rb") as handle:
        header = handle.read(32).lstrip().lower()

    if (
        header.startswith(b"<!doctype")
        or header.startswith(b"<html")
    ):
        raise RuntimeError(
            "The source returned an HTML error page."
        )

    return final_path, final_path.stat().st_size


def run_download_job(job_id):
    job = get_job(job_id)
    if not job:
        return

    temp_dir = Path(job["temp_dir"])
    url = job["url"]
    mode = job["mode"]
    quality = job["quality"]

    try:
        update_job(job_id, status="preparing", error=None)

        info = get_media_info(url)
        title = info.get("title") or "video"
        update_job(job_id, title=title)

        options = base_ydl_options()
        options.update({
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [progress_hook(job_id)],
        })

        if mode == "audio":
            if not FFMPEG_AVAILABLE:
                raise RuntimeError(
                    "MP3 conversion requires FFmpeg and ffprobe."
                )

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
                "Quality=%s, selected height=%s",
                quality, source_height
            )

            options["format"] = selected_format

            if FFMPEG_AVAILABLE:
                options["merge_output_format"] = "mp4"

            file_type = "MP4"

        update_job(job_id, status="downloading")

        with yt_dlp.YoutubeDL(options) as ydl:
            downloaded_info = ydl.extract_info(
                url, download=True
            )

        final_path, final_size = find_output_file(
            temp_dir, mode
        )

        title = downloaded_info.get("title") or title
        platform = platform_for(url)

        with get_db() as connection:
            connection.execute(
                """
                INSERT INTO downloads
                (title, platform, quality, file_type,
                 source_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    title, platform, quality, file_type,
                    url, now_iso()
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
        )

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
                )
            return

        app.logger.exception("Download job failed")

        if is_network_error(error):
            update_job(
                job_id,
                status="network_error",
                error=(
                    "Network error. Check your connection "
                    "and try resuming."
                ),
            )
        else:
            update_job(
                job_id,
                status="error",
                error=humanize_error(error),
            )

        options = base_ydl_options()
        options.update({
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
            "progress_hooks": [progress_hook(job_id)],
        })

        if mode == "audio":
            if not FFMPEG_AVAILABLE:
                raise RuntimeError(
                    "MP3 conversion requires FFmpeg and ffprobe."
                )

            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            file_type = "MP3"

        else:
            requested_height = QUALITY_HEIGHTS[quality]
            selected_format, source_height = choose_video_format(
                info, requested_height
            )

            app.logger.info(
                "Quality=%s, selected height=%s",
                quality, source_height
            )

            options["format"] = selected_format

            if FFMPEG_AVAILABLE:
                options["merge_output_format"] = "mp4"

            file_type = "MP4"

        update_job(job_id, status="downloading")

        with yt_dlp.YoutubeDL(options) as ydl:
            downloaded_info = ydl.extract_info(
                url, download=True
            )

        final_path, final_size = find_output_file(
            temp_dir, mode
        )

        title = downloaded_info.get("title") or title
        platform = platform_for(url)

        with get_db() as connection:
            connection.execute(
                """
                INSERT INTO downloads
                (title, platform, quality, file_type,
                 source_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    title, platform, quality, file_type,
                    url, now_iso()
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
        )

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
                )
            return

        app.logger.exception("Download job failed")

        if is_network_error(error):
            update_job(
                job_id,
                status="network_error",
                error=(
                    "Network error. Check your connection "
                    "and try resuming."
                ),
            )
        else:
            update_job(
                job_id,
                status="error",
                error=humanize_error(error),
            )


@app.route("/")
def index():
    with get_db() as connection:
        connection.execute(
            "INSERT INTO visits(created_at) VALUES (?)",
            (now_iso(),),
        )
    return render_template("index.html")


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
        image_urls = get_gallery_image_urls(url)

        if not image_urls:
            return jsonify({
                "ok": False,
                "error": "No supported images found in this post."
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

        image_urls = get_gallery_image_urls(url)
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
                    raise ValueError("TikTok returned a file that is not an image.")

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
            download_name="tiktok-photo-album.zip",
        )

    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except requests.RequestException as error:
        app.logger.warning("TikTok image download request failed: %s", error)
        return jsonify({
            "ok": False,
            "error": "An image could not be downloaded from TikTok. Please fetch the album again and retry."
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

    if job["status"] != "downloading":
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

    if (
        not path.is_file()
        or not path.resolve().is_relative_to(
            Path(job["temp_dir"]).resolve()
        )
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
import json
import os
import re
import subprocess

import requests
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError

from core.logging_config import logger

from core.models import get_whisper

_YOUTUBE_FORMAT_HELP = (
    "YouTube did not expose any real video formats (often: 'Only images are available'). "
    "Typical causes: (1) bot/challenge not solved — install Deno and upgrade yt-dlp: "
    "https://github.com/yt-dlp/yt-dlp/wiki/EJS ; (2) after cookie-based attempts fail, "
    "this pipeline retries without cookies using the android client (works for many public videos); "
    "(3) download the MP4 in your browser and run: run_pipeline.py /path/to/video.mp4"
)


def get_video_duration_seconds(video_path):
    """Duration in seconds via ffprobe (float)."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def _youtube_id_from_url(url):
    m = re.search(
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/live/)([a-zA-Z0-9_-]{11})",
        url,
    )
    return m.group(1) if m else None


def get_heatmap(video_id):
    """Fetch YouTube heatmap data by scraping the video page."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Find ytInitialPlayerResponse
        match = re.search(r'ytInitialPlayerResponse\s*=\s*({.+?});', response.text)
        if match:
            data = json.loads(match.group(1))
            heat_map = data.get('videoDetails', {}).get('heatMap')
            if heat_map:
                # heat_map is list of {'time': seconds, 'heat': intensity 0-1}
                return heat_map
    except Exception as e:
        logger.warning("Failed to get heatmap: %s", e, exc_info=True)
    return None


def _is_local_video_path(url):
    if url.startswith("file://"):
        path = url[7:]
        if path.startswith("/"):
            path = "/" + path.lstrip("/")
        return os.path.isfile(path), path
    if os.path.isfile(url):
        return True, url
    return False, None


def _find_cached_download(video_id, download_dir="data/downloads"):
    """Look for an already-downloaded file for this YouTube video id."""
    if not video_id:
        return None
    for ext in ("mp4", "mkv", "webm", "mov", "avi"):
        p = os.path.join(download_dir, f"{video_id}.{ext}")
        if os.path.isfile(p):
            return p
    # Older runs used %(title)s — any filename containing the 11-char id still matches.
    if os.path.isdir(download_dir):
        for name in os.listdir(download_dir):
            if video_id in name and name.lower().endswith(
                (".mp4", ".mkv", ".webm", ".mov", ".avi")
            ):
                return os.path.join(download_dir, name)
    return None


def _yt_dlp_cookie_opts(cookies_file=None, cookies_from_browser=None):
    """
    YouTube often returns 429 or 'Sign in to confirm you are not a bot' for anonymous
    requests. Pass cookies from a Netscape cookies.txt file or from your browser profile.
    Env: YT_DLP_COOKIES (path), YT_DLP_COOKIES_FROM_BROWSER (e.g. firefox or chrome:Default).
    """
    path = cookies_file or os.environ.get("YT_DLP_COOKIES", "").strip()
    browser = (cookies_from_browser or os.environ.get("YT_DLP_COOKIES_FROM_BROWSER", "")).strip()
    opts = {}
    if path and os.path.isfile(path):
        opts["cookiefile"] = path
    elif browser:
        b = browser.strip()
        if b.lower() == "zen":
            raise ValueError(
                "yt-dlp does not support browser name 'zen'. Zen is Firefox-based: use "
                "firefox:/absolute/path/to/your/Zen/profile (folder that contains "
                "cookies.sqlite). In Zen open about:profiles → Open Folder, copy that path. "
                "Or export cookies to a Netscape cookies.txt and pass --cookies PATH."
            )
        name, sep, profile = b.partition(":")
        name = name.strip()
        if sep:
            p = profile.strip()
            opts["cookiesfrombrowser"] = (name,) if not p else (name, p)
        else:
            opts["cookiesfrombrowser"] = (name,)
    return opts


def _without_cookies(opts):
    return {k: v for k, v in opts.items() if k not in ("cookiefile", "cookiesfrombrowser")}


def _download_sequences():
    """
    With cookies, yt-dlp skips android/ios clients; the web client often needs JS (EJS/Deno)
    for challenges, or YouTube only returns 'image' formats.

    Phase 1: cookies + merge / best / web+tv_embedded.
    Phase 2: NO cookies + android/ios (gets real video for many public URLs).
    """
    with_cookie = [
        {"format": "bv*+ba/bv+ba/b", "merge_output_format": "mp4"},
        {"format": "bestvideo*+bestaudio/best", "merge_output_format": "mp4"},
        {"format": "best"},
        {
            "format": "best",
            "extractor_args": {"youtube": {"player_client": ["web", "tv_embedded"]}},
        },
    ]
    no_cookie = [
        {
            "format": "bv*+ba/bv+ba/b",
            "merge_output_format": "mp4",
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        },
        {"format": "best", "extractor_args": {"youtube": {"player_client": ["android"]}}},
        {
            "format": "best",
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        },
        {"format": "best", "extractor_args": {"youtube": {"player_client": ["ios"]}}},
        {"format": "best"},
    ]
    return with_cookie, no_cookie


def baixar_video(url, cookies_file=None, cookies_from_browser=None, use_heatmap=True):
    logger.info("Starting video download: url=%s", url)
    os.makedirs("data/downloads", exist_ok=True)

    ok, local = _is_local_video_path(url)
    if ok:
        logger.info("Using local video path: %s", local)
        return {"info": {"id": os.path.splitext(os.path.basename(local))[0]}, "video_path": local, "cached": True, "heatmap": None}

    cookie_opts = _yt_dlp_cookie_opts(cookies_file, cookies_from_browser)

    base_opts = {
        "outtmpl": "data/downloads/%(id)s.%(ext)s",
        "retries": 5,
        "fragment_retries": 5,
        "ignoreerrors": False,
        **cookie_opts,
    }

    # Probe metadata without downloading (stable id for cache + filename).
    probe_opts = {**base_opts, "quiet": True, "no_warnings": True}
    info = {}
    try:
        with YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        pass

    video_id = (info or {}).get("id") or _youtube_id_from_url(url)
    cached = _find_cached_download(video_id)
    if cached:
        return {"info": info, "video_path": cached, "cached": True, "heatmap": None}

    last_err = None
    with_cookie, no_cookie = _download_sequences()
    phases = [(base_opts, with_cookie)]
    # Without cookies, android client can return real video while cookie+web returns only images.
    phases.append((_without_cookies(base_opts), no_cookie))

    for phase_opts, attempts in phases:
        for fmt_opts in attempts:
            opts = {**phase_opts, **fmt_opts}
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    video_path = ydl.prepare_filename(info)
                if not os.path.exists(video_path):
                    base, _ = os.path.splitext(video_path)
                    for ext in ("mp4", "mkv", "webm"):
                        alt = f"{base}.{ext}"
                        if os.path.exists(alt):
                            video_path = alt
                            break
                heatmap = get_heatmap(video_id) if use_heatmap else None
                logger.info("Downloaded video using yt-dlp, path=%s", video_path)
                return {"info": info, "video_path": video_path, "cached": False, "heatmap": heatmap}
            except (DownloadError, ExtractorError) as e:
                last_err = e
                continue

    if last_err:
        raise DownloadError(f"{_YOUTUBE_FORMAT_HELP}\n\nLast error: {last_err}") from last_err
    raise DownloadError(_YOUTUBE_FORMAT_HELP)


def extrair_audio(video_path):
    logger.info("Extracting audio from video %s", video_path)
    os.makedirs("data/audio", exist_ok=True)

    audio = "data/audio/audio.wav"

    cmd = [
        "ffmpeg","-y",
        "-i",video_path,
        "-vn",
        "-acodec","pcm_s16le",
        "-ar","16000",
        "-ac","1",
        audio
    ]

    subprocess.run(cmd, check=True)
    logger.info("Audio extracted to %s", audio)
    return audio


def transcrever(audio_path):
    logger.info("Transcribing audio %s", audio_path)
    result = get_whisper().transcribe(
        audio_path,
        task="transcribe",
        word_timestamps=True,
    )
    segments = result.get("segments", [])
    logger.info("Transcription complete: %d segments", len(segments))
    return segments

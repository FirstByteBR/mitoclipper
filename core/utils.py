import json
import os
import re
from typing import Optional, Dict, Any

def save_json(path: str, data: Any):
    """Saves a dictionary to a JSON file, ensuring the directory exists."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: str) -> Optional[Dict]:
    """Loads a JSON file, returning None if not found or invalid."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None
    except Exception:
        return None


def ffmpeg_escape_path(path: str) -> str:
    """Escapes a file path for use in FFmpeg commands, especially for ASS filters."""
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace("'", r"\'")
    p = p.replace(":", r"\:")
    return p


def sanitize_ass_text(text: str) -> str:
    """Sanitizes text for ASS subtitles to prevent formatting issues."""
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", " ")
        .strip()
    )

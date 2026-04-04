import json
import os
import re

def save_json(path: str, data: dict):
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
        # Log this error if a logger is available
        return None
    except Exception:
        return None


def ffmpeg_escape_path(path: str) -> str:
    """Escapes a file path for use in FFmpeg commands, especially for ASS filters."""
    # FFmpeg ASS filter expects Windows paths with backslashes escaped and colons escaped
    # or Unix paths without special escaping for simple cases.
    # Using forward slashes and escaping single quotes and backslashes is generally safer.
    p = os.path.abspath(path).replace("", "/") # Convert backslashes to forward slashes
    p = p.replace("'", r"'") # Escape single quotes
    p = p.replace(":", r"\:") # Escape colons (important for Windows drive letters)
    return p


def sanitize_ass_text(text: str) -> str:
    """Sanitizes text for ASS subtitles to prevent formatting issues."""
    # Escape ASS-specific characters: { } \ and ensure no newlines break formatting
    return (
        text.replace("", r"")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("
", " ") # Replace newlines with spaces
        .strip()
    )

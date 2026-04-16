import os
import json
import argparse
import glob
import subprocess
import shutil
from core.config import cfg
from core.logging_config import logger

def upload_single_clip(clip_path, meta_path, privacy="unlisted"):
    if not os.path.exists(clip_path):
        logger.error(f"Clip not found: {clip_path}")
        return False

    title = "MitoClipper Highlight"
    description = "Generated with MitoClipper."

    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
                title = meta.get("title") or title
                description = meta.get("description") or description
        except Exception as e:
            logger.warning(f"Could not read metadata from {meta_path}: {e}")

    logger.info(f"Uploading {clip_path} with title: {title}")

    if shutil.which("youtube-upload") is None:
        logger.error("youtube-upload CLI not found. Install it with: pip install youtube-upload")
        return False

    cmd = [
        "youtube-upload",
        "--title", title,
        "--description", description,
        "--privacy", privacy,
        clip_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"Successfully uploaded: {clip_path}")
            # Optional: Extract URL if present in stdout
            return True
        else:
            logger.error(f"Upload failed for {clip_path}: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error executing youtube-upload: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Standalone YouTube Uploader for MitoClipper clips.")
    parser.add_argument("--dir", default=cfg.clips_dir, help="Directory containing clips and .json metadata.")
    parser.add_argument("--privacy", default="unlisted", choices=["public", "private", "unlisted"], help="YouTube privacy setting.")
    parser.add_argument("--file", help="Specific .mp4 file to upload (will look for matching .json).")
    
    args = parser.parse_args()

    if args.file:
        clip_path = args.file
        meta_path = clip_path.rsplit(".", 1)[0] + ".json"
        upload_single_clip(clip_path, meta_path, args.privacy)
    else:
        # Scan directory
        clips = glob.glob(os.path.join(args.dir, "*.mp4"))
        if not clips:
            print(f"No clips found in {args.dir}")
            return

        print(f"Found {len(clips)} clips. Starting upload...")
        for clip in sorted(clips):
            meta_path = clip.rsplit(".", 1)[0] + ".json"
            upload_single_clip(clip, meta_path, args.privacy)

if __name__ == "__main__":
    main()

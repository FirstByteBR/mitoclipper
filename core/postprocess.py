import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np

from core.logging_config import logger
from core.config import cfg
from core.subtitle_styles import get_style
from core.utils import ffmpeg_escape_path, sanitize_ass_text

class FaceDetector:
    def __init__(self, model_path="models/face_detection_short_range.tflite"):
        self.net = None
        if os.path.exists(model_path):
            try:
                self.net = cv2.dnn.readNetFromTFLite(model_path)
                logger.info("Face detector loaded from %s", model_path)
            except Exception as e:
                logger.warning("Failed to load face detector from %s: %s", model_path, e)

    def detect_face_center(self, frame):
        """Returns the X-coordinate (normalized 0-1) of the most prominent face."""
        h, w = frame.shape[:2]
        
        # Fallback to Haar Cascades (standard OpenCV, very reliable for this use case)
        # TFLite parsing for BlazeFace in cv2.dnn can be extremely complex without MediaPipe
        # So we use Haar as a reliable baseline for "Back-end Enhancements"
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Use a slightly smaller scale for speed
            small_gray = cv2.resize(gray, (0,0), fx=0.5, fy=0.5)
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            faces = face_cascade.detectMultiScale(small_gray, 1.2, 3)
            
            if len(faces) > 0:
                # Find the largest face (closest to camera)
                largest_face = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest_face
                # Adjust for 0.5x scaling
                center_x = (fx + fw/2) * 2
                return float(center_x / w)
        except Exception as e:
            logger.debug("Haar detection failed: %s", e)
            
        return 0.5

_face_detector = None

def proximo_id():
    pasta = cfg.clips_dir
    os.makedirs(pasta, exist_ok=True)
    ids = []
    for f in os.listdir(pasta):
        prefix = f.split("_")[0]
        num = "".join(filter(str.isdigit, prefix))
        if num:
            ids.append(int(num))
    return max(ids) + 1 if ids else 1


def _ass_time(sec):
    td = timedelta(seconds=max(0.0, float(sec)))
    h = int(td.total_seconds() // 3600)
    m = int((td.total_seconds() % 3600) // 60)
    s = int(td.total_seconds() % 60)
    cs = int((td.total_seconds() % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _word_key(word):
    return re.sub(r"^[^\w]+|[^\w]+$", "", word.lower())


def _is_hook_word(word):
    return _word_key(word) in cfg.hook_keywords


def upload_clips_to_youtube(clip_paths, metadata_entries, privacy="unlisted", dry_run=False):
    if not clip_paths:
        return []

    if shutil.which("youtube-upload") is None:
        raise RuntimeError(
            "youtube-upload CLI not found. Install it (pip install youtube-upload) "
            "and configure OAuth credentials before using auto-upload."
        )

    uploads = []
    for i, clip_path in enumerate(clip_paths):
        if not os.path.exists(clip_path):
            raise FileNotFoundError(f"Clip not found: {clip_path}")

        title = "MitoClipper Highlight"
        description = "Generated with MitoClipper."
        if i < len(metadata_entries):
            meta = metadata_entries[i]
            title = meta.get("title") or title
            description = meta.get("description") or description

        if dry_run:
            uploads.append({"clip": clip_path, "title": title, "description": description, "status": "dry_run"})
            continue

        cmd = [
            "youtube-upload",
            "--title",
            title,
            "--description",
            description,
            "--privacy",
            privacy,
            clip_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        status = "success" if result.returncode == 0 else "failed"
        published_url = None
        if result.stdout:
            m = re.search(r"https?://[^\s]+", result.stdout)
            if m:
                published_url = m.group(0)

        uploads.append(
            {
                "clip": clip_path,
                "title": title,
                "description": description,
                "status": status,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "published_url": published_url,
            }
        )

        if result.returncode != 0:
            raise RuntimeError(f"Upload failed for {clip_path}: {result.stderr.strip()}")

    return uploads


def _flatten_words(segmentos):
    words = []
    for seg in segmentos:
        for w in seg.get("words") or []:
            words.append(
                {
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "word": w.get("word", ""),
                }
            )
    words.sort(key=lambda x: x["start"])
    merged = []
    for w in words:
        if not merged:
            merged.append(dict(w))
            continue
        p = merged[-1]
        gap = w["start"] - p["end"]
        if gap < 0.02 and (w["end"] - w["start"]) < 0.12:
            p["word"] = (p["word"] + w["word"]).strip()
            p["end"] = w["end"]
        else:
            merged.append(dict(w))
    return merged


def _word_chunks(words, max_words=3):
    for i in range(0, len(words), max_words):
        yield words[i : i + max_words]


def face_horizontal_bias(video_path, t_start, duration, samples=6):
    """
    Analyzes several frames from the video segment to find the dominant face
    and returns its average horizontal position (0-1).
    """
    global _face_detector
    if _face_detector is None:
        _face_detector = FaceDetector()
        
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.5
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    start_frame = int(t_start * fps)
    end_frame = int((t_start + duration) * fps)
    
    # Sample frames across the duration
    frame_indices = np.linspace(start_frame, min(end_frame, total_frames - 1), samples, dtype=int)
    
    positions = []
    for idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        pos = _face_detector.detect_face_center(frame)
        positions.append(pos)
        
    cap.release()
    
    if not positions:
        return 0.5
        
    # Return average but weight more towards the center if detections are scattered
    return float(np.mean(positions))


def _build_vf(subtitle_path, vertical=True, bias=0.5):
    ass = ffmpeg_escape_path(subtitle_path)
    b = min(1.0, max(0.0, float(bias)))
    if vertical:
        return (
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920:(iw-1080)*{b:.6f}:0,"
            f"format=yuv420p,"
            f"ass={ass}"
        )
    return f"ass={ass}"


def gerar_legenda(segmentos, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    words = _flatten_words(segmentos)
    
    style_def = get_style(cfg.subtitle_style)
    # Override font if specified
    if hasattr(cfg, 'subtitle_font') and cfg.subtitle_font:
        style_def.fontname = cfg.subtitle_font
        
    style_name = style_def.name
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\n")
        f.write("Title: MitoClipper\n")
        f.write("ScriptType: v4.00+\n")
        f.write("PlayResX: 1080\n")
        f.write("PlayResY: 1920\n")
        f.write("WrapStyle: 0\n\n")

        f.write("[V4+ Styles]\n")
        f.write(
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
            "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
        )
        f.write(style_def.generate_ass_style_header())
        f.write("\n")

        f.write("[Events]\n")
        f.write(
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
        )

        for chunk in _word_chunks(words, max_words=3):
            line_start = chunk[0]["start"]
            line_end = chunk[-1]["end"]
            parts = []
            for w in chunk:
                raw = w["word"]
                dur = max(0.1, float(w["end"]) - float(w["start"]))
                # Karaoke timer in centiseconds
                cs = max(8, min(120, int(dur * 100)))
                display = sanitize_ass_text(raw).upper()
                if not display:
                    continue
                    
                is_hook = _is_hook_word(raw)
                target_color = style_def.hook_color if is_hook else style_def.active_color
                scx = int(style_def.hook_scale * 100) if is_hook else int(style_def.active_scale * 100)
                scy = scx

                c_tag = target_color.replace("&H00", "&H") if target_color.startswith("&H00") else target_color
                
                # Active word animation using \t
                # Starts with default font settings (karaoke keeps highlight synced), 
                # but we'll manually apply color and scale when word is hit
                parts.append(
                    f"{{\\k{cs}}}{{\\c{c_tag}&\\fscx{scx}\\fscy{scy}\\t(0,50,\\fscx100\\fscy100)}}"
                    f"{display}{{\\r}}"
                )

            if not parts:
                continue
            text = " ".join(parts)
            f.write(
                f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},{style_name},,0,0,0,,{text}\n"
            )

    return output_path


def _segmentos_no_intervalo(segmentos, start, end):
    selected = []
    for seg in segmentos:
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", 0))
        if seg_end <= start or seg_start >= end:
            continue
        seg_copy = {
            "start": max(0.0, seg_start - start),
            "end": max(0.0, seg_end - start),
            "text": seg.get("text", "")
        }
        if "words" in seg:
            words = []
            for w in seg["words"]:
                w_start = float(w.get("start", 0))
                w_end = float(w.get("end", 0))
                if w_end <= start or w_start >= end:
                    continue
                words.append(
                    {
                        "start": max(0.0, w_start - start),
                        "end": max(0.0, w_end - start),
                        "word": w.get("word", ""),
                    }
                )
            seg_copy["words"] = words
        selected.append(seg_copy)
    return selected


def _process_single_clip(args):
    idx, clip_info, video_path, segmentos, vertical, face_tracking, base_id, hoje, clip_meta = args
    start = float(clip_info["start"])
    end = float(clip_info["end"])
    dur = int(max(1, round(end - start)))
    letra = chr(ord("A") + idx)
    nome = f"{base_id}{letra}_{hoje:%d_%m}_{dur}.mp4"
    saida = os.path.join(cfg.clips_dir, nome)
    meta_saida = os.path.join(cfg.clips_dir, f"{base_id}{letra}_{hoje:%d_%m}_{dur}.json")

    segs_clip = _segmentos_no_intervalo(segmentos, start, end)
    sub_path = os.path.join(cfg.subtitles_dir, f"{base_id}{letra}_{hoje:%d_%m}_{dur}.ass")
    gerar_legenda(segs_clip, sub_path)

    # Save metadata if provided
    if clip_meta:
        from core.utils import save_json
        save_json(meta_saida, clip_meta)

    bias = 0.5

    if vertical and face_tracking:
        bias = face_horizontal_bias(video_path, start, end - start)

    vf = _build_vf(sub_path, vertical=vertical, bias=bias)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", video_path,
        "-vf", vf,
        "-c:v", cfg.ffmpeg_video_encoder,
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        saida,
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return {
            "video_path": saida,
            "subtitle_path": sub_path,
            "start": start,
            "end": end,
            "vertical": vertical,
            "face_bias": bias if vertical else None,
            "success": True
        }
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg error for clip %d: %s", idx, e.stderr.decode())
        return {"success": False, "error": str(e), "idx": idx}


def gerar_clips(video, cortes, segmentos, vertical=True, face_tracking=True, metadata=None):
    logger.info(
        "Generating clips (parallel): video=%s, cortes=%d, vertical=%s, face_tracking=%s",
        video,
        len(cortes) if cortes else 0,
        vertical,
        face_tracking,
    )
    os.makedirs(cfg.clips_dir, exist_ok=True)
    os.makedirs(cfg.subtitles_dir, exist_ok=True)

    base_id = proximo_id()
    hoje = datetime.now()
    
    worker_args = []
    for i, c in enumerate(cortes):
        clip_meta = None
        if metadata and i < len(metadata):
            clip_meta = metadata[i]
        worker_args.append((i, c, video, segmentos, vertical, face_tracking, base_id, hoje, clip_meta))

    outputs = []
    # Use max 4 workers to avoid overloading CPU/GPU
    with ProcessPoolExecutor(max_workers=min(len(cortes), 4)) as executor:
        results = list(executor.map(_process_single_clip, worker_args))
        
    for res in results:
        if res.get("success"):
            outputs.append(res)
        else:
            logger.error("Failed to generate clip %s", res.get("idx"))

    logger.info("Generated %d clip outputs", len(outputs))
    return outputs

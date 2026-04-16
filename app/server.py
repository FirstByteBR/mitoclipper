"""
MitoClipper Web Server
Flask application serving the web UI and REST API for the clip pipeline.
"""
import os
import sys
import json
import time
import threading
import glob
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, abort

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.config import cfg
from core.metrics import pipeline_metrics, get_metrics
from core.logging_config import logger, LOG_FILE
from core.subtitle_styles import STYLES, get_style
from core.pipeline_slate import PipelineState

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# ─── In-memory pipeline run state ────────────────────────────────────────────
_pipeline_lock = threading.Lock()
_pipeline_thread = None
_pipeline_progress = {
    "status": "idle",
    "stage": None,
    "started_at": None,
    "error": None,
    "result": None,
}


def _reset_progress():
    _pipeline_progress.update({
        "status": "idle",
        "stage": None,
        "started_at": None,
        "error": None,
        "result": None,
    })


def _run_pipeline_thread(url, options):
    """Runs the full pipeline in a background thread."""
    from run_pipeline import run as run_pipeline

    _pipeline_progress["status"] = "running"
    _pipeline_progress["started_at"] = time.time()
    _pipeline_progress["error"] = None
    _pipeline_progress["result"] = None

    try:
        result = run_pipeline(url, **options)
        _pipeline_progress["status"] = "done"
        _pipeline_progress["result"] = result
    except Exception as e:
        _pipeline_progress["status"] = "failed"
        _pipeline_progress["error"] = str(e)
        logger.error("Pipeline thread failed: %s", e, exc_info=True)


# ─── Template Routes ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── API: Pipeline ───────────────────────────────────────────────────────────

@app.route("/api/pipeline/run", methods=["POST"])
def api_run_pipeline():
    global _pipeline_thread

    if _pipeline_progress["status"] == "running":
        return jsonify({"error": "Pipeline is already running"}), 409

    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    options = {}
    for key in ["top_k", "max_duration", "min_clip_duration", "target_clip_duration",
                 "subtitle_style", "subtitle_font", "youtube_privacy"]:
        if key in data and data[key] is not None:
            options[key] = data[key]

    # Boolean options
    if data.get("no_vertical"):
        options["no_vertical"] = True
    if data.get("no_face"):
        options["no_face"] = True
    if data.get("no_heatmap"):
        options["no_heatmap"] = True
    if data.get("auto_upload"):
        options["auto_upload"] = True

    _reset_progress()
    _pipeline_thread = threading.Thread(
        target=_run_pipeline_thread, args=(url, options), daemon=True
    )
    _pipeline_thread.start()

    return jsonify({"status": "started"})


@app.route("/api/pipeline/status")
def api_pipeline_status():
    elapsed = None
    if _pipeline_progress["started_at"]:
        if _pipeline_progress["status"] == "running":
            elapsed = time.time() - _pipeline_progress["started_at"]
        elif _pipeline_progress["result"]:
            metrics = _pipeline_progress["result"].get("metrics", {})
            lr = metrics.get("last_run")
            if lr:
                elapsed = lr.get("duration_sec")

    # Current stage from PipelineState
    stage = PipelineState.current_stage
    steps = dict(PipelineState.steps)

    return jsonify({
        "status": _pipeline_progress["status"],
        "stage": stage,
        "steps": steps,
        "elapsed_sec": round(elapsed, 1) if elapsed else None,
        "error": _pipeline_progress["error"],
    })


# ─── API: Clips Management ──────────────────────────────────────────────────

def _scan_clips():
    """Scans the clips directory and returns structured clip info."""
    clips_dir = cfg.clips_dir
    if not os.path.isdir(clips_dir):
        return []

    clips = []
    for fname in sorted(os.listdir(clips_dir)):
        fpath = os.path.join(clips_dir, fname)
        if not os.path.isfile(fpath):
            continue

        if fname.lower().endswith((".mp4", ".mkv", ".webm", ".mov")):
            basename = os.path.splitext(fname)[0]
            meta_path = os.path.join(clips_dir, f"{basename}.json")
            meta = {}
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as mf:
                        meta = json.load(mf)
                except Exception:
                    pass

            stat = os.stat(fpath)
            clips.append({
                "filename": fname,
                "basename": basename,
                "path": fpath,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "title": meta.get("title", ""),
                "description": meta.get("description", ""),
                "meta": meta,
            })

    return clips


@app.route("/api/clips")
def api_list_clips():
    return jsonify(_scan_clips())


@app.route("/api/clips/<filename>/download")
def api_download_clip(filename):
    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        abort(404)
    return send_file(fpath, as_attachment=True)


@app.route("/api/clips/<filename>/stream")
def api_stream_clip(filename):
    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        abort(404)
    return send_file(fpath, mimetype="video/mp4")


@app.route("/api/clips/<filename>/rename", methods=["PUT"])
def api_rename_clip(filename):
    data = request.get_json(force=True)
    new_name = data.get("new_name", "").strip()
    if not new_name:
        return jsonify({"error": "new_name is required"}), 400

    old_path = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(old_path):
        abort(404)

    # Preserve extension
    _, ext = os.path.splitext(filename)
    if not new_name.endswith(ext):
        new_name += ext

    new_path = os.path.join(cfg.clips_dir, new_name)
    if os.path.exists(new_path):
        return jsonify({"error": "A clip with that name already exists"}), 409

    os.rename(old_path, new_path)

    # Also rename associated metadata JSON if it exists
    old_base = os.path.splitext(filename)[0]
    new_base = os.path.splitext(new_name)[0]
    old_meta = os.path.join(cfg.clips_dir, f"{old_base}.json")
    if os.path.isfile(old_meta):
        os.rename(old_meta, os.path.join(cfg.clips_dir, f"{new_base}.json"))

    return jsonify({"status": "renamed", "new_name": new_name})


@app.route("/api/clips/<filename>", methods=["DELETE"])
def api_delete_clip(filename):
    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        abort(404)
    os.remove(fpath)

    # Also remove associated metadata JSON
    base = os.path.splitext(filename)[0]
    meta_path = os.path.join(cfg.clips_dir, f"{base}.json")
    if os.path.isfile(meta_path):
        os.remove(meta_path)

    return jsonify({"status": "deleted"})


@app.route("/api/clips/<filename>/metadata", methods=["PUT"])
def api_update_clip_metadata(filename):
    """Update a clip's title and description."""
    data = request.get_json(force=True)
    base = os.path.splitext(filename)[0]
    meta_path = os.path.join(cfg.clips_dir, f"{base}.json")

    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    if "title" in data:
        meta["title"] = data["title"]
    if "description" in data:
        meta["description"] = data["description"]

    os.makedirs(cfg.clips_dir, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return jsonify({"status": "updated", "meta": meta})


@app.route("/api/clips/<filename>/upload", methods=["POST"])
def api_upload_clip_to_youtube(filename):
    """Upload a single clip to YouTube."""
    from core.postprocess import upload_clips_to_youtube

    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        abort(404)

    data = request.get_json(force=True) if request.data else {}
    privacy = data.get("privacy", "unlisted")

    base = os.path.splitext(filename)[0]
    meta_path = os.path.join(cfg.clips_dir, f"{base}.json")
    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except Exception:
            pass

    try:
        result = upload_clips_to_youtube(
            [fpath],
            [meta],
            privacy=privacy,
        )
        return jsonify({"status": "uploaded", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Metrics & Logs ────────────────────────────────────────────────────

@app.route("/api/metrics")
def api_metrics():
    summary = get_metrics()

    # Also load saved metrics from disk if available
    saved = pipeline_metrics.load_metrics(cfg.pipeline_metrics_json)
    if saved and not summary.get("last_run"):
        summary = saved

    return jsonify(summary)


@app.route("/api/logs")
def api_logs():
    """Returns the last N lines of the log file."""
    n = request.args.get("lines", 100, type=int)
    n = min(n, 500)

    log_path = LOG_FILE
    if not os.path.isfile(log_path):
        return jsonify({"lines": [], "total": 0})

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        tail = all_lines[-n:]
        return jsonify({
            "lines": [l.rstrip() for l in tail],
            "total": len(all_lines),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: Config & Styles ───────────────────────────────────────────────────

@app.route("/api/config")
def api_get_config():
    """Returns the current pipeline configuration."""
    config_dict = {}
    for field_name in cfg.__dataclass_fields__:
        val = getattr(cfg, field_name, None)
        if field_name.startswith("_"):
            continue
        # Skip non-serializable
        try:
            json.dumps(val)
            config_dict[field_name] = val
        except (TypeError, ValueError):
            config_dict[field_name] = str(val)
    return jsonify(config_dict)


@app.route("/api/styles")
def api_get_styles():
    """Returns available subtitle styles."""
    styles_info = {}
    for key, style in STYLES.items():
        styles_info[key] = {
            "name": style.name,
            "fontname": style.fontname,
            "fontsize": style.fontsize,
            "primary_color": style.primary_color,
            "hook_color": style.hook_color,
            "active_color": style.active_color,
            "outline": style.outline,
            "shadow": style.shadow,
            "active_scale": style.active_scale,
            "hook_scale": style.hook_scale,
        }
    return jsonify(styles_info)


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="MitoClipper Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=5000, help="Port")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()

    logger.info("Starting MitoClipper Web UI on %s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

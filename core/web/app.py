import os
import sys
import glob
import threading
import json
import re
import mimetypes

# Make sure this package works when running from the script path directly.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
    flash,
    jsonify,
    Response,
)

from core.analysis import parse_generated_metadata, gerar_metadados
from core.metrics import get_metrics
from core.pipeline_slate import PipelineState
from core.postprocess import upload_clips_to_youtube
from run_pipeline import run

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=os.path.join(BASE_DIR, "static"))
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "mitoclipper-demo-secret")

DATA_CLIPS_DIR = "data/clips"
PIPELINE_RESULT_JSON = "data/transcripts/pipeline_result.json"

job_lock = threading.Lock()
job_thread = None


def _read_pipeline_result():
    if not os.path.exists(PIPELINE_RESULT_JSON):
        return None
    try:
        with open(PIPELINE_RESULT_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    result = _read_pipeline_result()
    return render_template(
        "index.html",
        state=PipelineState,
        recent_result=result,
    )


@app.route("/start", methods=["POST"])
def start_pipeline():
    global job_thread

    url = request.form.get("url", "").strip()
    if not url:
        flash("Please enter a video URL or local path.", "warning")
        return redirect(url_for("index"))

    if PipelineState.status == "running":
        flash("A pipeline run is already in progress. Please wait.", "danger")
        return redirect(url_for("status"))

    top_k = int(request.form.get("top_k", 3))
    max_duration = int(request.form.get("max_duration", 60))
    min_clip_duration = float(request.form.get("min_clip_duration", 15.0))
    target_clip_duration = float(request.form.get("target_clip_duration", 35.0))
    vertical = request.form.get("vertical") == "on"
    face_tracking = request.form.get("face_tracking") == "on"
    use_heatmap = request.form.get("use_heatmap") == "on"
    auto_upload = request.form.get("auto_upload") == "on"
    cookies = request.form.get("cookies") or None
    cookies_from_browser = request.form.get("cookies_from_browser") or None

    def worker():
        try:
            run(
                url,
                top_k=top_k,
                max_duration=max_duration,
                min_clip_duration=min_clip_duration,
                target_clip_duration=target_clip_duration,
                vertical=vertical,
                face_tracking=face_tracking,
                use_heatmap=use_heatmap,
                auto_upload=auto_upload,
                cookies_file=cookies,
                cookies_from_browser=cookies_from_browser,
            )
            PipelineState.status = "done"
        except Exception as error:
            PipelineState.status = "failed"
            PipelineState.last_error = str(error)

    PipelineState.reset()
    PipelineState.status = "running"
    PipelineState.current_video = url

    with job_lock:
        job_thread = threading.Thread(target=worker, daemon=True)
        job_thread.start()

    flash("Pipeline started. Check status page for progress.", "success")
    return redirect(url_for("status"))


@app.route("/status")
def status():
    result = _read_pipeline_result()
    return render_template(
        "status.html",
        state=PipelineState,
        result=result,
    )


def _load_generated_clip_metadata():
    path = "data/transcripts/generated_metadata.json"
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # expected shape {raw: ..., parsed:[...]}
        if isinstance(data, dict):
            parsed = data.get("parsed")
            if isinstance(parsed, list):
                return parsed
            if isinstance(data.get("raw"), str):
                return parse_generated_metadata(data.get("raw"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


@app.route("/api/result")
def api_result():
    return (json.dumps({
        "status": PipelineState.status,
        "current_stage": PipelineState.current_stage,
        "current_video": PipelineState.current_video,
        "steps": PipelineState.steps,
        "last_error": PipelineState.last_error,
        "youtube_upload_results": PipelineState.youtube_upload_results,
        "result": _read_pipeline_result(),
        "metrics": get_metrics(),
    }), 200, {"Content-Type": "application/json"})


@app.route("/api/metrics")
def api_metrics():
    return (json.dumps(get_metrics()), 200, {"Content-Type": "application/json"})


@app.route("/api/clips")
def api_clips():
    clip_files = sorted(glob.glob(os.path.join(DATA_CLIPS_DIR, "*.mp4")))
    files = [os.path.basename(p) for p in clip_files]
    metadata = _load_generated_clip_metadata()
    return jsonify({"clips": files, "metadata": metadata})


@app.route("/api/clips/delete", methods=["POST"])
def api_delete_clip():
    payload = request.get_json() or {}
    clip_name = payload.get("clip_name")
    if not clip_name:
        return jsonify({"error": "Missing clip_name"}), 400
    path = os.path.join(DATA_CLIPS_DIR, clip_name)
    if not os.path.exists(path):
        return jsonify({"error": "Clip not found"}), 404
    os.remove(path)
    return jsonify({"message": "Deleted", "clip_name": clip_name})


@app.route("/api/clips/rename", methods=["POST"])
def api_rename_clip():
    payload = request.get_json() or {}
    clip_name = payload.get("clip_name")
    new_name = payload.get("new_name")
    if not clip_name or not new_name:
        return jsonify({"error": "Missing clip_name or new_name"}), 400
    old_path = os.path.join(DATA_CLIPS_DIR, clip_name)
    new_path = os.path.join(DATA_CLIPS_DIR, new_name)
    if not os.path.exists(old_path):
        return jsonify({"error": "Clip not found"}), 404
    if os.path.exists(new_path):
        return jsonify({"error": "Target name exists"}), 409
    os.rename(old_path, new_path)
    return jsonify({"message": "Renamed", "old": clip_name, "new": new_name})


@app.route("/api/clips/generate", methods=["POST"])
def api_generate_clip_metadata():
    payload = request.get_json() or {}
    top_k = int(payload.get("top_k", 3))
    force = payload.get("force", False)

    result = _read_pipeline_result() or {}
    segmentos = []
    cortes = []
    if result.get("viral_segments"):
        cortes = result.get("viral_segments", [])
    transcript_path = "data/transcripts/transcript.json"
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            segmentos = json.load(f)

    if not segmentos or not cortes:
        return jsonify({"error": "No transcript or clip segments found"}), 400

    raw_metadata = gerar_metadados(segmentos, cortes)
    parsed_metadata = parse_generated_metadata(raw_metadata)
    _save_json("data/transcripts/generated_metadata.json", {"raw": raw_metadata, "parsed": parsed_metadata})

    # After this, clips have catchy titles/descriptions
    return jsonify({"metadata": parsed_metadata})


@app.route("/api/clips/youtube_data")
def api_clips_youtube_data():
    clips = sorted(glob.glob(os.path.join(DATA_CLIPS_DIR, "*.mp4")))
    clip_names = [os.path.basename(p) for p in clips]
    metadata = _load_generated_clip_metadata()

    result = []
    for idx, name in enumerate(clip_names):
        entry = {"clip_name": name, "download_url": url_for("clip_file", filename=name, _external=True)}
        if idx < len(metadata) and isinstance(metadata[idx], dict):
            entry["title"] = metadata[idx].get("title")
            entry["description"] = metadata[idx].get("description")
        else:
            entry["title"] = f"MitoClipper Highlight #{idx+1}"
            entry["description"] = "Generated with MitoClipper."
        result.append(entry)

    return jsonify({"youtube_ready": result})


@app.route("/api/clips/youtube_publish", methods=["POST"])
def api_clips_youtube_publish():
    payload = request.get_json() or {}
    privacy = payload.get("privacy", "unlisted")
    dry_run = payload.get("dry_run", False)

    clips = sorted(glob.glob(os.path.join(DATA_CLIPS_DIR, "*.mp4")))
    if not clips:
        return jsonify({"error": "No clips available for upload"}), 400

    generated_path = "data/transcripts/generated_metadata.json"
    metadata_entries = []
    if os.path.exists(generated_path):
        try:
            with open(generated_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                metadata_entries = content.get("parsed") if isinstance(content, dict) else []
        except Exception:
            metadata_entries = []

    if not metadata_entries:
        return jsonify({"error": "No generated metadata available; run /api/clips/generate first"}), 400

    try:
        upload_results = upload_clips_to_youtube(
            [os.path.abspath(p) for p in clips],
            metadata_entries,
            privacy=privacy,
            dry_run=dry_run,
        )
        PipelineState.youtube_upload_results = upload_results
        PipelineState.steps["youtube_upload"] = True
        PipelineState.current_stage = "youtube_upload"
        return jsonify({"upload": upload_results})
    except Exception as exc:
        PipelineState.fail(str(exc))
        return jsonify({"error": str(exc)}), 500


@app.route("/clips")
def browse_clips():
    files = []
    if os.path.exists(DATA_CLIPS_DIR):
        mp4s = sorted(glob.glob(os.path.join(DATA_CLIPS_DIR, "*.mp4")))
        files = [os.path.basename(p) for p in mp4s]

    result = _read_pipeline_result()
    viral_segments = []
    if result:
        viral_segments = result.get("viral_segments") or []

    return render_template(
        "clips.html",
        files=files,
        state=PipelineState,
        result=result,
        viral_segments=viral_segments,
    )


def _streaming_response(file_path):
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("Range", None)
    if not range_header:
        return send_from_directory(DATA_CLIPS_DIR, os.path.basename(file_path), conditional=True)

    match = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not match:
        return send_from_directory(DATA_CLIPS_DIR, os.path.basename(file_path), conditional=True)

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    end = min(end, file_size - 1)

    length = end - start + 1
    with open(file_path, "rb") as f:
        f.seek(start)
        data = f.read(length)

    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    resp = Response(data, status=206, mimetype=content_type)
    resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Content-Length"] = str(length)
    return resp


@app.route("/clips/<path:filename>")
def clip_file(filename):
    file_path = os.path.join(DATA_CLIPS_DIR, filename)
    if not os.path.exists(file_path):
        flash("Clip not found.", "danger")
        return redirect(url_for("browse_clips"))
    return _streaming_response(file_path)


@app.route("/reset")
def reset_state():
    PipelineState.reset()
    flash("Pipeline state reset.", "info")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

import os
import sys
import glob
import threading
import json

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
)

from core.pipeline_slate import PipelineState
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


@app.route("/api/result")
def api_result():
    return (json.dumps({
        "status": PipelineState.status,
        "current_video": PipelineState.current_video,
        "steps": PipelineState.steps,
        "last_error": PipelineState.last_error,
        "result": _read_pipeline_result(),
    }), 200, {"Content-Type": "application/json"})


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


@app.route("/clips/<path:filename>")
def clip_file(filename):
    return send_from_directory(DATA_CLIPS_DIR, filename)


@app.route("/reset")
def reset_state():
    PipelineState.reset()
    flash("Pipeline state reset.", "info")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

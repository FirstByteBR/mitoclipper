import os
import sys
import json
import asyncio
import time
from typing import Optional, List, Dict
from datetime import datetime

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import cfg
from core.metrics import pipeline_metrics, get_metrics
from core.logging_config import logger, LOG_FILE
from core.subtitle_styles import STYLES
from run_pipeline import run as run_pipeline

app = FastAPI(title="MitoClipper Evolution API")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ─── State Management ────────────────────────────────────────────────────────
class PipelineProgress:
    status = "idle"
    stage = None
    started_at = None
    error = None
    result = None

_progress = PipelineProgress()
_active_websockets: List[WebSocket] = []

# ─── Pydantic Models ─────────────────────────────────────────────────────────
class PipelineRunRequest(BaseModel):
    url: str
    top_k: Optional[int] = None
    max_duration: Optional[int] = None
    min_clip_duration: Optional[float] = None
    target_clip_duration: Optional[float] = None
    subtitle_style: Optional[str] = None
    subtitle_font: Optional[str] = None
    no_vertical: bool = False
    no_face: bool = False
    no_heatmap: bool = False
    auto_upload: bool = False
    youtube_privacy: str = "unlisted"

# ─── Background Tasks ───────────────────────────────────────────────────────
async def _run_pipeline_task(url: str, options: dict):
    _progress.status = "running"
    _progress.started_at = time.time()
    _progress.error = None
    _progress.result = None
    
    try:
        # Run the actual pipeline (blocking call, so we wrap in run_in_executor if needed, 
        # but for simplicity we'll just await the result if it was async, 
        # or use run_in_executor for the blocking pipeline)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: run_pipeline(url, **options))
        
        _progress.status = "done"
        _progress.result = result
        await _broadcast_log("Pipeline completed successfully!")
    except Exception as e:
        _progress.status = "failed"
        _progress.error = str(e)
        logger.error("Pipeline task failed: %s", e, exc_info=True)
        await _broadcast_log(f"ERROR: {str(e)}")

async def _broadcast_log(message: str):
    formatted = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    for ws in _active_websockets:
        try:
            await ws.send_text(formatted)
        except:
            pass

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join("app", "templates", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return f.read()
    return "Index not found"

@app.post("/api/pipeline/run")
async def api_run_pipeline(request: PipelineRunRequest, background_tasks: BackgroundTasks):
    if _progress.status == "running":
        raise HTTPException(status_code=409, detail="Pipeline is already running")

    options = request.dict(exclude_unset=True)
    url = options.pop("url")
    
    # Handle boolean flag naming differences between run_pipeline args and CLI
    if options.get("no_vertical"): options["no_vertical"] = True
    if options.get("no_face"): options["no_face"] = True
    if options.get("no_heatmap"): options["no_heatmap"] = True

    _progress.status = "starting"
    background_tasks.add_task(_run_pipeline_task, url, options)
    
    return {"status": "started"}

@app.get("/api/pipeline/status")
async def api_pipeline_status():
    elapsed = None
    if _progress.started_at:
        if _progress.status == "running":
            elapsed = time.time() - _progress.started_at
        elif _progress.result:
            elapsed = _progress.result.get("metrics", {}).get("last_run", {}).get("duration_sec")

    return {
        "status": _progress.status,
        "elapsed_sec": round(elapsed, 1) if elapsed else None,
        "error": _progress.error,
        "result": _progress.result
    }

@app.get("/api/clips")
async def api_list_clips():
    clips_dir = cfg.clips_dir
    if not os.path.isdir(clips_dir):
        return []

    clips = []
    for fname in sorted(os.listdir(clips_dir)):
        if fname.lower().endswith((".mp4", ".mkv")):
            clips.append({"filename": fname})
    return clips

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    _active_websockets.append(websocket)
    try:
        # Stream existing logs first
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()[-50:]
                for line in lines:
                    await websocket.send_text(line.strip())
        
        while True:
            # Keep alive and wait for client to close
            await websocket.receive_text()
    except WebSocketDisconnect:
        _active_websockets.remove(websocket)
    except Exception:
        if websocket in _active_websockets:
            _active_websockets.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

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
from core.pipeline_slate import PipelineState
from run_pipeline import run as run_pipeline

import logging
from core.cancel import pipeline_cancel_event

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

# Custom Logging Handler to broadcast to WebSockets
class WebSocketLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))

    def emit(self, record):
        try:
            message = self.format(record)
            if _active_websockets:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_broadcast_raw_log(message))
        except Exception:
            pass

async def _broadcast_raw_log(message: str):
    for ws in list(_active_websockets):
        try:
            await ws.send_text(message)
        except Exception:
            try:
                _active_websockets.remove(ws)
            except ValueError:
                pass

# Register WebSocket log handler to logger
ws_handler = WebSocketLogHandler()
logger.addHandler(ws_handler)

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

class UpdateMetadataRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

class RenameClipRequest(BaseModel):
    new_name: str

class UploadClipRequest(BaseModel):
    privacy: str = "unlisted"



# Helper to scan clips
def _scan_clips():
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

    # Clear any previous cancellation signal
    pipeline_cancel_event.clear()

    _progress.status = "starting"
    _progress.error = None
    _progress.result = None
    _progress.started_at = time.time()
    background_tasks.add_task(_run_pipeline_task, url, options)
    
    return {"status": "started"}


async def _run_pipeline_task(url: str, options: dict):
    """Background task that runs the pipeline in a thread executor."""
    from core.pipeline_slate import PipelineState
    _progress.status = "running"
    PipelineState.reset()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: run_pipeline(url, **options)
        )
        _progress.result = result
        _progress.status = "done"
        logger.info("Pipeline task completed successfully")
    except Exception as exc:
        if pipeline_cancel_event.is_set():
            _progress.status = "cancelled"
            logger.info("Pipeline was cancelled by user request")
        else:
            _progress.status = "failed"
            _progress.error = str(exc)
            logger.error("Pipeline task failed: %s", exc)


@app.post("/api/pipeline/cancel")
async def api_cancel_pipeline():
    if _progress.status != "running":
        raise HTTPException(status_code=409, detail="No pipeline is currently running")
    pipeline_cancel_event.set()
    return {"status": "cancellation_requested"}


@app.get("/api/pipeline/status")
async def api_pipeline_status():
    elapsed = None
    if _progress.started_at:
        if _progress.status == "running":
            elapsed = time.time() - _progress.started_at
        elif _progress.result:
            elapsed = _progress.result.get("metrics", {}).get("last_run", {}).get("duration_sec")

    stage = PipelineState.current_stage
    steps = dict(PipelineState.steps)

    return {
        "status": _progress.status,
        "stage": stage,
        "steps": steps,
        "elapsed_sec": round(elapsed, 1) if elapsed else None,
        "error": _progress.error or PipelineState.last_error,
        "result": _progress.result
    }

@app.get("/api/clips")
async def api_list_clips():
    return _scan_clips()

@app.get("/api/clips/{filename}/download")
async def api_download_clip(filename: str):
    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(fpath, filename=filename, media_type="application/octet-stream")

@app.get("/api/clips/{filename}/stream")
async def api_stream_clip(filename: str):
    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(fpath, media_type="video/mp4")

@app.put("/api/clips/{filename}/rename")
async def api_rename_clip(filename: str, request: RenameClipRequest):
    new_name = request.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")

    old_path = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(old_path):
        raise HTTPException(status_code=404, detail="Clip not found")

    _, ext = os.path.splitext(filename)
    if not new_name.endswith(ext):
        new_name += ext

    new_path = os.path.join(cfg.clips_dir, new_name)
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail="A clip with that name already exists")

    os.rename(old_path, new_path)

    old_base = os.path.splitext(filename)[0]
    new_base = os.path.splitext(new_name)[0]
    old_meta = os.path.join(cfg.clips_dir, f"{old_base}.json")
    if os.path.isfile(old_meta):
        os.rename(old_meta, os.path.join(cfg.clips_dir, f"{new_base}.json"))

    return {"status": "renamed", "new_name": new_name}

@app.delete("/api/clips/{filename}")
async def api_delete_clip(filename: str):
    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Clip not found")
    os.remove(fpath)

    base = os.path.splitext(filename)[0]
    meta_path = os.path.join(cfg.clips_dir, f"{base}.json")
    if os.path.isfile(meta_path):
        os.remove(meta_path)

    return {"status": "deleted"}

@app.put("/api/clips/{filename}/metadata")
async def api_update_clip_metadata(filename: str, request: UpdateMetadataRequest):
    base = os.path.splitext(filename)[0]
    meta_path = os.path.join(cfg.clips_dir, f"{base}.json")

    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    if request.title is not None:
        meta["title"] = request.title
    if request.description is not None:
        meta["description"] = request.description

    os.makedirs(cfg.clips_dir, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {"status": "updated", "meta": meta}

@app.post("/api/clips/{filename}/upload")
async def api_upload_clip_to_youtube(filename: str, request: UploadClipRequest):
    from core.postprocess import upload_clips_to_youtube

    fpath = os.path.join(cfg.clips_dir, filename)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Clip not found")

    base = os.path.splitext(filename)[0]
    meta_path = os.path.join(cfg.clips_dir, f"{base}.json")
    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, 
            lambda: upload_clips_to_youtube([fpath], [meta], privacy=request.privacy)
        )
        return {"status": "uploaded", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/metrics")
async def api_metrics_endpoint():
    summary = get_metrics()
    saved = pipeline_metrics.load_metrics(cfg.pipeline_metrics_json)
    if saved and not summary.get("last_run"):
        summary = saved
    return summary

@app.get("/api/logs")
async def api_logs_endpoint(lines: int = 100):
    lines = min(lines, 500)
    if not os.path.isfile(LOG_FILE):
        return {"lines": [], "total": 0}
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        return {
            "lines": [l.rstrip() for l in tail],
            "total": len(all_lines),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config")
async def api_get_config():
    config_dict = {}
    for field_name in cfg.__dataclass_fields__:
        val = getattr(cfg, field_name, None)
        if field_name.startswith("_"):
            continue
        try:
            json.dumps(val)
            config_dict[field_name] = val
        except (TypeError, ValueError):
            config_dict[field_name] = str(val)
    return config_dict

@app.get("/api/styles")
async def api_get_styles():
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
    return styles_info

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    _active_websockets.append(websocket)
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()[-50:]
                for line in lines:
                    await websocket.send_text(line.strip())
        
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _active_websockets:
            _active_websockets.remove(websocket)
    except Exception:
        if websocket in _active_websockets:
            _active_websockets.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

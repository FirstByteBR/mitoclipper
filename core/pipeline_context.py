import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from core.logging_config import logger

@dataclass
class PipelineContext:
    url: str
    config: Any
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    transcript: List[Dict] = field(default_factory=list)
    viral_segments: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    video_duration: float = 0.0
    heatmap: Optional[List] = None
    status: str = "idle"
    current_stage: Optional[str] = None
    error: Optional[str] = None
    metrics: Any = None
    upload_results: List[Dict] = field(default_factory=list)

    def mark_stage(self, stage: str):
        self.current_stage = stage
        logger.info("Stage: %s", stage)
        from core.pipeline_slate import PipelineState
        PipelineState.current_stage = stage
        PipelineState.status = "running"
        stages_order = ['download', 'video_duration', 'audio_extraction', 'transcription', 'analysis', 'metadata', 'clip_generation', 'youtube_upload']
        if stage in stages_order:
            idx = stages_order.index(stage)
            for i in range(idx):
                PipelineState.mark(stages_order[i], True)
            PipelineState.mark(stage, False)

    def fail(self, error_msg: str):
        self.status = "failed"
        self.error = error_msg
        logger.error("Pipeline failed: %s", error_msg)
        from core.pipeline_slate import PipelineState
        PipelineState.fail(error_msg)

    def success(self):
        self.status = "done"
        logger.info("Pipeline completed successfully")
        from core.pipeline_slate import PipelineState
        PipelineState.status = "done"
        for k in PipelineState.steps:
            PipelineState.mark(k, True)

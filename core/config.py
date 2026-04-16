import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

load_dotenv()

@dataclass
class PipelineConfig:
    # General Pipeline Parameters
    top_k: int = 3
    max_duration: int = 60
    min_clip_duration: float = 15.0
    target_clip_duration: float = 35.0
    vertical: bool = True
    face_tracking: bool = True
    auto_upload: bool = False
    youtube_privacy: str = "unlisted"
    use_heatmap: bool = True

    # Paths and Directories
    data_dir: str = "data"
    downloads_dir: str = field(init=False)
    audio_dir: str = field(init=False)
    subtitles_dir: str = field(init=False)
    clips_dir: str = field(init=False)
    transcripts_dir: str = field(init=False)
    log_dir: str = field(init=False)

    pipeline_result_json: str = field(init=False)
    transcript_json: str = field(init=False)
    viral_segments_json: str = field(init=False)
    generated_metadata_json: str = field(init=False)
    pipeline_metrics_json: str = field(init=False)
    log_file: str = field(init=False)

    # Model Configuration
    llm_model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"
    embeddings_model_id: str = "all-MiniLM-L6-v2"
    emotion_model_id: str = "superb/wav2vec2-base-superb-er"
    whisper_model_id: str = "base"
    whisper_compute_type: str = "float16" # float16, int8_float16, int8
    llm_device: str = "cpu"
    
    # Analysis Parameters
    hook_keywords: List[str] = field(default_factory=lambda: [
        "insane", "crazy", "secret", "shocking", "impossible",
        "never", "nobody", "truth", "mistake", "warning",
    ])
    viral_score_weights: Dict[str, float] = field(default_factory=lambda: {
        "semantic_novelty": 0.25,
        "emotion_intensity": 0.15,
        "prosody_variation": 0.15,
        "hook_strength": 0.15,
        "heatmap_popularity": 0.30,
    })
    heatmap_position_sigma: float = 0.3
    llm_max_prompt_chars: int = 12000
    transcript_margin_sec: float = 15.0
    transcript_max_chars: int = 18000

    # FFmpeg/yt-dlp
    youtube_dl_cookiefile: Optional[str] = None
    youtube_dl_cookies_from_browser: Optional[str] = None
    ffmpeg_video_encoder: str = "libx264" # Use h264_nvenc for NVIDIA GPUs
    
    # Subtitle Styling (ASS)
    subtitle_style: str = "hormozi"
    subtitle_font: Optional[str] = None

    def __post_init__(self):
        # Override with environment variables
        self._load_from_env()
        # Override with config.yaml if it exists
        self._load_from_yaml()

        os.makedirs(self.data_dir, exist_ok=True)
        self.downloads_dir = os.path.join(self.data_dir, "downloads")
        self.audio_dir = os.path.join(self.data_dir, "audio")
        self.subtitles_dir = os.path.join(self.data_dir, "subtitles")
        self.clips_dir = os.path.join(self.data_dir, "clips")
        self.transcripts_dir = os.path.join(self.data_dir, "transcripts")
        self.log_dir = os.path.join(self.data_dir, "logs")

        self.pipeline_result_json = os.path.join(self.transcripts_dir, "pipeline_result.json")
        self.transcript_json = os.path.join(self.transcripts_dir, "transcript.json")
        self.viral_segments_json = os.path.join(self.transcripts_dir, "viral_segments.json")
        self.generated_metadata_json = os.path.join(self.transcripts_dir, "generated_metadata.json")
        self.pipeline_metrics_json = os.path.join(self.transcripts_dir, "pipeline_metrics.json")
        self.log_file = os.path.join(self.log_dir, "mitoclipper.log")

    def _load_from_env(self):
        for field_name in self.__dataclass_fields__:
            env_var = f"MITOCLIPPER_{field_name.upper()}"
            val = os.environ.get(env_var)
            if val is not None:
                # Basic type conversion
                default_val = getattr(self, field_name)
                if isinstance(default_val, bool):
                    setattr(self, field_name, val.lower() in ("true", "1", "yes"))
                elif isinstance(default_val, int):
                    setattr(self, field_name, int(val))
                elif isinstance(default_val, float):
                    setattr(self, field_name, float(val))
                elif isinstance(default_val, list):
                    setattr(self, field_name, [v.strip() for v in val.split(",")])
                else:
                    setattr(self, field_name, val)

    def _load_from_yaml(self, path="config.yaml"):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    for k, v in data.items():
                        if hasattr(self, k):
                            setattr(self, k, v)

# Global configuration instance
cfg = PipelineConfig()


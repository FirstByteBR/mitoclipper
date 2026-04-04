import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class PipelineConfig:
    # General Pipeline Parameters
    top_k: int = 3
    max_duration: int = 60
    min_clip_duration: float = 15.0
    target_clip_duration: float = 35.0
    vertical: bool = True
    face_tracking: bool = True # Placeholder, will be removed if not implemented
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
    llm_device_env_var: str = "MITOCLIPPER_LLM_DEVICE"
    log_level_env_var: str = "MITOCLIPPER_LOG_LEVEL"

    # Analysis Parameters
    hook_keywords: Dict[str, None] = field(default_factory=lambda: { # Using dict for O(1) lookup
        "insane": None, "crazy": None, "secret": None, "shocking": None, "impossible": None,
        "never": None, "nobody": None, "truth": None, "mistake": None, "warning": None,
    })
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
    youtube_dl_cookiefile_env_var: str = "YT_DLP_COOKIES"
    youtube_dl_cookies_from_browser_env_var: str = "YT_DLP_COOKIES_FROM_BROWSER"
    
    # Subtitle Styling (ASS)
    ass_fontname_tiktok: str = "Arial Black"
    ass_fontsize_tiktok: int = 92
    ass_primarycolor_tiktok: str = "&H00FFFFFF"
    ass_outlinecolor_tiktok: str = "&H00000000"
    ass_backcolor_tiktok: str = "&H80000000"

    ass_fontname_hook: str = "Arial Black"
    ass_fontsize_hook: int = 96
    ass_primarycolor_hook: str = "&H0000FFFF" # Yellow
    ass_outlinecolor_hook: str = "&H00000000"
    ass_backcolor_hook: str = "&H80000000"
    
    ass_wrapstyle: int = 0
    ass_alignment: int = 2
    ass_marginv: int = 140
    ass_outline: int = 5
    ass_shadow: int = 3

    def __post_init__(self):
        # Ensure data_dir exists before joining
        os.makedirs(self.data_dir, exist_ok=True)

        # Initialize paths relative to data_dir
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


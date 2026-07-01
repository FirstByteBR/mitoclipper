class PipelineState:
    status = "idle"
    current_stage = None
    steps = {
        "download": False,
        "video_duration": False,
        "audio_extraction": False,
        "transcription": False,
        "analysis": False,
        "metadata": False,
        "clip_generation": False,
        "youtube_upload": False,
    }
    current_video = None
    last_error = None
    youtube_upload_results = []

    @classmethod
    def reset(cls):
        cls.status = "idle"
        cls.current_stage = None
        cls.current_video = None
        cls.last_error = None
        cls.youtube_upload_results = []
        for k in cls.steps:
            cls.steps[k] = False

    @classmethod
    def mark(cls, step_name, done=True):
        if step_name in cls.steps:
            cls.steps[step_name] = done

    @classmethod
    def fail(cls, message):
        cls.status = "failed"
        cls.last_error = message
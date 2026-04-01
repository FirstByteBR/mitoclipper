class PipelineState:
    status = "idle"
    steps = {
        "download": False,
        "audio": False,
        "transcription": False,
        "analysis": False,
        "clips": False,
        "metadata": False,
    }
    current_video = None
    last_error = None

    @classmethod
    def reset(cls):
        cls.status = "idle"
        cls.current_video = None
        cls.last_error = None
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
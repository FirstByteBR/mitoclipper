import json
import os
import time
from contextlib import contextmanager
from collections import defaultdict

METRICS_FILE = os.environ.get("MITOCLIPPER_METRICS_FILE", "data/transcripts/pipeline_metrics.json")


class PipelineMetrics:
    def __init__(self):
        self.reset()

    def reset(self):
        self.runs = 0
        self.failures = 0
        self.last_run = None
        self.history = []
        self.current_run = None

    def start_run(self, url=None):
        self.runs += 1
        self.current_run = {
            "run_id": self.runs,
            "url": url,
            "start_time": time.time(),
            "end_time": None,
            "duration_sec": None,
            "status": "running",
            "error": None,
            "steps": {},
        }

    def end_run(self, success=True, error=None):
        if not self.current_run:
            return
        self.current_run["end_time"] = time.time()
        self.current_run["duration_sec"] = self.current_run["end_time"] - self.current_run["start_time"]
        self.current_run["status"] = "done" if success else "failed"
        self.current_run["error"] = error

        if not success:
            self.failures += 1

        self.last_run = self.current_run
        self.history.append(self.current_run)
        self.current_run = None

    def record_step(self, name, duration, success=True, extra=None):
        if not self.current_run:
            return
        self.current_run["steps"][name] = {
            "duration_sec": duration,
            "success": success,
            "extra": extra,
        }

    def record_error(self, step_name, error):
        if not self.current_run:
            return
        self.current_run["steps"].setdefault(step_name, {})
        self.current_run["steps"][step_name]["error"] = str(error)

    @contextmanager
    def step(self, name):
        if self.current_run is None:
            # Allow step-scoped metrics outside a full run (e.g., init path)
            ad_hoc = {
                "start_time": time.time(),
            }
            try:
                yield
                success = True
            except Exception as exc:
                success = False
                raise
            finally:
                duration = time.time() - ad_hoc["start_time"]
                self.record_step(name, duration, success=success)
        else:
            start = time.time()
            try:
                yield
                success = True
            except Exception as exc:
                success = False
                raise
            finally:
                duration = time.time() - start
                self.record_step(name, duration, success=success)

    def get_summary(self):
        summary = {
            "runs": self.runs,
            "failures": self.failures,
            "last_run": self.last_run,
        }
        if self.last_run and self.last_run.get("steps"):
            summary["last_run"]["total_step_duration"] = sum(
                s.get("duration_sec", 0) for s in self.last_run["steps"].values()
            )
        return summary

    def save_metrics(self, path=METRICS_FILE):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.get_summary(), f, ensure_ascii=False, indent=2)

    def load_metrics(self, path=METRICS_FILE):
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


pipeline_metrics = PipelineMetrics()


def get_metrics():
    return pipeline_metrics.get_summary()

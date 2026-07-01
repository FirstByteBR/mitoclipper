import threading

# Global thread-safe event to signal pipeline cancellation.
# Using threading.Event because the pipeline runs in a thread via run_in_executor.
pipeline_cancel_event = threading.Event()

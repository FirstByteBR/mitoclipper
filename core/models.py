import os

import torch
import whisper
from sentence_transformers import SentenceTransformer
from transformers import pipeline


class Models:
    llm = None
    embeddings = None
    emotion = None
    whisper_model = None


def _llm_device_and_dtype():
    """
    MITOCLIPPER_LLM_DEVICE:
      - cpu (default): avoids CUDA OOM when Whisper/embeddings/emotion already use the GPU.
      - cuda: use GPU 0 (set only if you have spare VRAM; prefer float16).
    """
    raw = os.environ.get("MITOCLIPPER_LLM_DEVICE", "cpu").strip().lower()
    if raw in ("", "cpu", "-1"):
        return -1, None
    if raw in ("cuda", "gpu", "0"):
        return 0, torch.float16
    return -1, None


def get_llm():
    if Models.llm is None:
        model_id = "Qwen/Qwen2.5-1.5B-Instruct"
        device, dtype = _llm_device_and_dtype()
        if dtype is not None and device >= 0:
            Models.llm = pipeline(
                "text-generation",
                model=model_id,
                device=device,
                torch_dtype=dtype,
            )
        else:
            Models.llm = pipeline(
                "text-generation",
                model=model_id,
                device=device,
            )
    return Models.llm


def get_embeddings():
    if Models.embeddings is None:
        Models.embeddings = SentenceTransformer("all-MiniLM-L6-v2")
    return Models.embeddings


def get_emotion():
    if Models.emotion is None:
        Models.emotion = pipeline(
            "audio-classification",
            model="superb/wav2vec2-base-superb-er",
        )
    return Models.emotion


def get_whisper():
    if Models.whisper_model is None:
        Models.whisper_model = whisper.load_model("base")
    return Models.whisper_model


def init_models():
    # Do not load the LLM here: it is only needed for metadata after analysis.
    # Loading Qwen on GPU alongside Whisper/embeddings/emotion commonly causes CUDA OOM on ~6GB cards.
    get_embeddings()
    get_emotion()
    get_whisper()
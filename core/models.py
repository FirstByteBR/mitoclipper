import os
import torch
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer
from transformers import pipeline

from core.logging_config import logger
from core.config import cfg


class Models:
    llm = None
    embeddings = None
    emotion = None
    whisper_model = None


def _get_torch_device():
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_llm():
    if Models.llm is None:
        model_id = cfg.llm_model_id
        device_str = cfg.llm_device
        
        # Map device string to torch device index/name
        if device_str == "cuda" and torch.cuda.is_available():
            device = 0
            dtype = torch.float16
        else:
            device = -1
            dtype = None

        logger.info("Loading LLM model %s on device=%s", model_id, device_str)
        
        kwargs = {"model": model_id, "device": device}
        if dtype:
            kwargs["torch_dtype"] = dtype
            
        Models.llm = pipeline("text-generation", **kwargs)
        logger.info("LLM model loaded")
    return Models.llm


def get_embeddings():
    if Models.embeddings is None:
        logger.info("Loading sentence embeddings model %s", cfg.embeddings_model_id)
        device = _get_torch_device()
        Models.embeddings = SentenceTransformer(cfg.embeddings_model_id, device=device)
        logger.info("Sentence embeddings model loaded on %s", device)
    return Models.embeddings


def get_emotion():
    if Models.emotion is None:
        logger.info("Loading emotion audio-classification model %s", cfg.emotion_model_id)
        device = 0 if torch.cuda.is_available() else -1
        Models.emotion = pipeline(
            "audio-classification",
            model=cfg.emotion_model_id,
            device=device
        )
        logger.info("Emotion model loaded on device=%s", device)
    return Models.emotion


def get_whisper():
    if Models.whisper_model is None:
        model_size = cfg.whisper_model_id
        device = _get_torch_device()
        compute_type = cfg.whisper_compute_type
        
        logger.info("Loading Faster-Whisper model %s on %s with %s", model_size, device, compute_type)
        Models.whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("Faster-Whisper model loaded")
    return Models.whisper_model


def init_models():
    # Pre-load core models
    get_embeddings()
    get_emotion()
    get_whisper()

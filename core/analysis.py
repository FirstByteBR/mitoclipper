import json
import re

import numpy as np
import librosa
from sklearn.metrics.pairwise import cosine_similarity
from core.models import get_embeddings, get_emotion, get_llm
from core.logging_config import logger


HOOK_KEYWORDS = {
    "insane",
    "crazy",
    "secret",
    "shocking",
    "impossible",
    "never",
    "nobody",
    "truth",
    "mistake",
    "warning",
}


def _heatmap_score(start, end, heatmap, video_duration):
    if heatmap:
        # heatmap is list of {'time': seconds, 'heat': 0-1}
        center = (start + end) / 2.0
        # Find closest points
        heats = []
        for point in heatmap:
            t = point['time']
            h = point['heat']
            if start <= t <= end:
                heats.append(h)
        if heats:
            return sum(heats) / len(heats)
        # If no points in segment, interpolate
        # Simple: find nearest
        min_dist = float('inf')
        nearest_h = 0.5
        for point in heatmap:
            dist = abs(point['time'] - center)
            if dist < min_dist:
                min_dist = dist
                nearest_h = point['heat']
        return nearest_h
    else:
        # Fallback to position-based
        if video_duration <= 0:
            return 0.5
        relative = center / video_duration
        import math
        sigma = 0.3
        score = math.exp(-((relative - 0.5) ** 2) / (2 * sigma ** 2))
        return score


def _segment_texts(segmentos):
    return [s.get("text", "").strip() for s in segmentos]


def _normalize(values):
    if not values:
        return []
    arr = np.array(values, dtype=float)
    min_v = float(np.nanmin(arr))
    max_v = float(np.nanmax(arr))
    if np.isclose(max_v, min_v):
        # all values equal, return neutral mid-range values
        return [0.5 for _ in values]
    normalized = (arr - min_v) / (max_v - min_v)
    return [float(x) for x in normalized]


def _semantic_novelty_scores(segmentos):
    texts = _segment_texts(segmentos)
    if not texts:
        return []
    embeddings = get_embeddings().encode(texts)
    similarity_means = []
    for i in range(len(embeddings)):
        start = max(0, i - 4)
        end = min(len(embeddings), i + 5)
        neighborhood = embeddings[start:end]
        sim = cosine_similarity([embeddings[i]], neighborhood)[0]
        similarity_means.append(float(np.mean(sim)))
    # Lower context similarity => higher novelty
    novelty = [1.0 - s for s in _normalize(similarity_means)]
    return novelty


def _hook_strength_scores(segmentos):
    scores = []
    for s in segmentos:
        text = s.get("text", "").lower()
        words = [w.strip(".,!?;:()[]\"'") for w in text.split()]
        if not words:
            scores.append(0.0)
            continue
        hits = sum(1 for w in words if w in HOOK_KEYWORDS)
        scores.append(hits / max(1, len(words)))
    return list(_normalize(scores))


def _prosody_scores(y, sr, segmentos):
    values = []
    for s in segmentos:
        start = int(float(s["start"]) * sr)
        end = int(float(s["end"]) * sr)
        chunk = y[start:end]
        if len(chunk) < sr // 2:
            values.append(0.0)
            continue
        energy = float(np.mean(np.abs(chunk)))
        pitch, _ = librosa.piptrack(y=chunk, sr=sr)
        pitch_vals = pitch[pitch > 0]
        pitch_var = float(np.var(pitch_vals)) if len(pitch_vals) else 0.0
        values.append(energy + pitch_var)
    return list(_normalize(values))


def _emotion_scores(y, sr, segmentos):
    clf = get_emotion()
    raw_scores = []
    for s in segmentos:
        start = int(float(s["start"]) * sr)
        end = int(float(s["end"]) * sr)
        chunk = y[start:end]
        if len(chunk) < sr:
            raw_scores.append(0.0)
            continue
        # Score by top confidence to represent emotional intensity.
        result = clf(chunk)
        raw_scores.append(float(max(r["score"] for r in result)))
    return list(_normalize(raw_scores))


def expand_clip_windows(
    clips,
    video_duration,
    min_duration=15.0,
    target_duration=35.0,
    max_duration=60.0,
    gap=0.5,
):
    """
    Whisper segments are often a few seconds long; expand each pick around its center
    so clips reach at least min_duration (up to target_duration), without exceeding max_duration.
    Clips are processed in list order (highest score first); later clips are nudged right if needed.
    """
    if not clips or video_duration is None:
        return clips
    vd = float(video_duration)
    want = max(min_duration, min(target_duration, max_duration))
    placed = []
    last_end = -gap

    for c in clips:
        c = dict(c)
        start = float(c["start"])
        end = float(c["end"])
        dur = max(0.0, end - start)
        center = (start + end) / 2.0

        if dur < want:
            half = want / 2.0
            ns = max(0.0, center - half)
            ne = ns + want
            if ne > vd:
                ne = vd
                ns = max(0.0, ne - want)
        else:
            ns = start
            ne = min(end, start + max_duration)

        clip_dur = ne - ns

        if ns < last_end + gap:
            ns = last_end + gap
            ne = ns + clip_dur
            if ne > vd:
                ne = vd
                ns = max(0.0, ne - clip_dur)

        if ne > vd:
            ne = vd
        if ne - ns < min_duration:
            ns = max(0.0, ne - min_duration)
        if ns >= ne:
            continue

        c["start"], c["end"] = ns, ne
        placed.append(c)
        last_end = ne

    return placed


def detectar_momentos_virais(
    segmentos,
    audio_path,
    top_k=3,
    max_duration=60,
    video_duration=None,
    min_clip_duration=15.0,
    target_clip_duration=35.0,
    heatmap=None,
):
    logger.info(
        "Starting viral moment detection: top_k=%s, max_duration=%s, min_clip_duration=%s, target_clip_duration=%s",
        top_k,
        max_duration,
        min_clip_duration,
        target_clip_duration,
    )
    if not segmentos:
        logger.warning("No segments provided to detectar_momentos_virais")
        return []

    semantic = _semantic_novelty_scores(segmentos)
    hooks = _hook_strength_scores(segmentos)
    
    # Load audio once for prosody and emotion
    y, sr = librosa.load(audio_path, sr=16000)
    prosody = _prosody_scores(y, sr, segmentos)
    emotion = _emotion_scores(y, sr, segmentos)
    position = [_heatmap_score(s["start"], s["end"], heatmap, video_duration) for s in segmentos]

    combined = []
    for i, s in enumerate(segmentos):
        start = float(s["start"])
        end = float(s["end"])
        duration = end - start
        if duration <= 0:
            continue
        if duration > max_duration:
            end = start + max_duration
        score = (
            0.25 * semantic[i]
            + 0.15 * emotion[i]
            + 0.15 * prosody[i]
            + 0.15 * hooks[i]
            + 0.30 * position[i]  # Prioritize middle sections like heatmaps
        )
        combined.append(
            {
                "start": start,
                "end": end,
                "semantic_novelty": semantic[i],
                "emotion_intensity": emotion[i],
                "prosody_variation": prosody[i],
                "hook_strength": hooks[i],
                "heatmap_popularity": position[i],
                "viral_score": float(score),
            }
        )

    combined.sort(key=lambda x: x["viral_score"], reverse=True)

    selected = []
    for clip in combined:
        overlaps = any(
            not (clip["end"] <= c["start"] or clip["start"] >= c["end"])
            for c in selected
        )
        if not overlaps:
            selected.append(clip)
        if len(selected) >= top_k:
            break

    selected = expand_clip_windows(
        selected,
        video_duration,
        min_duration=min_clip_duration,
        target_duration=target_clip_duration,
        max_duration=max_duration,
    )
    logger.info("Viral moment detection complete: selected %d clips", len(selected))
    return selected


def _transcript_for_clips(segmentos, top_clips, margin_sec=15.0, max_chars=18000):
    """
    Only include transcript lines near selected clips so the LLM prompt stays small.
    Full long-form transcripts + GPU models + Qwen caused CUDA OOM on typical 6GB GPUs.
    """
    if not top_clips:
        return ""

    lines = []
    seen = set()
    for c in top_clips:
        cs, ce = float(c["start"]), float(c["end"])
        a, b = cs - margin_sec, ce + margin_sec
        for s in segmentos:
            ss = float(s["start"])
            se = float(s["end"])
            if se < a or ss > b:
                continue
            key = (round(ss, 3), round(se, 3), s.get("text", ""))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"[{ss:.2f}-{se:.2f}] {s.get('text', '').strip()}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[...truncated...]"

    if not text.strip():
        fallback = "\n".join(
            f"[{float(s['start']):.2f}-{float(s['end']):.2f}] {s.get('text', '').strip()}"
            for s in segmentos[:120]
        )
        text = fallback[:max_chars]
        if len(fallback) > max_chars:
            text += "\n[...truncated...]"

    return text


def gerar_metadados(segmentos, top_clips):
    logger.info("Generating metadata for %d clips", len(top_clips) if top_clips else 0)
    texto = _transcript_for_clips(segmentos, top_clips)

    clips = "\n".join(
        [
            f"- start={c['start']:.2f}, end={c['end']:.2f}, viral_score={c['viral_score']:.3f}"
            for c in top_clips
        ]
    )

    prompt = f"""
You are a short-form content strategist.
Given a transcript and selected viral windows, create concise metadata.

Return strict JSON array with fields:
[
  {{"start": float, "end": float, "title": string, "description": string}}
]

Selected clips:
{clips}

Transcript (relevant excerpts):
{texto}
"""

    max_prompt_chars = 12000
    if len(prompt) > max_prompt_chars:
        prompt = prompt[:max_prompt_chars] + "\n[...truncated...]"

    pipe = get_llm()
    tokenizer = pipe.tokenizer
    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id

    out = pipe(
        prompt,
        max_new_tokens=256,
        do_sample=False,
        pad_token_id=pad_id,
        return_full_text=False,
    )
    if isinstance(out, list) and out:
        generated = out[0].get("generated_text", "")
        logger.info("Metadata generated, length=%d", len(generated))
        return generated
    generated = str(out)
    logger.info("Metadata generated (fallback), length=%d", len(generated))
    return generated


def parse_generated_metadata(raw_text):
    if not raw_text:
        return []
    if isinstance(raw_text, (list, dict)):
        return raw_text

    text = raw_text.strip()
    # Direct JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Try to extract first JSON array block inside text
    bracket_match = re.search(r"(\[.*\])", text, re.S)
    if bracket_match:
        candidate = bracket_match.group(1)
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # Fallback: empty
    logger.warning("Could not parse generated metadata JSON; returning empty list")
    return []

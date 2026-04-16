import json
import re
import math
import numpy as np
import librosa
from sklearn.metrics.pairwise import cosine_similarity
from core.models import get_embeddings, get_emotion, get_llm
from core.logging_config import logger
from core.config import cfg


def _heatmap_score(start, end, heatmap, video_duration):
    if heatmap:
        center = (start + end) / 2.0
        heats = []
        for point in heatmap:
            t = point['time']
            h = point['heat']
            if start <= t <= end:
                heats.append(h)
        if heats:
            return sum(heats) / len(heats)
        
        min_dist = float('inf')
        nearest_h = 0.5
        for point in heatmap:
            dist = abs(point['time'] - center)
            if dist < min_dist:
                min_dist = dist
                nearest_h = point['heat']
        return nearest_h
    else:
        if video_duration <= 0:
            return 0.5
        center = (start + end) / 2.0
        relative = center / video_duration
        sigma = cfg.heatmap_position_sigma
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
        return [0.5 for _ in values]
    normalized = (arr - min_v) / (max_v - min_v)
    return [float(x) for x in normalized]


def _semantic_novelty_scores(segmentos):
    texts = _segment_texts(segmentos)
    if not texts:
        return []
    
    # Batch encode all texts
    embeddings = get_embeddings().encode(texts, show_progress_bar=False)
    
    similarity_means = []
    for i in range(len(embeddings)):
        # Expand window for better novelty detection
        start = max(0, i - 10)
        end = min(len(embeddings), i + 11)
        neighborhood = embeddings[start:end]
        sim = cosine_similarity([embeddings[i]], neighborhood)[0]
        similarity_means.append(float(np.mean(sim)))
    
    novelty = [1.0 - s for s in _normalize(similarity_means)]
    return novelty


def _hook_strength_scores(segmentos):
    scores = []
    hooks = [h.lower() for h in cfg.hook_keywords]
    for s in segmentos:
        text = s.get("text", "").lower()
        words = [w.strip(".,!?;:()[]\"'") for w in text.split()]
        if not words:
            scores.append(0.0)
            continue
        hits = sum(1 for w in words if w in hooks)
        scores.append(hits / max(1, len(words)))
    return list(_normalize(scores))


def _prosody_scores(y, sr, segmentos):
    values = []
    for s in segmentos:
        start_sample = int(float(s["start"]) * sr)
        end_sample = int(float(s["end"]) * sr)
        chunk = y[start_sample:end_sample]
        if len(chunk) < sr // 4:
            values.append(0.0)
            continue
        energy = float(np.mean(np.abs(chunk)))
        
        # Reduced hop_length for speed
        pitch, _ = librosa.piptrack(y=chunk, sr=sr, hop_length=1024)
        pitch_vals = pitch[pitch > 0]
        pitch_var = float(np.var(pitch_vals)) if len(pitch_vals) else 0.0
        values.append(energy + pitch_var)
    return list(_normalize(values))


def _emotion_scores(y, sr, segmentos):
    clf = get_emotion()
    raw_scores = []
    
    # Batch inference for emotions would be better, 
    # but transformers pipeline for audio-classification 
    # expects individual clips or a list of numpy arrays.
    
    chunks = []
    valid_indices = []
    for i, s in enumerate(segmentos):
        start_sample = int(float(s["start"]) * sr)
        end_sample = int(float(s["end"]) * sr)
        chunk = y[start_sample:end_sample]
        if len(chunk) >= sr // 2:
            chunks.append(chunk)
            valid_indices.append(i)
    
    # Default all to 0.0
    scores = [0.0] * len(segmentos)
    
    if chunks:
        # Pipeline handles batching if we pass a list
        results = clf(chunks, batch_size=16)
        for idx, res in zip(valid_indices, results):
            scores[idx] = float(max(r["score"] for r in res))
            
    return list(_normalize(scores))


def expand_clip_windows(
    clips,
    video_duration,
    min_duration=15.0,
    target_duration=35.0,
    max_duration=60.0,
    gap=0.5,
):
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
    logger.info("Starting viral moment detection: top_k=%s", top_k)
    if not segmentos:
        return []

    semantic = _semantic_novelty_scores(segmentos)
    hooks = _hook_strength_scores(segmentos)
    
    y, sr = librosa.load(audio_path, sr=16000)
    prosody = _prosody_scores(y, sr, segmentos)
    emotion = _emotion_scores(y, sr, segmentos)
    position = [_heatmap_score(s["start"], s["end"], heatmap, video_duration) for s in segmentos]

    weights = cfg.viral_score_weights
    combined = []
    for i, s in enumerate(segmentos):
        start = float(s["start"])
        end = float(s["end"])
        duration = end - start
        if duration <= 0:
            continue
        
        score = (
            weights.get("semantic_novelty", 0.25) * semantic[i]
            + weights.get("emotion_intensity", 0.15) * emotion[i]
            + weights.get("prosody_variation", 0.15) * prosody[i]
            + weights.get("hook_strength", 0.15) * hooks[i]
            + weights.get("heatmap_popularity", 0.30) * position[i]
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
    return selected


def _transcript_for_clips(segmentos, top_clips):
    if not top_clips:
        return ""

    margin_sec = cfg.transcript_margin_sec
    max_chars = cfg.transcript_max_chars
    
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

    clips_str = "\n".join(
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
{clips_str}

Transcript (relevant excerpts):
{texto}
"""

    if len(prompt) > cfg.llm_max_prompt_chars:
        prompt = prompt[:cfg.llm_max_prompt_chars] + "\n[...truncated...]"

    pipe = get_llm()
    tokenizer = pipe.tokenizer
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    out = pipe(
        prompt,
        max_new_tokens=512,
        do_sample=False,
        pad_token_id=pad_id,
        return_full_text=False,
    )
    
    generated = ""
    if isinstance(out, list) and out:
        generated = out[0].get("generated_text", "")
    else:
        generated = str(out)
        
    logger.info("Metadata generated, length=%d", len(generated))
    return generated


def parse_generated_metadata(raw_text):
    if not raw_text:
        return []
    if isinstance(raw_text, (list, dict)):
        return raw_text

    text = raw_text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    bracket_match = re.search(r"(\[.*\])", text, re.S)
    if bracket_match:
        try:
            parsed = json.loads(bracket_match.group(1))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    return []

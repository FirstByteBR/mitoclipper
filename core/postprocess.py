import os
import re
import subprocess
from datetime import datetime, timedelta

# Same hook lexicon as analysis (for subtitle emphasis)
HOOK_WORDS = {
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


def proximo_id():
    pasta = "data/clips"
    os.makedirs(pasta, exist_ok=True)
    ids = []
    for f in os.listdir(pasta):
        prefix = f.split("_")[0]
        num = "".join(filter(str.isdigit, prefix))
        if num:
            ids.append(int(num))
    return max(ids) + 1 if ids else 1


def _ass_time(sec):
    td = timedelta(seconds=max(0.0, float(sec)))
    h = int(td.total_seconds() // 3600)
    m = int((td.total_seconds() % 3600) // 60)
    s = int(td.total_seconds() % 60)
    cs = int((td.total_seconds() % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _word_key(w):
    return re.sub(r"^[^\w]+|[^\w]+$", "", w.lower())


def _is_hook_word(word):
    return _word_key(word) in HOOK_WORDS


def _sanitize_ass_text(text):
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .strip()
    )


def _flatten_words(segmentos):
    words = []
    for seg in segmentos:
        for w in seg.get("words") or []:
            words.append(
                {
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "word": w.get("word", ""),
                }
            )
    words.sort(key=lambda x: x["start"])
    merged = []
    for w in words:
        if not merged:
            merged.append(dict(w))
            continue
        p = merged[-1]
        gap = w["start"] - p["end"]
        if gap < 0.02 and (w["end"] - w["start"]) < 0.12:
            p["word"] = (p["word"] + w["word"]).strip()
            p["end"] = w["end"]
        else:
            merged.append(dict(w))
    return merged


def _word_chunks(words, max_words=3):
    for i in range(0, len(words), max_words):
        yield words[i : i + max_words]


def face_horizontal_bias(video_path, t_start, duration, samples=6):
    """
    Always return 0.5 (center crop) since face detection is not available.
    """
    return 0.5


def _ffmpeg_escape_ass_path(path):
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", r"\\:")
    p = p.replace("'", r"\'")
    return p


def _build_vertical_vf(subtitle_path, bias=0.5):
    """
    9:16 output 1080x1920: scale to cover frame, crop width 1080; bias in [0,1] shifts crop.
    """
    ass = _ffmpeg_escape_ass_path(subtitle_path)
    b = min(1.0, max(0.0, float(bias)))
    return (
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920:(iw-1080)*{b:.6f}:0,"
        f"format=yuv420p,"
        f"ass={ass}"
    )


def gerar_legenda(segmentos, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    words = _flatten_words(segmentos)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\n")
        f.write("Title: MitoClipper\n")
        f.write("ScriptType: v4.00+\n")
        f.write("PlayResX: 1080\n")
        f.write("PlayResY: 1920\n")
        f.write("WrapStyle: 0\n\n")

        f.write("[V4+ Styles]\n")
        f.write(
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
            "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
        )
        f.write(
            "Style: TikTok,Arial Black,92,&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,1,5,3,2,80,80,140,1\n"
        )
        f.write(
            "Style: Hook,Arial Black,96,&H0000FFFF,&H0000D7FF,&H00000000,&H80000000,"
            "1,0,0,0,105,105,0,0,1,5,3,2,80,80,140,1\n\n"
        )

        f.write("[Events]\n")
        f.write(
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
        )

        for chunk in _word_chunks(words, max_words=3):
            line_start = chunk[0]["start"]
            line_end = chunk[-1]["end"]
            parts = []
            for w in chunk:
                raw = w["word"]
                dur = max(0.1, float(w["end"]) - float(w["start"]))
                cs = max(8, min(120, int(dur * 100)))
                display = _sanitize_ass_text(raw).upper()
                if not display:
                    continue
                if _is_hook_word(raw):
                    parts.append(
                        f"{{\\k{cs}}}{{\\fnArial Black\\fs96\\c&H0000FFFF&\\3c&H000000&}}"
                        f"{display}{{\\r}}"
                    )
                else:
                    parts.append(
                        f"{{\\k{cs}}}{{\\fnArial Black\\fs92\\c&H00FFFFFF&\\3c&H000000&}}"
                        f"{display}{{\\r}}"
                    )
            if not parts:
                continue
            text = " ".join(parts)
            f.write(
                f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},TikTok,,0,0,0,,{text}\n"
            )

    return output_path


def _segmentos_no_intervalo(segmentos, start, end):
    selected = []
    for seg in segmentos:
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", 0))
        if seg_end <= start or seg_start >= end:
            continue
        seg_copy = {
            "start": max(0.0, seg_start - start),
            "end": max(0.0, seg_end - start),
        }
        if "words" in seg:
            words = []
            for w in seg["words"]:
                w_start = float(w.get("start", 0))
                w_end = float(w.get("end", 0))
                if w_end <= start or w_start >= end:
                    continue
                words.append(
                    {
                        "start": max(0.0, w_start - start),
                        "end": max(0.0, w_end - start),
                        "word": w.get("word", ""),
                    }
                )
            seg_copy["words"] = words
        selected.append(seg_copy)
    return selected


def gerar_clips(video, cortes, segmentos, vertical=True, face_tracking=True):
    pasta = "data/clips"
    pasta_sub = "data/subtitles"
    os.makedirs(pasta, exist_ok=True)
    os.makedirs(pasta_sub, exist_ok=True)

    base_id = proximo_id()
    hoje = datetime.now()
    outputs = []

    for i, c in enumerate(cortes):
        start = float(c["start"])
        end = float(c["end"])
        dur = int(max(1, round(end - start)))
        letra = chr(ord("A") + i)
        nome = f"{base_id}{letra}_{hoje:%d_%m}_{dur}.mp4"
        saida = os.path.join(pasta, nome)

        segs_clip = _segmentos_no_intervalo(segmentos, start, end)
        sub_path = os.path.join(pasta_sub, f"{base_id}{letra}_{hoje:%d_%m}_{dur}.ass")
        gerar_legenda(segs_clip, sub_path)

        bias = 0.5
        if vertical and face_tracking:
            bias = face_horizontal_bias(video, start, end - start)

        if vertical:
            vf = _build_vertical_vf(sub_path, bias=bias)
        else:
            vf = f"ass={_ffmpeg_escape_ass_path(sub_path)}"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            video,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            saida,
        ]
        subprocess.run(cmd, check=True)
        outputs.append(
            {
                "video_path": saida,
                "subtitle_path": sub_path,
                "start": start,
                "end": end,
                "vertical": vertical,
                "face_bias": bias if vertical else None,
            }
        )

    return outputs

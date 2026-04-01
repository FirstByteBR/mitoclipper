import argparse
import json
import os

from core.analysis import detectar_momentos_virais, gerar_metadados
from core.models import init_models
from core.pipeline_slate import PipelineState
from core.postprocess import gerar_clips
from core.preprocess import (
    baixar_video,
    extrair_audio,
    get_video_duration_seconds,
    transcrever,
)

def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run(
    url,
    top_k=3,
    max_duration=60,
    min_clip_duration=15.0,
    target_clip_duration=35.0,
    vertical=True,
    face_tracking=True,
    cookies_file=None,
    cookies_from_browser=None,
):
    PipelineState.reset()
    PipelineState.status = "running"

    try:
        init_models()

        downloaded = baixar_video(
            url,
            cookies_file=cookies_file,
            cookies_from_browser=cookies_from_browser,
        )
        video_path = downloaded["video_path"]
        heatmap = downloaded.get("heatmap")
        PipelineState.current_video = video_path
        PipelineState.mark("download")

        video_duration = get_video_duration_seconds(video_path)

        audio_path = extrair_audio(video_path)
        PipelineState.mark("audio")

        segmentos = transcrever(audio_path)
        PipelineState.mark("transcription")
        _save_json("data/transcripts/transcript.json", segmentos)

        cortes = detectar_momentos_virais(
            segmentos=segmentos,
            audio_path=audio_path,
            top_k=top_k,
            max_duration=max_duration,
            video_duration=video_duration,
            min_clip_duration=min_clip_duration,
            target_clip_duration=target_clip_duration,
            heatmap=heatmap,
        )
        PipelineState.mark("analysis")
        _save_json("data/transcripts/viral_segments.json", cortes)

        metadados = gerar_metadados(segmentos, cortes)
        PipelineState.mark("metadata")
        _save_json("data/transcripts/generated_metadata.json", {"raw": metadados})

        clips = gerar_clips(
            video_path,
            cortes,
            segmentos,
            vertical=vertical,
            face_tracking=face_tracking,
        )
        PipelineState.mark("clips")

        PipelineState.status = "done"
        result = {
            "video_path": video_path,
            "video_duration_sec": video_duration,
            "audio_path": audio_path,
            "clips": clips,
            "viral_segments": cortes,
            "metadata_raw": metadados,
        }
        _save_json("data/transcripts/pipeline_result.json", result)
        return result
    except Exception as exc:
        PipelineState.fail(str(exc))
        raise


def main():
    parser = argparse.ArgumentParser(description="MitoClipper full pipeline runner")
    parser.add_argument(
        "url",
        nargs="?",
        help="Video URL, or a local path to a video file you already have",
    )
    parser.add_argument("--top-k", type=int, default=3, help="Number of clips to generate")
    parser.add_argument(
        "--max-duration",
        type=int,
        default=60,
        help="Maximum duration of each clip in seconds",
    )
    parser.add_argument(
        "--min-clip-duration",
        type=float,
        default=15.0,
        help="Minimum clip length after expansion (Whisper segments are often short)",
    )
    parser.add_argument(
        "--target-clip-duration",
        type=float,
        default=35.0,
        help="Target clip length when expanding around a viral moment",
    )
    parser.add_argument(
        "--no-vertical",
        action="store_true",
        help="Keep original aspect ratio (no 9:16 crop)",
    )
    parser.add_argument(
        "--no-face",
        action="store_true",
        help="Center crop for vertical (no face-based horizontal bias)",
    )
    parser.add_argument(
        "--cookies",
        metavar="PATH",
        help="Netscape cookies.txt for yt-dlp (fixes YouTube bot / 429 when logged in)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        metavar="SPEC",
        help=(
            "yt-dlp cookies: firefox, chrome, chrome:ProfileName, or "
            "firefox:/abs/path/to/profile (Zen: use firefox:PATH to Zen profile dir with cookies.sqlite)"
        ),
    )
    args = parser.parse_args()

    url = args.url or input("Enter video URL: ").strip()
    if not url:
        raise SystemExit("No URL provided.")

    result = run(
        url,
        top_k=args.top_k,
        max_duration=args.max_duration,
        min_clip_duration=args.min_clip_duration,
        target_clip_duration=args.target_clip_duration,
        vertical=not args.no_vertical,
        face_tracking=not args.no_face,
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

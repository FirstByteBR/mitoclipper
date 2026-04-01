import argparse
import json
import os
import time

from core.analysis import detectar_momentos_virais, gerar_metadados, parse_generated_metadata
from core.logging_config import logger
from core.metrics import pipeline_metrics
from core.models import init_models
from core.pipeline_slate import PipelineState
from core.postprocess import gerar_clips, upload_clips_to_youtube
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
    use_heatmap=True,
    auto_upload=False,
    youtube_privacy="unlisted",
):
    PipelineState.reset()
    PipelineState.status = "running"
    PipelineState.current_stage = "started"
    pipeline_metrics.start_run(url=url)
    logger.info("Pipeline run started for %s", url)

    try:
        with pipeline_metrics.step("download"):
            PipelineState.current_stage = "download"
            downloaded = baixar_video(
                url,
                cookies_file=cookies_file,
                cookies_from_browser=cookies_from_browser,
                use_heatmap=use_heatmap,
            )
            video_path = downloaded["video_path"]
            heatmap = downloaded.get("heatmap")
            PipelineState.current_video = video_path
            PipelineState.mark("download")

        with pipeline_metrics.step("video_duration"):
            PipelineState.current_stage = "video_duration"
            video_duration = get_video_duration_seconds(video_path)

        with pipeline_metrics.step("audio_extraction"):
            PipelineState.current_stage = "audio_extraction"
            audio_path = extrair_audio(video_path)
            PipelineState.mark("audio")

        with pipeline_metrics.step("transcription"):
            PipelineState.current_stage = "transcription"
            segmentos = transcrever(audio_path)
            PipelineState.mark("transcription")
            _save_json("data/transcripts/transcript.json", segmentos)

        with pipeline_metrics.step("analysis"):
            PipelineState.current_stage = "analysis"
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

        with pipeline_metrics.step("metadata"):
            PipelineState.current_stage = "metadata"
            metadados = gerar_metadados(segmentos, cortes)
            parsed_metadados = parse_generated_metadata(metadados)
            PipelineState.mark("metadata")
            _save_json("data/transcripts/generated_metadata.json", {"raw": metadados, "parsed": parsed_metadados})

        with pipeline_metrics.step("clip_generation"):
            PipelineState.current_stage = "clip_generation"
            clips = gerar_clips(
                video_path,
                cortes,
                segmentos,
                vertical=vertical,
                face_tracking=face_tracking,
            )
            PipelineState.mark("clips")

        upload_info = []
        if auto_upload:
            with pipeline_metrics.step("youtube_upload"):
                PipelineState.current_stage = "youtube_upload"
                upload_info = upload_clips_to_youtube(
                    [c.get("video_path") for c in clips],
                    parsed_metadados,
                    privacy=youtube_privacy,
                )
                PipelineState.youtube_upload_results = upload_info
                PipelineState.mark("youtube_upload")

        PipelineState.status = "done"
        result = {
            "upload_info": upload_info,
            "video_path": video_path,
            "video_duration_sec": video_duration,
            "audio_path": audio_path,
            "clips": clips,
            "viral_segments": cortes,
            "metadata_raw": metadados,
            "metrics": pipeline_metrics.get_summary(),
        }
        _save_json("data/transcripts/pipeline_result.json", result)
        pipeline_metrics.end_run(success=True)
        pipeline_metrics.save_metrics()
        logger.info("Pipeline run completed successfully in %.2fs", result["metrics"]["last_run"]["duration_sec"])
        return result
    except Exception as exc:
        PipelineState.fail(str(exc))
        pipeline_metrics.record_error("pipeline", exc)
        pipeline_metrics.end_run(success=False, error=str(exc))
        pipeline_metrics.save_metrics()
        logger.exception("Pipeline run failed for %s", url)
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
    parser.add_argument(
        "--no-heatmap",
        action="store_true",
        help="Do not fetch YouTube heatmap data during download/analysis",
    )
    parser.add_argument(
        "--auto-upload",
        action="store_true",
        help="Automatically upload generated clips to YouTube after pipeline and metadata generation",
    )
    parser.add_argument(
        "--youtube-privacy",
        choices=["public", "unlisted", "private"],
        default="unlisted",
        help="Privacy setting for uploaded videos",
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
        use_heatmap=not args.no_heatmap,
        auto_upload=args.auto_upload,
        youtube_privacy=args.youtube_privacy,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

import argparse
import json
import os
import time

from core.analysis import detectar_momentos_virais, gerar_metadados, parse_generated_metadata
from core.logging_config import logger
from core.metrics import pipeline_metrics
from core.models import init_models
from core.pipeline_context import PipelineContext
from core.postprocess import gerar_clips, upload_clips_to_youtube
from core.preprocess import (
    baixar_video,
    extrair_audio,
    get_video_duration_seconds,
    transcrever,
)
from core.config import cfg
from core.utils import save_json


def run(
    url,
    **kwargs
):
    # Update global cfg with CLI arguments
    for k, v in kwargs.items():
        if v is not None and hasattr(cfg, k):
            setattr(cfg, k, v)
    
    # Custom overrides for CLI flags
    if kwargs.get("no_vertical") is True: cfg.vertical = False
    if kwargs.get("no_face") is True: cfg.face_tracking = False
    if kwargs.get("no_heatmap") is True: cfg.use_heatmap = False

    # Initialize Context
    ctx = PipelineContext(url=url, config=cfg, metrics=pipeline_metrics)
    ctx.status = "running"
    pipeline_metrics.start_run(url=url)
    logger.info("Pipeline run started for %s", url)

    try:
        with pipeline_metrics.step("download"):
            ctx.mark_stage("download")
            downloaded = baixar_video(
                ctx.url,
                cookies_file=cfg.youtube_dl_cookiefile,
                cookies_from_browser=cfg.youtube_dl_cookies_from_browser,
                use_heatmap=cfg.use_heatmap,
            )
            ctx.video_path = downloaded["video_path"]
            ctx.heatmap = downloaded.get("heatmap")

        with pipeline_metrics.step("video_duration"):
            ctx.mark_stage("video_duration")
            ctx.video_duration = get_video_duration_seconds(ctx.video_path)

        with pipeline_metrics.step("audio_extraction"):
            ctx.mark_stage("audio_extraction")
            ctx.audio_path = extrair_audio(ctx.video_path)

        with pipeline_metrics.step("transcription"):
            ctx.mark_stage("transcription")
            ctx.transcript = transcrever(ctx.audio_path)
            save_json(cfg.transcript_json, ctx.transcript)

        with pipeline_metrics.step("analysis"):
            ctx.mark_stage("analysis")
            ctx.viral_segments = detectar_momentos_virais(
                segmentos=ctx.transcript,
                audio_path=ctx.audio_path,
                top_k=cfg.top_k,
                max_duration=cfg.max_duration,
                video_duration=ctx.video_duration,
                min_clip_duration=cfg.min_clip_duration,
                target_clip_duration=cfg.target_clip_duration,
                heatmap=ctx.heatmap,
            )
            save_json(cfg.viral_segments_json, ctx.viral_segments)

        with pipeline_metrics.step("metadata"):
            ctx.mark_stage("metadata")
            metadados_raw = gerar_metadados(ctx.transcript, ctx.viral_segments)
            ctx.metadata = {"raw": metadados_raw, "parsed": parse_generated_metadata(metadados_raw)}
            save_json(cfg.generated_metadata_json, ctx.metadata)

        with pipeline_metrics.step("clip_generation"):
            ctx.mark_stage("clip_generation")
            clips = gerar_clips(
                ctx.video_path,
                ctx.viral_segments,
                ctx.transcript,
                vertical=cfg.vertical,
                face_tracking=cfg.face_tracking,
                metadata=ctx.metadata.get("parsed", []),
            )
            ctx.clips = clips

        if cfg.auto_upload:
            with pipeline_metrics.step("youtube_upload"):
                ctx.mark_stage("youtube_upload")
                ctx.upload_results = upload_clips_to_youtube(
                    [c.get("video_path") for c in clips if c.get("success")],
                    ctx.metadata.get("parsed", []),
                    privacy=cfg.youtube_privacy,
                )

        ctx.success()
        result = {
            "upload_info": ctx.upload_results,
            "video_path": ctx.video_path,
            "video_duration_sec": ctx.video_duration,
            "audio_path": ctx.audio_path,
            "clips": ctx.clips,
            "viral_segments": ctx.viral_segments,
            "metadata": ctx.metadata,
            "metrics": pipeline_metrics.get_summary(),
        }
        save_json(cfg.pipeline_result_json, result)
        pipeline_metrics.end_run(success=True)
        pipeline_metrics.save_metrics(cfg.pipeline_metrics_json)
        return result
        
    except Exception as exc:
        ctx.fail(str(exc))
        pipeline_metrics.record_error("pipeline", exc)
        pipeline_metrics.end_run(success=False, error=str(exc))
        pipeline_metrics.save_metrics(cfg.pipeline_metrics_json)
        raise


def main():
    parser = argparse.ArgumentParser(description="MitoClipper full pipeline runner")
    parser.add_argument(
        "url",
        nargs="?",
        help="Video URL, or a local path to a video file you already have",
    )
    parser.add_argument("--top-k", type=int, help="Number of clips to generate")
    parser.add_argument(
        "--max-duration",
        type=int,
        help="Maximum duration of each clip in seconds",
    )
    parser.add_argument(
        "--min-clip-duration",
        type=float,
        help="Minimum clip length after expansion",
    )
    parser.add_argument(
        "--target-clip-duration",
        type=float,
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
        help="Netscape cookies.txt for yt-dlp",
    )
    parser.add_argument(
        "--cookies-from-browser",
        metavar="SPEC",
        help="yt-dlp cookies from browser",
    )
    parser.add_argument(
        "--no-heatmap",
        action="store_true",
        help="Do not fetch YouTube heatmap data",
    )
    parser.add_argument(
        "--auto-upload",
        action="store_true",
        help="Automatically upload generated clips to YouTube",
    )
    parser.add_argument(
        "--youtube-privacy",
        choices=["public", "unlisted", "private"],
        help="Privacy setting for uploaded videos",
    )
    parser.add_argument(
        "--subtitle-style",
        type=str,
        default="hormozi",
        help="Subtitle style to use (e.g., hormozi, mrbeast, minimalist)",
    )
    parser.add_argument(
        "--subtitle-font",
        type=str,
        help="Override the default font for the selected subtitle style",
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
        no_vertical=args.no_vertical,
        no_face=args.no_face,
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
        no_heatmap=args.no_heatmap,
        auto_upload=args.auto_upload,
        youtube_privacy=args.youtube_privacy,
        subtitle_style=args.subtitle_style,
        subtitle_font=args.subtitle_font,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

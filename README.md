# MitoClipper

A tool to download YouTube videos, transcribe them, analyze for viral moments, and generate short clips.

## Setup

1. Clone the repo.
2. Create a virtual environment: `python -m venv venv`
3. Activate: `source venv/bin/activate` (Linux/Mac) or `venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Run: `python run_pipeline.py "https://www.youtube.com/watch?v=..."`

## Options

- `--top-k`: Number of clips (default 3)
- `--max-duration`: Max clip length (default 60s)
- `--no-vertical`: Keep original aspect ratio
- `--no-face`: Disable face tracking (always center crop)
- `--cookies`: Path to cookies file for yt-dlp
- `--cookies-from-browser`: Browser to extract cookies from

## Output

Clips are saved in `data/clips/`, subtitles in `data/subtitles/`, transcripts in `data/transcripts/`.

The `data/` folder is gitignored as it contains generated files.

## Instrumentation

- Logs are written to `data/logs/mitoclipper.log` and stdout via `core/logging_config.py`.
- Metrics are exposed via:
  - `/api/result` (includes `metrics` with last run summary)
  - `/api/metrics` (direct metrics endpoint)
- Metrics file: `data/transcripts/pipeline_metrics.json`.

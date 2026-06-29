# 🎥 MitoClipper Evolution

**Professional AI-Powered Video Clipping & Auto-Reframing Suite**

MitoClipper Evolution is a sophisticated tool designed to transform long-form content (podcasts, interviews, streams) into viral short-form clips. Using a modern stack and high-performance ML models, it automates the entire pipeline from detection to rendering and uploading.

---

## ✨ Key Features

- **🚀 Dual-Engine LLM**: Blazing fast metadata generation using **Groq (Llama-3)** with local fallback for offline privacy.
- **🎯 Precision Face Tracking**: High-accuracy auto-framing for vertical (9:16) crops powered by **MediaPipe**.
- **⚡ Async Pipeline**: Completely rewritten in **FastAPI** with background task management for zero-lag UI performance.
- **✨ Professional Subtitles**: Dynamic, animated ASS subtitles (Hormozi/MrBeast style) powered by the **pysubs2** engine.
- **📟 Real-time Control Center**: A sleek Glassmorphism UI with **WebSocket** log streaming and live progress tracking.
- **🎬 Parallel Rendering**: Multi-threaded FFmpeg rendering for maximum performance.
- **☁️ Auto-Upload**: Integrated YouTube API support for automated publishing.

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.10+)
- **Frontend**: Tailwind CSS + Vanilla JS + Lucide Icons
- **ML/Computer Vision**: MediaPipe, OpenAI Whisper (Faster-Whisper), PyTorch, Librosa
- **Video Processing**: FFmpeg, pysubs2
- **Acceleration**: CUDA (Nvidia), MPS (Apple Silicon), or CPU fallback

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10+
- FFmpeg installed and in your PATH
- [Groq API Key](https://console.groq.com/) (Optional, for 10x faster metadata)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/yourusername/mitoclipper.git
cd mitoclipper

# Activate your venv
source clipenv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:
```env
MITOCLIPPER_GROQ_API_KEY=your_groq_key_here
MITOCLIPPER_WHISPER_MODEL_ID=base
MITOCLIPPER_LLM_DEVICE=cpu # or cuda
```

### 4. Running the Application
```bash
# Start the FastAPI server
python app/main.py
```
Visit `http://localhost:5000` in your browser.

---

## 🔧 Advanced Usage

### Local vs. API LLM
MitoClipper is built to be resilient. 
- If `MITOCLIPPER_GROQ_API_KEY` is found, it will use **Groq** for instantaneous clip titles and descriptions.
- If no key is found, it automatically falls back to a **local Qwen2.5-1.5B** model.

### Vertical Reframing
The face tracking logic samples the video to find the most prominent speaker. It uses **MediaPipe Face Detection** to ensure the 9:16 crop always centers the action, even in dynamic multi-person videos.

---

## 🛡️ Requirements Checklist
- [x] FFmpeg
- [x] Python 3.10+
- [x] MediaPipe (for Face Tracking)
- [x] Pysubs2 (for Subtitles)
- [x] FastAPI / Uvicorn

---

## 📝 License
MIT License - Copyright (c) 2026 MitoClipper Team

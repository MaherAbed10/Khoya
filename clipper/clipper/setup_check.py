"""Load keys from clipper/.env and report anything missing before a job starts."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip().strip('"').strip("'")
        if val:
            os.environ.setdefault(key.strip(), val)


def problems() -> list[str]:
    out = []
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        out.append("ffmpeg is not installed. Mac: brew install ffmpeg / Windows: winget install ffmpeg")
    if not shutil.which("yt-dlp"):
        out.append("yt-dlp is missing. Run: pip install -r requirements.txt")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        out.append("No Claude key. Put ANTHROPIC_API_KEY=... in clipper/.env (get one at console.anthropic.com)")
    return out

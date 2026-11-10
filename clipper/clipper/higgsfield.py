"""Optional AI intro shots through the Higgsfield API (https://docs.higgsfield.ai)."""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

API = "https://api.higgsfield.ai"
# Any Higgsfield text-to-video endpoint works; override with HIGGSFIELD_MODEL.
DEFAULT_MODEL = "bytedance/seedance-2.0/text-to-video"


def enabled() -> bool:
    return bool(os.environ.get("HF_API_KEY_ID") and os.environ.get("HF_API_KEY_SECRET"))


def _headers() -> dict:
    return {
        "Authorization": f"Key {os.environ['HF_API_KEY_ID']}:{os.environ['HF_API_KEY_SECRET']}",
        "Content-Type": "application/json",
    }


def generate_intro(prompt: str, out: Path, seconds: int = 5, timeout_s: int = 600) -> Path:
    model = os.environ.get("HIGGSFIELD_MODEL", DEFAULT_MODEL)
    body = {"prompt": prompt, "resolution": "720p", "duration": seconds,
            "aspect_ratio": "9:16", "generate_audio": False}
    r = httpx.post(f"{API}/{model}", json=body, headers=_headers(), timeout=60)
    r.raise_for_status()
    status_url = r.json()["status_url"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = httpx.get(status_url, headers=_headers(), timeout=30)
        s.raise_for_status()
        data = s.json()
        state = data.get("status")
        if state == "completed":
            video_url = data["video"]["url"]
            with httpx.stream("GET", video_url, timeout=120, follow_redirects=True) as v:
                v.raise_for_status()
                with open(out, "wb") as f:
                    for chunk in v.iter_bytes():
                        f.write(chunk)
            return out
        if state in {"failed", "nsfw", "canceled", "cancelled"}:
            raise RuntimeError(f"Higgsfield generation ended with status '{state}'")
        time.sleep(5)
    raise RuntimeError("Higgsfield generation timed out")

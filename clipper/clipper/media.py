"""Download, transcribe, measure loudness and render vertical clips with ffmpeg."""
from __future__ import annotations

import json
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

W, H = 1080, 1920


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{p.stderr[-2000:]}")
    return p.stdout


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def download(url: str, out_dir: Path, section: str = "") -> Path:
    """Download a stream/VOD/clip with yt-dlp. `section` like '1:00:00-1:45:00' limits long VODs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if Path(url).exists():  # local file path
        return Path(url)
    cmd = ["yt-dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
           "-o", str(out_dir / "source.%(ext)s"), "--no-playlist"]
    if section:
        cmd += ["--download-sections", f"*{section}", "--force-keyframes-at-cuts"]
    run(cmd + [url])
    files = sorted(out_dir.glob("source.*"))
    if not files:
        raise RuntimeError("Download finished but no file was found.")
    return files[0]


def duration_of(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def has_audio(path: Path) -> bool:
    out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
               "-of", "csv=p=0", str(path)])
    return bool(out.strip())


# --------------------------------------------------------------------------- #
# Audio analysis
# --------------------------------------------------------------------------- #
def extract_wav(video: Path, wav: Path) -> Path:
    run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav)])
    return wav


def loudness_per_second(wav: Path) -> np.ndarray:
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    n = len(data) // sr
    if n == 0:
        return np.zeros(1)
    rms = np.sqrt((data[: n * sr].reshape(n, sr) ** 2).mean(axis=1) + 1e-9)
    lo, hi = np.percentile(rms, 5), np.percentile(rms, 99)
    return np.clip((rms - lo) / max(hi - lo, 1e-9), 0, 1)


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str


def transcribe(wav: Path, model_size: str = "base") -> tuple[list[Segment], list[Word]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segs, _ = model.transcribe(str(wav), word_timestamps=True, vad_filter=True)
    segments, words = [], []
    for s in segs:
        segments.append(Segment(s.start, s.end, s.text.strip()))
        for w in s.words or []:
            words.append(Word(w.start, w.end, w.word.strip()))
    return segments, words


def transcript_for_claude(segments: list[Segment], loud: np.ndarray, duration: float) -> str:
    lines = []
    for s in segments:
        a, b = int(s.start), max(int(s.start) + 1, int(s.end))
        score = float(loud[a:b].max()) if a < len(loud) else 0.0
        lines.append(f"[{s.start:.1f}-{s.end:.1f}] ({score:.2f}) {s.text}")
    # Also flag loud moments with no speech (explosions, crashes, screams).
    covered = np.zeros(len(loud), dtype=bool)
    for s in segments:
        covered[int(s.start): int(s.end) + 1] = True
    for t in np.where((loud > 0.85) & ~covered)[0]:
        lines.append(f"[{t:.1f}-{t + 1:.1f}] ({loud[t]:.2f}) <loud moment, no speech>")
    lines.sort(key=lambda l: float(l[1:l.index("-")]))
    if not lines:
        lines.append(f"[0.0-{duration:.1f}] (0.00) <no speech detected>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Captions (ASS)
# --------------------------------------------------------------------------- #
def _ts(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(path: Path, words: list[Word], start: float, end: float, hook: str) -> Path:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,520,1
Style: Hook,DejaVu Sans,72,&H00000000,&H00000000,&H0017FED1,&H0017FED1,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if hook:
        events.append(f"Dialogue: 1,{_ts(0)},{_ts(min(3.0, end - start))},Hook,,0,0,0,,{_esc(hook.upper())}")
    clip_words = [w for w in words if w.start >= start - 0.05 and w.end <= end + 0.05 and w.text]
    for i in range(0, len(clip_words), 3):
        group = clip_words[i:i + 3]
        a = group[0].start - start
        b = (clip_words[i + 3].start - start) if i + 3 < len(clip_words) else group[-1].end - start
        b = min(b, group[-1].end - start + 0.6)
        text = " ".join(_esc(w.text) for w in group).upper()
        events.append(f"Dialogue: 0,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{text}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def _ff_path(p: Path) -> str:
    # Escape for use inside an ffmpeg filter argument.
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render_vertical(src: Path, start: float, end: float, ass: Path, out: Path) -> Path:
    """Gameplay centred over a blurred, zoomed copy of itself, captions burned in."""
    fc = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:2,eq=brightness=-0.08[bg];"
        f"[0:v]scale={W}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,format=yuv420p,subtitles='{_ff_path(ass)}'[v]"
    )
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(src),
           "-filter_complex", fc, "-map", "[v]"]
    if has_audio(src):
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "1:a", "-shortest", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", str(out)]
    run(cmd)
    return out


def prepend_intro(intro: Path, clip: Path, out: Path) -> Path:
    """Normalise an AI intro to 1080x1920/30fps and put it in front of the clip."""
    a_in = "[0:a]" if has_audio(intro) else None
    fc = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,format=yuv420p,setsar=1[iv];"
        f"[1:v]setsar=1[cv];"
    )
    inputs = ["-i", str(intro), "-i", str(clip)]
    if a_in is None:
        inputs += ["-f", "lavfi", "-t", f"{duration_of(intro):.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        a_in = "[2:a]"
    fc += f"{a_in}aresample=48000,aformat=channel_layouts=stereo[ia];[1:a]aresample=48000[ca];"
    fc += "[iv][ia][cv][ca]concat=n=2:v=1:a=1[v][a]"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-movflags", "+faststart", str(out)])
    return out

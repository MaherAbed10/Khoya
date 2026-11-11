"""Whole job: Whop link + source link(s) -> folder of finished clips with captions."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable

from . import ai, higgsfield, media, setup_check

setup_check.load_env()

OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "outputs"


def run_job(
    whop_url: str,
    source_urls: list[str],
    rules: str = "",
    n_clips: int = 5,
    section: str = "",
    ai_intro: bool = False,
    whisper_model: str = "base",
    job_dir: Path | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    missing = setup_check.problems()
    if missing:
        raise RuntimeError("Setup not finished:\n- " + "\n- ".join(missing))
    job_dir = job_dir or OUTPUT_ROOT / time.strftime("%Y%m%d-%H%M%S")
    job_dir.mkdir(parents=True, exist_ok=True)

    log("Reading the Whop campaign with Claude...")
    brief = ai.read_campaign(whop_url, rules)
    (job_dir / "brief.json").write_text(brief.model_dump_json(indent=2))
    log(f"Campaign: {brief.campaign_name} | {brief.pay_rate} | {brief.min_seconds}-{brief.max_seconds}s "
        f"| tags: {' '.join(brief.required_hashtags + brief.required_mentions) or 'none'}")

    sources = [u for u in source_urls if u.strip()] or brief.source_links
    if not sources:
        raise RuntimeError("No source video link. Paste a stream/VOD/Drive link.")
    if ai_intro and not higgsfield.enabled():
        log("AI intro skipped: set HF_API_KEY_ID and HF_API_KEY_SECRET to use Higgsfield.")
        ai_intro = False
    if ai_intro and not brief.allows_ai_generated_footage:
        log("AI intro skipped: this campaign's rules don't clearly allow AI footage (could get you rejected).")
        ai_intro = False

    results: list[dict] = []
    per_source = max(1, -(-n_clips // len(sources)))
    for si, url in enumerate(sources, 1):
        sdir = job_dir / f"source{si}"
        log(f"[{si}/{len(sources)}] Downloading {url} ...")
        src = media.download(url.strip(), sdir, section)
        dur = media.duration_of(src)
        log(f"Downloaded {dur / 60:.1f} min. Transcribing (this is the slow part)...")
        wav = media.extract_wav(src, sdir / "audio.wav")
        loud = media.loudness_per_second(wav)
        segments, words = media.transcribe(wav, whisper_model)
        lines = media.transcript_for_claude(segments, loud, dur)

        log("Claude is picking the best moments...")
        plan = ai.plan_clips(brief, lines, dur, per_source, ai_intro)

        taken: list[tuple[float, float]] = []
        for clip in plan.clips[:per_source]:
            start = max(0.0, min(clip.start, dur - 1))
            end = min(dur, max(clip.end, start + brief.min_seconds))
            end = min(end, start + brief.max_seconds)
            if end - start < 3 or any(start < b and end > a for a, b in taken):
                continue
            taken.append((start, end))
            idx = len(results) + 1
            name = f"clip_{idx:02d}"
            log(f"Rendering {name}: {start:.0f}s-{end:.0f}s  \"{clip.hook_text}\"")
            ass = media.write_ass(job_dir / f"{name}.ass", words, start, end, clip.hook_text)
            out = media.render_vertical(src, start, end, ass, job_dir / f"{name}.mp4")

            if ai_intro and clip.ai_intro_prompt:
                try:
                    log(f"Generating Higgsfield intro for {name}...")
                    intro = higgsfield.generate_intro(clip.ai_intro_prompt, job_dir / f"{name}_intro_raw.mp4")
                    media.prepend_intro(intro, out, job_dir / f"{name}_with_intro.mp4")
                except Exception as e:  # intro is a bonus, never block the clip
                    log(f"Intro failed for {name}: {e}")

            info = {
                "file": out.name,
                "with_intro": f"{name}_with_intro.mp4" if (job_dir / f"{name}_with_intro.mp4").exists() else None,
                "source": url,
                "start": round(start, 1),
                "end": round(end, 1),
                **clip.model_dump(exclude={"start", "end"}),
            }
            (job_dir / f"{name}.txt").write_text(
                f"TITLE:\n{clip.title}\n\nCAPTION:\n{clip.caption}\n\nWHY:\n{clip.why_it_will_hit}\n"
            )
            results.append(info)
            if len(results) >= n_clips:
                break

    (job_dir / "clips.json").write_text(json.dumps(results, indent=2))
    log(f"Done: {len(results)} clips in {job_dir}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Turn a Whop campaign + stream link into ready-to-post clips.")
    p.add_argument("--whop", default="", help="Whop campaign link")
    p.add_argument("--source", action="append", default=[], help="Stream/VOD/clip link or local file (repeatable)")
    p.add_argument("--rules", default="", help="Campaign rules pasted as text")
    p.add_argument("--clips", type=int, default=5)
    p.add_argument("--section", default="", help="Only use part of a long VOD, e.g. 1:00:00-1:45:00")
    p.add_argument("--ai-intro", action="store_true", help="Add a Higgsfield AI intro if the campaign allows it")
    p.add_argument("--whisper", default="base", help="Whisper model: tiny/base/small/medium")
    a = p.parse_args()
    run_job(a.whop, a.source, a.rules, a.clips, a.section, a.ai_intro, a.whisper)


if __name__ == "__main__":
    main()

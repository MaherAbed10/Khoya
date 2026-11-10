"""Claude calls: read the Whop campaign, then direct the clips."""
from __future__ import annotations

import re

import anthropic
import httpx
from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _ask(prompt: str, schema: type[BaseModel], effort: str = "high") -> BaseModel:
    # Server-side fallback is on: if a request is declined, the API retries it
    # on a fallback model inside the same call.
    resp = client().beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        output_format=schema,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request.")
    if resp.parsed_output is None:
        raise RuntimeError(f"Claude returned no usable answer (stop_reason={resp.stop_reason}).")
    return resp.parsed_output


# --------------------------------------------------------------------------- #
# 1. Campaign brief
# --------------------------------------------------------------------------- #
class CampaignBrief(BaseModel):
    campaign_name: str
    creator: str = Field(description="Streamer/brand the campaign is for, or 'unknown'")
    pay_rate: str = Field(description="e.g. '$1.50 per 1K views', or 'unknown'")
    platforms: list[str] = Field(description="Platforms that count for payout")
    min_seconds: int
    max_seconds: int
    required_hashtags: list[str]
    required_mentions: list[str] = Field(description="@handles that must be tagged")
    required_caption_text: str = Field(description="Exact text/link that must be in the caption, or ''")
    content_rules: list[str] = Field(description="Every rule about what the clip must contain or look like")
    banned: list[str] = Field(description="Everything that gets a submission rejected")
    source_links: list[str] = Field(description="Content links the campaign provides for clipping")
    allows_ai_generated_footage: bool = Field(
        description="True only if the rules clearly allow adding AI-generated footage"
    )
    style_notes: str = Field(description="What kind of clips this campaign wants, in one or two sentences")


def _fetch_page_text(url: str) -> str:
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20,
                      headers={"User-Agent": "Mozilla/5.0 (clipper)"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return f"(could not load page: {e})"
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", r.text)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text[:40000]


def read_campaign(whop_url: str, pasted_rules: str) -> CampaignBrief:
    page = _fetch_page_text(whop_url) if whop_url else "(no link given)"
    prompt = f"""You are reading a Whop "Content Rewards" clipping campaign so a clipper can follow it exactly and get paid.

Campaign link: {whop_url or "(none)"}

Text scraped from the campaign page (may be incomplete or just page chrome if it needs a login):
<page>
{page}
</page>

Rules the clipper pasted in themselves (trust these over the page if they disagree):
<pasted>
{pasted_rules or "(none)"}
</pasted>

Extract the campaign brief. Where something is not stated, use sensible defaults for short-form
vertical clipping (15-60 seconds, platforms TikTok/Instagram/YouTube Shorts) and say 'unknown'
for names or pay. Never invent hashtags, mentions or links that are not in the text."""
    return _ask(prompt, CampaignBrief, effort="medium")


# --------------------------------------------------------------------------- #
# 2. Clip plan
# --------------------------------------------------------------------------- #
class ClipIdea(BaseModel):
    start: float = Field(description="Start time in seconds in the source")
    end: float = Field(description="End time in seconds in the source")
    hook_text: str = Field(description="On-screen hook for the first 3 seconds, max 7 words, no emojis")
    title: str = Field(description="Post title / YouTube Shorts title, under 70 characters")
    caption: str = Field(description="Post caption including every required hashtag, mention and text")
    why_it_will_hit: str
    virality_score: int = Field(description="1-10")
    ai_intro_prompt: str = Field(
        description="Prompt for a 5 second AI-generated vertical intro shot, or '' if not allowed or not useful"
    )


class ClipPlan(BaseModel):
    clips: list[ClipIdea]


def plan_clips(brief: CampaignBrief, transcript_lines: str, duration: float,
               n_clips: int, want_ai_intro: bool) -> ClipPlan:
    ai_rule = (
        "The campaign allows AI footage and the clipper wants an AI intro: write an ai_intro_prompt for each "
        "clip - a cinematic 5 second vertical shot that sets the mood (e.g. a neon-lit Florida city at night, "
        "a sports car drifting on a wet highway). No real people, no streamer likeness, no logos, no on-screen "
        "text, no game names."
        if want_ai_intro and brief.allows_ai_generated_footage
        else "Leave ai_intro_prompt empty."
    )
    prompt = f"""You are a top short-form editor who clips livestreams for paid Whop campaigns. Views are money:
pick the moments most likely to be watched to the end and shared.

<campaign_brief>
{brief.model_dump_json(indent=2)}
</campaign_brief>

The source is {duration:.0f} seconds long. Below is its transcript, one line per segment:
[start-end] (loudness 0-1) text
Loud spikes usually mean the streamer is screaming, laughing or reacting - strong clip candidates.

<transcript>
{transcript_lines}
</transcript>

Pick the {n_clips} best clips. Rules:
- Each clip must be between {brief.min_seconds} and {brief.max_seconds} seconds and must not overlap another.
- Start right before the action (no slow intros); end on the payoff or punchline, never mid-sentence.
- Follow every content rule and avoid everything banned in the brief.
- GTA 6 launch week: avoid major story spoilers or ending reveals; chaos, funny NPCs, physics, reactions,
  secrets and money/guide tips do best.
- hook_text makes a scroller stop: curiosity or stakes, not a description.
- caption must contain every required hashtag, mention and required text from the brief, plus 3-5 relevant
  extra hashtags.
- {ai_rule}
Order clips from best to worst."""
    return _ask(prompt, ClipPlan, effort="high")

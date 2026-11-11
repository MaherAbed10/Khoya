# Whop Clipper

Paste a **Whop Content Rewards campaign** and the **stream/VOD link**. You get back vertical 9:16 clips
with burned-in captions and a hook, plus a ready-to-paste caption with the campaign's required tags.

What happens on each job:

1. **Claude reads the campaign**: pay rate, length limits, required hashtags/@mentions, what's banned, and
   whether AI footage is allowed.
2. **Download**: yt-dlp grabs the source (YouTube, Twitch, Kick, X, Drive, etc. or a local file).
3. **Listen**: Whisper transcribes with word timings, and a loudness scan finds screams, crashes and hype spikes.
4. **Claude picks the moments** most likely to get watched to the end, writes the hook, title and caption,
   and follows the campaign rules.
5. **Render**: ffmpeg cuts each clip to 1080×1920 with a blurred background fill, big word-by-word
   captions and the hook on screen for the first 3 seconds.
6. **Optional Higgsfield intro**: a 5-second AI cinematic shot in front of the clip, used **only** if the
   campaign allows AI footage. Otherwise you can get rejected, so it skips itself.

## Setup (once)

1. Install Python 3.10+ and ffmpeg (`brew install ffmpeg` on Mac, `winget install ffmpeg` on Windows).
2. Double-click **`start.bat`** (Windows) or run **`./start.sh`** (Mac/Linux). The first run installs
   everything and creates a `.env` file.
3. Open `clipper/.env` and paste your Claude key after `ANTHROPIC_API_KEY=` (from console.anthropic.com).
   Higgsfield keys are optional. Restart the start script.

If anything is missing, the page shows it in red at the top.

## Use it

Start it with the start script. The browser opens http://localhost:5000. Then paste:

- the Whop campaign link
- the campaign rules, copied from Whop (the page often needs a login, so pasting them is the reliable way)
- one or more stream links, one per line
- for 4-hour VODs, a section like `1:00:00-1:45:00` so it only processes the good part

Each clip gets **Download** and **Copy caption** buttons. Post the clip on the platforms the campaign pays
for, then submit the post links on Whop.

Command-line version:

```bash
python -m clipper.pipeline --whop "https://whop.com/..." --rules "$(cat rules.txt)" \
  --source "https://www.twitch.tv/videos/123" --clips 5 --section 0:30:00-1:30:00
```

Files land in `clipper/outputs/<job>/`: `clip_01.mp4`, `clip_01.txt` (title and caption), `clips.json`
and `brief.json`.

## Tips

- **Speed**: transcription is the slow step. `--whisper tiny` is fastest; `small` is more accurate. A GPU
  helps a lot.
- **Cost**: each job makes two Claude calls (Claude Opus 5.5), usually cents per job. Higgsfield intros cost
  Higgsfield credits per clip.
- **Stay paid**: only clip content the campaign gives you permission to use. Avoid GTA 6 story spoilers in
  launch week, and never miss a required tag. Missing tags are the #1 reason submissions get rejected.

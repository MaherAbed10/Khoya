"""Local web page: paste a Whop link + stream links, get clips back.

Run:  python app.py   then open http://localhost:5000
"""
from __future__ import annotations

import html
import json
import threading
import time
import traceback
import uuid
from pathlib import Path

from flask import Flask, abort, redirect, request, send_from_directory, url_for

from clipper import higgsfield
from clipper.pipeline import OUTPUT_ROOT, run_job

app = Flask(__name__)
JOBS: dict[str, dict] = {}

STYLE = """
:root{--bg:#0b0b0c;--card:#151517;--line:#2a2a2e;--text:#f2f2f2;--muted:#9a9aa2;--accent:#d1fe17}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 64px}h1{font-size:28px;margin:0 0 4px}
p.sub{color:var(--muted);margin:0 0 24px}label{display:block;font-weight:600;margin:18px 0 6px}
small{color:var(--muted);font-weight:400}
input,textarea{width:100%;background:var(--card);color:var(--text);border:1px solid var(--line);
border-radius:10px;padding:12px;font:inherit}textarea{min-height:90px}
.row{display:flex;gap:12px;flex-wrap:wrap}.row>div{flex:1;min-width:160px}
.check{display:flex;gap:10px;align-items:center;margin-top:18px;font-weight:400}.check input{width:auto}
button,.btn{background:var(--accent);color:#000;border:0;border-radius:10px;padding:12px 20px;font-weight:700;
cursor:pointer;text-decoration:none;display:inline-block;margin-top:22px}
.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line);margin:0;padding:8px 12px;font-weight:500}
pre{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;white-space:pre-wrap;
font-size:13px;max-height:320px;overflow:auto}
.clip{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:16px 0;
display:grid;grid-template-columns:220px 1fr;gap:16px}@media(max-width:640px){.clip{grid-template-columns:1fr}}
video{width:100%;border-radius:10px;background:#000;aspect-ratio:9/16}
.hook{color:var(--accent);font-weight:800;text-transform:uppercase}.score{color:var(--muted);font-size:14px}
.cap{background:#0e0e10;border:1px solid var(--line);border-radius:8px;padding:10px;white-space:pre-wrap;font-size:14px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.err{color:#ff6b6b}
"""


def page(body: str, refresh: bool = False) -> str:
    meta = '<meta http-equiv="refresh" content="4">' if refresh else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1">{meta}<title>Whop Clipper</title>'
            f"<style>{STYLE}</style></head><body><main>{body}</main>"
            "<script>document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{"
            "navigator.clipboard.writeText(document.getElementById(b.dataset.copy).innerText);"
            "b.innerText='Copied';setTimeout(()=>b.innerText='Copy caption',1500)})</script></body></html>")


@app.get("/")
def index():
    hf = "" if higgsfield.enabled() else " <small>(add Higgsfield API keys to enable)</small>"
    recent = "".join(
        f'<li><a href="{url_for("job", job_id=j)}" style="color:var(--accent)">{html.escape(d["title"])}</a> '
        f'<small>{d["status"]}</small></li>'
        for j, d in sorted(JOBS.items(), key=lambda kv: -kv[1]["created"])
    )
    return page(f"""
<h1>Whop Clipper</h1>
<p class="sub">Paste a campaign and the stream. Claude reads the rules, finds the best moments and cuts
vertical clips with captions, ready to post.</p>
<form method="post" action="/run">
  <label>Whop campaign link</label>
  <input name="whop" placeholder="https://whop.com/...">
  <label>Campaign rules <small>(paste them here too: Whop pages often need a login)</small></label>
  <textarea name="rules" placeholder="Required hashtags, @mentions, length, what's banned..."></textarea>
  <label>Stream / VOD / clip links <small>(one per line: YouTube, Twitch, Kick, Drive, or a local file path)</small></label>
  <textarea name="sources" placeholder="https://www.twitch.tv/videos/..."></textarea>
  <div class="row">
    <div><label>How many clips</label><input name="clips" type="number" value="5" min="1" max="30"></div>
    <div><label>Only this part <small>(long VODs)</small></label><input name="section" placeholder="1:00:00-1:45:00"></div>
  </div>
  <label class="check"><input type="checkbox" name="ai_intro"> Add Higgsfield AI intro shot when the campaign allows it{hf}</label>
  <button type="submit">Make clips</button>
</form>
{"<h2>Jobs</h2><ul>" + recent + "</ul>" if recent else ""}
""")


@app.post("/run")
def start():
    f = request.form
    sources = [s.strip() for s in f.get("sources", "").splitlines() if s.strip()]
    job_id = uuid.uuid4().hex[:8]
    job_dir = OUTPUT_ROOT / f"{time.strftime('%Y%m%d-%H%M%S')}-{job_id}"
    job = {"status": "running", "log": [], "results": [], "dir": job_dir, "created": time.time(),
           "title": f.get("whop") or (sources[0] if sources else "job")}
    JOBS[job_id] = job

    def log(msg: str) -> None:
        job["log"].append(f"{time.strftime('%H:%M:%S')}  {msg}")

    def work() -> None:
        try:
            job["results"] = run_job(
                whop_url=f.get("whop", "").strip(), source_urls=sources, rules=f.get("rules", ""),
                n_clips=int(f.get("clips") or 5), section=f.get("section", "").strip(),
                ai_intro=bool(f.get("ai_intro")), job_dir=job_dir, log=log)
            job["status"] = "done"
        except Exception as e:
            log(f"ERROR: {e}")
            traceback.print_exc()
            job["status"] = "failed"

    threading.Thread(target=work, daemon=True).start()
    return redirect(url_for("job", job_id=job_id))


@app.get("/job/<job_id>")
def job(job_id: str):
    j = JOBS.get(job_id) or abort(404)
    clips = ""
    for i, c in enumerate(j["results"]):
        main_file = c["with_intro"] or c["file"]
        src = url_for("files", job_id=job_id, name=main_file)
        alt = (f'<a class="btn ghost" href="{url_for("files", job_id=job_id, name=c["file"])}" download>'
               "Download (no intro)</a>") if c["with_intro"] else ""
        clips += f"""
<div class="clip">
  <video src="{src}" controls preload="metadata"></video>
  <div>
    <div class="hook">{html.escape(c["hook_text"])}</div>
    <h3 style="margin:6px 0">{html.escape(c["title"])}</h3>
    <div class="score">Virality {c["virality_score"]}/10 · {c["start"]}s–{c["end"]}s · {html.escape(c["why_it_will_hit"])}</div>
    <p class="cap" id="cap{i}">{html.escape(c["caption"])}</p>
    <div class="actions">
      <a class="btn ghost" href="{src}" download>Download</a>{alt}
      <button class="btn ghost" data-copy="cap{i}" type="button">Copy caption</button>
    </div>
  </div>
</div>"""
    status = {"running": "Working on it…", "done": "Done. Post these, then submit the post links on Whop.",
              "failed": '<span class="err">Failed (see log)</span>'}[j["status"]]
    return page(f"""
<a href="/" style="color:var(--muted)">← New job</a>
<h1>{status}</h1>
<pre>{html.escape(chr(10).join(j["log"]) or "Starting...")}</pre>
{clips}""", refresh=j["status"] == "running")


@app.get("/files/<job_id>/<path:name>")
def files(job_id: str, name: str):
    j = JOBS.get(job_id) or abort(404)
    return send_from_directory(Path(j["dir"]), name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

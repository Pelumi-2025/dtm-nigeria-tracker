"""Local / hosted server for the DTM Nigeria report tracker.

  python server.py            -> http://localhost:8050

Serves the dashboard, the harvested data, a background harvest job and an AI
assistant. The assistant needs an Anthropic API key in the environment:
  ANTHROPIC_API_KEY=sk-ant-...   (optional: ANTHROPIC_MODEL=claude-sonnet-5)
Without a key the dashboard's assistant falls back to its built-in offline
command parser, so everything else keeps working.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from dtm.crawler import DATA, Crawler

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)

JOB = {"running": False, "log": [], "started": None, "finished": None, "keywords": [], "error": None}
STOP = threading.Event()


def load_reports() -> dict:
    p = DATA / "reports.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {"reports": [], "count": 0}


# ---- static -------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(ROOT / "dashboard", "index.html")


@app.get("/<path:name>")
def static_files(name):
    if name.startswith("data/"):
        return send_from_directory(DATA, name[5:], max_age=0)
    return send_from_directory(ROOT / "dashboard", name)


# ---- harvest job -----------------------------------------------------------
def _log(msg: str):
    JOB["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")
    JOB["log"] = JOB["log"][-300:]
    print(msg, flush=True)


def start_harvest(keywords: list[str] | None, refresh: bool = False) -> bool:
    if JOB["running"]:
        return False
    STOP.clear()
    JOB.update(running=True, log=[], started=time.time(), finished=None,
               keywords=keywords or [], error=None)

    def work():
        try:
            Crawler(log=_log, stop_event=STOP).run(keywords=keywords, refresh=refresh)
        except Exception as e:  # surface failure in the dashboard
            JOB["error"] = f"{e.__class__.__name__}: {e}"
            _log("Harvest failed: " + JOB["error"])
        finally:
            JOB.update(running=False, finished=time.time())

    threading.Thread(target=work, daemon=True).start()
    return True


@app.post("/api/harvest")
def api_harvest():
    body = request.get_json(silent=True) or {}
    kws = body.get("keywords")
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.split(",") if k.strip()]
    ok = start_harvest(kws or None, bool(body.get("refresh")))
    return jsonify({"started": ok, "status": JOB}), (202 if ok else 409)


@app.post("/api/harvest/stop")
def api_stop():
    STOP.set()
    return jsonify({"stopping": True})


@app.get("/api/status")
def api_status():
    d = load_reports()
    return jsonify({"job": JOB, "count": d.get("count", 0), "generated_at": d.get("generated_at"),
                    "ai": bool(os.environ.get("ANTHROPIC_API_KEY"))})


# ---- query helpers shared by the assistant ---------------------------------
def filter_reports(reports, f: dict):
    comps = set(f.get("components") or [])
    years = set(int(y) for y in (f.get("years") or []))
    regions = set(f.get("regions") or [])
    states = set(f.get("states") or [])
    months = set(int(m) for m in (f.get("months") or []))
    kw = (f.get("keyword") or "").lower()
    out = []
    for r in reports:
        if comps and r["component_key"] not in comps and r["component"] not in comps:
            continue
        if years and r.get("year") not in years:
            continue
        if months and not (r.get("date") and int(r["date"][5:7]) in months):
            continue
        if regions and not regions & set(r.get("regions") or []):
            continue
        if states and not states & set(r.get("states") or []):
            continue
        if kw and kw not in (r["title"] + " " + (r.get("summary") or "")).lower():
            continue
        out.append(r)
    return out


def count_by(reports, group_by: str | None):
    if not group_by or group_by == "none":
        return {"total": len(reports)}
    c = Counter()
    for r in reports:
        mo = MONTHS[int(r["date"][5:7]) - 1] if r.get("date") else "(no month)"
        vals = {"month": [mo], "year": [r.get("year")], "component": [r["component"]],
                "region": r.get("regions") or ["(none)"], "state": r.get("states") or ["(none)"]}[group_by]
        for v in vals:
            c[str(v)] += 1
    return {"total": len(reports), "by_" + group_by: dict(sorted(c.items()))}


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FILTER_SCHEMA = {
    "months": {"type": "array", "items": {"type": "integer"}, "description": "calendar months 1-12"},
    "components": {"type": "array", "items": {"type": "string"},
                   "description": "component keys: atlas, needs, flash, ett, intention, ses, smi, transhumance, ewer, flood, biometric, ses_fm, other"},
    "years": {"type": "array", "items": {"type": "integer"}},
    "regions": {"type": "array", "items": {"type": "string", "enum": ["North East", "North Central", "North West"]}},
    "states": {"type": "array", "items": {"type": "string"}},
    "keyword": {"type": "string", "description": "free-text match on title/summary"},
}
TOOLS = [
    {"name": "count_reports", "description": "Count harvested DTM Nigeria reports matching filters, optionally grouped.",
     "input_schema": {"type": "object", "properties": {**FILTER_SCHEMA, "group_by": {
         "type": "string", "enum": ["none", "year", "month", "component", "region", "state"]}}}},
    {"name": "list_reports", "description": "List matching reports (title, date, url), newest first.",
     "input_schema": {"type": "object", "properties": {**FILTER_SCHEMA, "limit": {"type": "integer"}}}},
    {"name": "set_dashboard_filters", "description": "Change the filters shown on the user's dashboard.",
     "input_schema": {"type": "object", "properties": {**FILTER_SCHEMA, "year_from": {"type": "integer"},
                                                       "year_to": {"type": "integer"}}}},
    {"name": "start_harvest", "description": "Start a new crawl of dtm.iom.int for Nigeria reports, searching the given keywords/terminologies in addition to the standard listings. Runs in the background for several minutes.",
     "input_schema": {"type": "object", "properties": {"keywords": {"type": "array", "items": {"type": "string"}},
                                                       "refresh": {"type": "boolean"}}}},
    {"name": "harvest_status", "description": "Check whether a harvest is running and see its latest log lines.",
     "input_schema": {"type": "object", "properties": {}}},
]


def run_tool(name, args, actions):
    reports = load_reports().get("reports", [])
    if name == "count_reports":
        return count_by(filter_reports(reports, args), args.get("group_by"))
    if name == "list_reports":
        rs = filter_reports(reports, args)[: min(int(args.get("limit") or 15), 50)]
        return [{"title": r["title"], "date": r.get("date"), "component": r["component"], "url": r["url"]} for r in rs]
    if name == "set_dashboard_filters":
        actions.append({"type": "set_filters", "filters": args})
        return {"ok": True}
    if name == "start_harvest":
        ok = start_harvest(args.get("keywords") or None, bool(args.get("refresh")))
        actions.append({"type": "harvest_started" if ok else "harvest_busy"})
        return {"started": ok}
    if name == "harvest_status":
        return {"running": JOB["running"], "log_tail": JOB["log"][-8:], "error": JOB["error"]}
    return {"error": "unknown tool"}


SYSTEM = """You are the assistant inside the IOM DTM Nigeria report-tracker dashboard.
The data is a harvest of reports published on https://dtm.iom.int/nigeria, classified by
component, geopolitical zone (North East, North Central, North West) and state, with a
publication year. Use the tools to answer with exact counts; never guess numbers. When the
user asks to "show" or "filter", call set_dashboard_filters. When they ask you to fetch,
update, crawl or search the website for keywords, call start_harvest. Keep answers short,
give numbers plainly, and say which filters you applied. Data harvested at: {gen}."""


@app.post("/api/chat")
def api_chat():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return jsonify({"error": "no_api_key"}), 503
    import anthropic

    body = request.get_json(silent=True) or {}
    msgs = [{"role": m["role"], "content": m["content"]} for m in body.get("messages", [])][-16:]
    client = anthropic.Anthropic(api_key=key)
    actions, gen = [], load_reports().get("generated_at", "unknown")
    for _ in range(6):
        resp = client.messages.create(model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
                                      max_tokens=1200, system=SYSTEM.format(gen=gen),
                                      tools=TOOLS, messages=msgs)
        msgs.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            text = "".join(b.text for b in resp.content if b.type == "text")
            return jsonify({"reply": text, "actions": actions})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": u.id,
             "content": json.dumps(run_tool(u.name, u.input, actions), default=str)[:20000]}
            for u in uses]})
    return jsonify({"reply": "I stopped after several tool steps. Try a narrower question.", "actions": actions})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"DTM Nigeria report tracker on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

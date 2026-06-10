#!/usr/bin/env python3
"""
Newsletter AI Agent — Web Interface
Run: python3 app.py  →  open http://localhost:5050
"""
import os
import sys
import json
import time
import uuid
import queue
import threading

from flask import Flask, render_template, request, Response, jsonify, send_from_directory

from newsletter_agent import usage_logger

app = Flask(__name__)
# Use /tmp on cloud (Railway), local demo_output when running on Mac
OUTPUT_DIR = "/tmp/newsletter_output" if os.getenv("RAILWAY_ENVIRONMENT") else os.path.join(os.path.dirname(__file__), "demo_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# One global run at a time — good enough for a demo
_run_queue: queue.Queue = queue.Queue()
_run_lock = threading.Lock()


class _StreamWriter:
    """Redirect stdout → SSE queue so every pipeline print() streams to browser."""
    def __init__(self, q: queue.Queue, original):
        self._q = q
        self._orig = original

    def write(self, text: str):
        self._orig.write(text)
        stripped = text.rstrip()
        if stripped:
            self._q.put({"type": "log", "text": stripped})

    def flush(self):
        self._orig.flush()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def start_run():
    data  = request.json or {}
    brief = data.get("brief", "").strip()
    if not brief:
        return jsonify({"error": "Brief is required"}), 400
    start_date  = data.get("start_date", "")
    end_date    = data.get("end_date", "")
    period_days = data.get("period_days", None)
    viz_hint    = data.get("viz_hint", None)

    # Session ID from cookie or generate a new one
    session_id = request.cookies.get("session_id") or str(uuid.uuid4())

    if not _run_lock.acquire(blocking=False):
        return jsonify({"error": "A run is already in progress"}), 429

    # Drain any stale messages
    while not _run_queue.empty():
        try:
            _run_queue.get_nowait()
        except queue.Empty:
            break

    def do_run():
        orig = sys.stdout
        sys.stdout = _StreamWriter(_run_queue, orig)
        run_start = time.monotonic()
        run_error = None
        figures = []
        try:
            from newsletter_agent.pipeline import run
            packages = run(brief, output_dir=OUTPUT_DIR,
                           start_date=start_date, end_date=end_date,
                           period_days=period_days)
            figures = [
                {
                    "path":          os.path.basename(p["path"]),
                    "title":         p["metadata"]["title"],
                    "note":          p["metadata"]["note"],
                    "kilde":         p["metadata"]["kilde"],
                    "reviewer_flag": p["metadata"].get("reviewer_flag", ""),
                }
                for p in packages
            ]
            _run_queue.put({"type": "done", "figures": figures})
        except Exception as exc:
            run_error = str(exc)
            _run_queue.put({"type": "error", "text": run_error})
        finally:
            duration = time.monotonic() - run_start
            sys.stdout = orig
            _run_lock.release()

            # Log usage to Supabase (non-blocking, never crashes)
            usage_logger.log_run(
                prompt=brief,
                viz_hint=viz_hint,
                period_days=int(period_days) if period_days else None,
                start_date=start_date or None,
                end_date=end_date or None,
                figures=[
                    {
                        "title": f.get("title"),
                        "type": f.get("path", "").rsplit(".", 1)[-1] if f.get("path") else None,
                        "reviewer_flag": f.get("reviewer_flag"),
                        "data_sources": f.get("kilde"),
                    }
                    for f in figures
                ],
                duration_seconds=round(duration, 2),
                error=run_error,
                session_id=session_id,
            )

    threading.Thread(target=do_run, daemon=True).start()

    resp = jsonify({"status": "started"})
    resp.set_cookie("session_id", session_id, max_age=86400, httponly=True, samesite="Lax")
    return resp


@app.route("/stream")
def stream():
    def generate():
        yield "data: {\"type\":\"connected\"}\n\n"
        while True:
            try:
                msg = _run_queue.get(timeout=90)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                yield "data: {\"type\":\"heartbeat\"}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/figures/<filename>")
def serve_figure(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/download/excel")
def download_excel():
    path = os.path.join(OUTPUT_DIR, "data_export.xlsx")
    if os.path.isfile(path):
        return send_from_directory(OUTPUT_DIR, "data_export.xlsx",
                                   as_attachment=True,
                                   download_name="maj_invest_data.xlsx")
    return jsonify({"error": "Ingen dataeksport tilgængelig — kør en analyse først."}), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    print(f"Newsletter AI Agent — http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

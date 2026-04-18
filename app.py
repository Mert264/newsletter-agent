#!/usr/bin/env python3
"""
Newsletter AI Agent — Web Interface
Run: python3 app.py  →  open http://localhost:5050
"""
import os
import sys
import json
import queue
import threading

from flask import Flask, render_template, request, Response, jsonify, send_from_directory

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
    body = request.json or {}
    brief = body.get("brief", "").strip()
    preferred_types = body.get("preferred_types", None)  # e.g. ["A", "G"]
    if not brief:
        return jsonify({"error": "Brief is required"}), 400

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
        try:
            from newsletter_agent.pipeline import run
            packages = run(brief, output_dir=OUTPUT_DIR, preferred_types=preferred_types)

            # Load rerender context to attach to each figure
            import json as _json
            ctx_path = os.path.join(OUTPUT_DIR, "rerender_context.json")
            rerender_ctx = {}
            if os.path.exists(ctx_path):
                with open(ctx_path) as f:
                    for entry in _json.load(f):
                        rerender_ctx[entry["figure_id"]] = entry

            figures = [
                {
                    "path":          os.path.basename(p["path"]),
                    "title":         p["metadata"]["title"],
                    "note":          p["metadata"]["note"],
                    "kilde":         p["metadata"]["kilde"],
                    "reviewer_flag": p["metadata"].get("reviewer_flag", ""),
                    "chart_type":    p["metadata"].get("chart_type", "A"),
                    "figure_id":     i,
                    "rerender_ctx":  rerender_ctx.get(i, {}),
                }
                for i, p in enumerate(packages)
            ]
            _run_queue.put({"type": "done", "figures": figures})
        except Exception as exc:
            _run_queue.put({"type": "error", "text": str(exc)})
        finally:
            sys.stdout = orig
            _run_lock.release()

    threading.Thread(target=do_run, daemon=True).start()
    return jsonify({"status": "started"})


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


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    print(f"Newsletter AI Agent — http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

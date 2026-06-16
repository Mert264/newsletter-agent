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





@app.route("/health")
def health():
    return jsonify({"status": "ok"})

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
    start_date     = data.get("start_date", "")
    end_date       = data.get("end_date", "")
    period_days    = data.get("period_days", None)
    self_critique  = data.get("self_critique", False)

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
            packages = run(brief, output_dir=OUTPUT_DIR,
                           start_date=start_date, end_date=end_date,
                           period_days=period_days,
                           self_critique=bool(self_critique))
            figures = [
                {
                    "path":          os.path.basename(p["path"]),
                    "title":         p["metadata"]["title"],
                    "note":          p["metadata"]["note"],
                    "kilde":         p["metadata"]["kilde"],
                    "reviewer_flag": p["metadata"].get("reviewer_flag", ""),
                    "data_warning":  p["metadata"].get("data_warning", ""),
                    "chart_type":    p["metadata"].get("chart_type", ""),
                    "specialist":    p["metadata"].get("specialist", ""),
                }
                for p in packages
            ]
            _run_queue.put({"type": "done", "figures": figures, "brief": brief})
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


@app.route("/rate", methods=["POST"])
def rate_figure():
    data = request.json or {}
    figure_id = data.get("figure_id", "").strip()
    rating = data.get("rating")
    if not figure_id or rating not in (1, 2, 3, 4, 5):
        return jsonify({"error": "Invalid rating"}), 400
    import re
    figure_id = re.sub(r"[^a-zA-Z0-9_\-]", "", figure_id)[:120]
    if not figure_id:
        return jsonify({"error": "Invalid figure_id"}), 400
    comment = data.get("comment", "").strip()[:500]
    import datetime
    entry = {
        "figure_id": figure_id,
        "rating": rating,
        "comment": comment,
        "chart_type": data.get("chart_type", ""),
        "title": data.get("title", ""),
        "specialist": data.get("specialist", ""),
        "brief": data.get("brief", ""),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    ratings_path = os.path.join(OUTPUT_DIR, "ratings.jsonl")
    with open(ratings_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if comment:
        from newsletter_agent.corrections_store import save_correction
        save_correction({
            "figure": figure_id,
            "specialist": entry.get("specialist", ""),
            "chart_type": entry.get("chart_type", ""),
            "comment": comment,
            "title": entry.get("title", ""),
            "brief": entry.get("brief", ""),
            "figure_type": entry.get("chart_type", ""),
            "source": "user",
        })
    return jsonify({"status": "saved"})


@app.route("/ratings")
def get_ratings():
    ratings_path = os.path.join(OUTPUT_DIR, "ratings.jsonl")
    if not os.path.isfile(ratings_path):
        return jsonify({"ratings": [], "summary": {}})
    entries = []
    with open(ratings_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    if not entries:
        return jsonify({"ratings": entries, "summary": {}})
    total = len(entries)
    avg = sum(e["rating"] for e in entries) / total
    dist = {str(i): sum(1 for e in entries if e["rating"] == i) for i in range(1, 6)}
    return jsonify({
        "ratings": entries[-50:],
        "summary": {"total": total, "average": round(avg, 2), "distribution": dist},
    })


@app.route("/corrections")
def get_corrections():
    from newsletter_agent.corrections_store import list_all_corrections
    entries = list_all_corrections(limit=100, output_dir=OUTPUT_DIR)
    active = [e for e in entries if e.get("status", "active") == "active"]
    return jsonify({"corrections": entries, "count": len(entries), "active_count": len(active)})


@app.route("/corrections/toggle", methods=["POST"])
def toggle_correction():
    data = request.json or {}
    cid = data.get("id", "").strip()
    new_status = data.get("status", "").strip()
    if not cid or new_status not in ("active", "disabled"):
        return jsonify({"error": "Invalid id or status"}), 400
    from newsletter_agent.corrections_store import toggle_correction as _toggle
    ok = _toggle(cid, new_status)
    return jsonify({"status": "toggled" if ok else "not_found"})


@app.route("/dashboard")
def serve_dashboard():
    path = os.path.join(OUTPUT_DIR, "dashboard.png")
    if os.path.isfile(path):
        return send_from_directory(OUTPUT_DIR, "dashboard.png")
    return jsonify({"error": "Intet dashboard tilgængeligt — kør en analyse først."}), 404


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

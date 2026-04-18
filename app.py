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


@app.route("/rerender", methods=["POST"])
def rerender_figure():
    """
    Re-render a single figure with a different chart type.
    Accepts JSON: {figure_id, chart_type, specialist, series_specs, chart_spec}
    Returns JSON: {path, title, note} or {error}.
    """
    data = request.json or {}
    figure_id    = data.get("figure_id", 0)
    chart_type   = data.get("chart_type", "A")
    specialist   = data.get("specialist")
    series_specs = data.get("series_specs", [])
    chart_spec   = data.get("chart_spec", {})

    if not specialist:
        return jsonify({"error": "specialist is required"}), 400

    # Override chart type in spec
    chart_spec = {**chart_spec, "type": chart_type}

    try:
        from newsletter_agent.pipeline import SPECIALIST_MAP, _render_figure
        from newsletter_agent.processors.converters import apply_conversions
        import os as _os

        # Build mini task for this specialist
        mini_task = {"series": series_specs, "charts": [chart_spec]}

        # Re-fetch data
        if specialist not in SPECIALIST_MAP:
            return jsonify({"error": f"Unknown specialist: {specialist}"}), 400
        result = SPECIALIST_MAP[specialist](mini_task)
        result["chart_specs"] = [chart_spec]

        # Apply conversions
        period_days = chart_spec.get("period_days", 730)
        converted_dfs, conv_note = apply_conversions(result["dataframes"], series_specs, period_days)
        result["dataframes"] = converted_dfs
        if conv_note:
            existing = chart_spec.get("note", "").rstrip(". ")
            chart_spec = {**chart_spec, "note": f"{existing} {conv_note}".strip()}
            result["chart_specs"] = [chart_spec]

        # Render to same output path as original (overwrites)
        output_path = _os.path.join(OUTPUT_DIR, f"figure_{figure_id:02d}.png")
        package = _render_figure(chart_spec, result, output_path)

        if package is None:
            return jsonify({"error": "No renderable data for this chart type"}), 422

        return jsonify({
            "path":  _os.path.basename(package["path"]),
            "title": package["metadata"]["title"],
            "note":  package["metadata"]["note"],
        })

    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "detail": traceback.format_exc()}), 500


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

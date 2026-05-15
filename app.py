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
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-do-not-use-in-prod")

# Use /tmp on cloud (Railway), local demo_output when running on Mac
OUTPUT_DIR = "/tmp/newsletter_output" if os.getenv("RAILWAY_ENVIRONMENT") else os.path.join(os.path.dirname(__file__), "demo_output")

# ── Auth ──────────────────────────────────────────────────────────────────────
_APP_PASSWORD = os.getenv("APP_PASSWORD", "")  # set in Railway env vars to lock the site

from flask import session, redirect, url_for

@app.before_request
def require_auth():
    if not _APP_PASSWORD:
        return  # no password set → open access (local dev)
    if request.path in ("/login", "/logout") or request.path.startswith("/static"):
        return
    if not session.get("authenticated"):
        if request.path == "/" or not request.path.startswith("/"):
            return redirect(url_for("login"))
        return jsonify({"error": "Unauthorized"}), 401

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        pw = (request.form or {}).get("password", "")
        if pw == _APP_PASSWORD:
            session["authenticated"] = True
            return redirect("/")
        error = "Forkert adgangskode."
    return f"""<!doctype html><html><head><title>Log ind</title>
<style>body{{font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f4f6f8}}
.box{{background:#fff;border-radius:10px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,.1);width:320px}}
h2{{color:#11716c;margin-top:0}}input{{width:100%;padding:10px;border:1.5px solid #d1d5db;border-radius:6px;font-size:14px;box-sizing:border-box;margin-top:8px}}
button{{width:100%;padding:10px;background:#11716c;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;margin-top:16px}}
.err{{color:#dc2626;font-size:13px;margin-top:8px}}</style></head>
<body><div class="box"><h2>Newsletter AI Agent</h2>
<form method="post"><label>Adgangskode<input type="password" name="password" autofocus/></label>
<button type="submit">Log ind</button></form>
<div class="err">{error}</div></div></body></html>"""

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# One global run at a time — good enough for a demo
_run_queue: queue.Queue = queue.Queue()
_run_lock = threading.Lock()
_last_result: dict = {}        # persists last done/error so reload can recover it
_LAST_RESULT_PATH = os.path.join(OUTPUT_DIR, "_last_result.json")


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
    brief        = body.get("brief", "").strip()
    preferred_types = body.get("preferred_types", None)
    period_days  = body.get("period_days", None)
    start_date   = body.get("start_date", None) or None
    end_date     = body.get("end_date", None) or None
    if not brief:
        return jsonify({"error": "Brief is required"}), 400

    if not _run_lock.acquire(blocking=False):
        return jsonify({"error": "A run is already in progress"}), 429

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
            from datetime import datetime

            run_dir = os.path.join(OUTPUT_DIR, datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(run_dir, exist_ok=True)
            packages, specialist_errors, excel_path = run(
                brief,
                output_dir=run_dir,
                preferred_types=preferred_types,
                period_days=period_days,
                start_date=start_date,
                end_date=end_date,
            )
            ctx_path = os.path.join(run_dir, "rerender_context.json")
            rerender_ctx = {}
            if os.path.exists(ctx_path):
                with open(ctx_path) as f:
                    for entry in json.load(f):
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
                    "excel_path":    p["metadata"].get("excel_path", ""),
                }
                for i, p in enumerate(packages)
            ]

            done_msg = {
                "type":              "done",
                "figures":           figures,
                "specialist_errors": specialist_errors,
                "excel_available":   bool(excel_path),
            }
            _last_result.update(done_msg)
            with open(_LAST_RESULT_PATH, "w") as _f:
                json.dump(done_msg, _f, ensure_ascii=False)
            _run_queue.put(done_msg)

        except Exception as exc:
            import traceback
            err_msg = {"type": "error", "text": str(exc)}
            _last_result.update(err_msg)
            _run_queue.put(err_msg)
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

        # Render into the latest run dir so it's served by /figures correctly
        import glob as _glob2
        _run_dirs = sorted(_glob2.glob(_os.path.join(OUTPUT_DIR, "2*")), reverse=True)
        _active_dir = _run_dirs[0] if _run_dirs else OUTPUT_DIR
        output_path = _os.path.join(_active_dir, f"figure_{figure_id:02d}.png")
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


@app.route("/last")
def last_result():
    """Return the most recent completed run so the browser can restore figures after a reload."""
    if os.path.exists(_LAST_RESULT_PATH):
        with open(_LAST_RESULT_PATH) as f:
            return jsonify(json.load(f))
    return jsonify({"type": "none"})


@app.route("/figures/<filename>")
def serve_figure(filename):
    import glob as _glob
    run_dirs = sorted(_glob.glob(os.path.join(OUTPUT_DIR, "2*")), reverse=True)
    for d in run_dirs:
        if os.path.exists(os.path.join(d, filename)):
            return send_from_directory(d, filename)
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/download/excel/<filename>")
def download_excel(filename):
    """Serve a per-figure Excel file by name."""
    import glob as _glob
    run_dirs = sorted(_glob.glob(os.path.join(OUTPUT_DIR, "2*")), reverse=True)
    for d in run_dirs:
        candidate = os.path.join(d, filename)
        if os.path.exists(candidate):
            return send_from_directory(d, filename, as_attachment=True,
                                       download_name=filename)
    return jsonify({"error": "Fil ikke fundet."}), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    print(f"Newsletter AI Agent — http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

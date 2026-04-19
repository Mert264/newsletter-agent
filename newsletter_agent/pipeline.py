# newsletter_agent/pipeline.py
"""Main pipeline orchestration: brief → manifest → specialists (parallel) → normalize → render → review → output."""
import os
import json
import pandas as pd
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from newsletter_agent.orchestrator import build_task_manifest
from newsletter_agent.specialists.energy import fetch_energy
from newsletter_agent.specialists.rates import fetch_rates
from newsletter_agent.specialists.macro import fetch_macro
from newsletter_agent.specialists.commodities import fetch_commodities
from newsletter_agent.specialists.equities import fetch_equities
from newsletter_agent.specialists.eurostat import fetch_eurostat
from newsletter_agent.processors.normalize import drop_nulls, align_dates, index_to_100, compute_yoy
from newsletter_agent.processors.converters import apply_conversions
from newsletter_agent.routing import get_routing_hint
from newsletter_agent.renderers.charts import render_type_a, render_type_b, render_type_c, render_type_e, render_type_f, render_type_g, render_type_p
from newsletter_agent.renderers.tables import render_type_d
from newsletter_agent.reviewer import review_figure

SPECIALIST_MAP = {
    "energy":      fetch_energy,
    "rates":       fetch_rates,
    "macro":       fetch_macro,
    "commodities": fetch_commodities,
    "equities":    fetch_equities,
    "eurostat":    fetch_eurostat,
}

CHART_RENDERER_MAP = {
    "A": render_type_a,
    "B": render_type_b,
    "C": render_type_c,
    "E": render_type_e,
    "F": render_type_f,
    "G": render_type_g,
    "P": render_type_p,
}


def _snapshot_value(series: pd.Series, date_str: str) -> float:
    """Return the series value closest to date_str ('latest' → last observation)."""
    if not date_str or date_str == "latest":
        return float(series.dropna().iloc[-1])
    ts = pd.Timestamp(date_str)
    idx = series.dropna().index.get_indexer([ts], method="nearest")[0]
    return float(series.dropna().iloc[idx])


def _fmt(val: float) -> str:
    """Format a number for table display."""
    if abs(val) >= 1000:
        return f"{val:,.0f}"
    if abs(val) >= 10:
        return f"{val:.2f}"
    if abs(val) >= 0.1:
        return f"{val:.3f}"
    return f"{val:.4f}"


def _build_table(dfs: dict, chart_spec: dict, kilde_str: str, output_path: str) -> str:
    """Build and render a Type D snapshot/before-after table from real series data."""
    before_date = chart_spec.get("before_date", "")
    after_date  = chart_spec.get("after_date", "latest")
    col_before  = chart_spec.get("col_before", "Før")
    col_after   = chart_spec.get("col_after", "Nu")

    # Use absolute pp change for rate/yield series (y_label="%"), relative % otherwise
    y_label = chart_spec.get("y_label", "")
    use_absolute = y_label.strip() in ("%", "pp", "PP", "Percentage points", "Basis points (bps)")

    rows = []
    for label, df in dfs.items():
        series = df.iloc[:, 0].dropna()
        if series.empty:
            continue
        try:
            after_val  = _snapshot_value(series, after_date)
            before_val = _snapshot_value(series, before_date) if before_date else float(series.iloc[0])
            change     = after_val - before_val
            sign       = "+" if change >= 0 else ""
            if use_absolute:
                change_str = f"{sign}{change:.2f} pp"
            else:
                pct = (change / abs(before_val) * 100) if before_val != 0 else 0.0
                change_str = f"{sign}{pct:.1f}%"
            rows.append({
                "indicator": label,
                col_before:  _fmt(before_val),
                col_after:   _fmt(after_val),
                "Ændring":   change_str,
            })
        except Exception as e:
            print(f"    [warn] Could not build table row for '{label}': {e}")

    data = {"columns": [col_before, col_after, "Ændring"], "rows": rows}
    # Pass spec without note — tables don't show Note text, only Kilde
    table_spec = {**chart_spec, "kilde": kilde_str, "note": ""}
    return render_type_d(data, table_spec, output_path)


def _build_before_after_bars(dfs: dict, chart_spec: dict, kilde_str: str, output_path: str) -> str:
    """Build and render a Type E before/after grouped bar chart from real series data."""
    before_date = chart_spec.get("before_date", "")
    after_date  = chart_spec.get("after_date", "latest")
    col_before  = chart_spec.get("col_before", "Før")
    col_after   = chart_spec.get("col_after", "Nu")

    before_vals, after_vals = {}, {}
    for label, df in dfs.items():
        series = df.iloc[:, 0].dropna()
        if series.empty:
            continue
        try:
            after_vals[label]  = _snapshot_value(series, after_date)
            before_vals[label] = _snapshot_value(series, before_date) if before_date else float(series.iloc[0])
        except Exception as e:
            print(f"    [warn] Could not build bar for '{label}': {e}")

    if not before_vals:
        print(f"    [warn] No data for Type E chart '{chart_spec.get('title')}' — skipping.")
        return output_path

    snapshot_df = pd.DataFrame({col_before: before_vals, col_after: after_vals})

    # If units differ wildly, show % change from before instead of absolute values
    ranges = snapshot_df.max() - snapshot_df.min()
    if len(snapshot_df) > 1:
        row_ranges = [abs(snapshot_df.loc[i, col_after] - snapshot_df.loc[i, col_before])
                      for i in snapshot_df.index]
        abs_vals   = [abs(snapshot_df.loc[i, col_before]) for i in snapshot_df.index]
        if abs_vals and max(abs_vals) / (min(abs_vals) + 1e-9) > 10:
            # Switch to % change bars (single column, positive/negative)
            pct_changes = {
                lbl: (after_vals[lbl] - before_vals[lbl]) / abs(before_vals[lbl]) * 100
                for lbl in before_vals
            }
            snapshot_df = pd.DataFrame({"% endring": pct_changes})
            chart_spec  = {**chart_spec, "y_label": "% ændring"}

    return render_type_e(snapshot_df, {**chart_spec, "kilde": kilde_str}, output_path)


def _build_event_impact_table(merged: pd.DataFrame, events: list,
                               chart_spec: dict, kilde_str: str,
                               output_path: str):
    """
    Build a companion impact table for any Type A chart that has events.
    For each event date, compute % change vs day-before for each series
    at T+7 and T+30 days. Returns a FigurePackage dict or None if no data.
    """
    if not events or merged is None or merged.empty:
        return None

    rows = []
    for ev in events:
        try:
            ev_date = pd.Timestamp(ev["date"])
        except Exception:
            continue
        label = ev.get("label", str(ev["date"]))

        # Find the last available observation strictly before the event date
        before_idx = merged.index[merged.index < ev_date]
        if before_idx.empty:
            continue
        t0 = before_idx[-1]

        # Use absolute pp change for rate/yield series (y_label="%"), relative % for everything else
        y_label = chart_spec.get("y_label", "")
        use_absolute = y_label.strip() in ("%", "pp", "PP", "Percentage points", "Basis points (bps)")

        for col in merged.columns:
            s = merged[col].dropna()
            if s.empty or t0 not in s.index:
                continue
            base_val = s.loc[t0]
            if base_val == 0 and not use_absolute:
                continue

            def _change(target_date, _base=base_val, _s=s, _abs=use_absolute):
                future = _s[_s.index >= target_date]
                if future.empty:
                    return "n/a"
                val = future.iloc[0]
                if _abs:
                    diff = val - _base
                    sign = "+" if diff >= 0 else ""
                    return f"{sign}{diff:.2f} pp"
                else:
                    if _base == 0:
                        return "n/a"
                    change = (val - _base) / abs(_base) * 100
                    sign = "+" if change >= 0 else ""
                    return f"{sign}{change:.1f}%"

            rows.append({
                "indicator": f"{col}",
                "Event":     label,
                "+7 days":   _change(ev_date + pd.Timedelta(days=7)),
                "+30 days":  _change(ev_date + pd.Timedelta(days=30)),
            })

    if not rows:
        return None

    # Group rows so events appear as visual sections in the table
    # Sort by event label so all rows for same event are together
    rows.sort(key=lambda r: r["Event"])

    # Build the data format render_type_d expects
    table_rows = []
    prev_event = None
    for r in rows:
        ev_label = r["Event"]
        if ev_label != prev_event:
            # Insert a section header row (blank values, teal background via indicator hack)
            table_rows.append({
                "indicator": f"— {ev_label} —",
                "+7 days": "",
                "+30 days": "",
            })
            prev_event = ev_label
        table_rows.append({
            "indicator": r["indicator"],
            "+7 days":   r["+7 days"],
            "+30 days":  r["+30 days"],
        })

    data = {"columns": ["+7 days", "+30 days"], "rows": table_rows}
    title = chart_spec.get("title", "")
    impact_spec = {
        "title": f"Event impact — {title}",
        "note":  "",
        "kilde": kilde_str,
    }
    from newsletter_agent.renderers.tables import render_type_d
    path = render_type_d(data, impact_spec, output_path)
    metadata = {
        "title":         impact_spec["title"],
        "chart_type":    "D",
        "x_label":       "",
        "y_label":       "",
        "note":          impact_spec["note"],
        "kilde":         kilde_str,
        "region_labels": [],
    }
    print(f"    [events] Impact table rendered: '{impact_spec['title']}'")
    return {"path": path, "metadata": metadata}


def _render_figure(chart_spec: dict, specialist_result: dict, output_path: str) -> dict:
    """Render one figure from chart_spec + specialist data. Returns FigurePackage dict."""
    chart_type = chart_spec["type"]
    dfs = specialist_result["dataframes"]
    kilde_str = " og ".join(specialist_result["kilde"])

    # ── Filter to series for this chart ──────────────────────────────────────
    series_labels = chart_spec.get("series_labels")
    if series_labels:
        dfs = {k: v for k, v in dfs.items() if k in series_labels}

    render_spec = {**chart_spec, "kilde": kilde_str}
    # Append any unit conversion note to the chart's note field
    conv_note = specialist_result.get("conversion_note", "")
    if conv_note:
        existing_note = render_spec.get("note", "").rstrip(". ")
        render_spec = {**render_spec, "note": f"{existing_note} {conv_note}".strip()}
        # If conversions harmonised units but LLM still wrote "Indekseret/Indexed" as y_label,
        # override it with "USD/MWh" — the conversion guarantees this is now the correct unit.
        cur_ylabel = render_spec.get("y_label", "")
        if "indekseret" in cur_ylabel.lower() or "indexed" in cur_ylabel.lower() or "basis=100" in cur_ylabel.lower():
            render_spec = {**render_spec, "y_label": "USD/MWh"}
            chart_spec  = {**chart_spec,  "y_label": "USD/MWh"}
    merged_for_events = None  # populated for Type A charts; used by event impact table

    # ── Type D — Snapshot / before-after table ────────────────────────────
    if chart_type == "D":
        path = _build_table(dfs, chart_spec, kilde_str, output_path)

    # ── Type E — Before/after grouped bar chart ───────────────────────────
    elif chart_type == "E":
        path = _build_before_after_bars(dfs, chart_spec, kilde_str, output_path)

    # ── Type F — 100% stacked bar (composition / energy mix) ─────────────
    elif chart_type == "F":
        # F expects a wide DataFrame: index=categories, columns=series labels
        # If specialist returns multiple single-column DFs, merge them wide.
        if len(dfs) == 1:
            wide = list(dfs.values())[0]
            if isinstance(wide.index, pd.DatetimeIndex):
                wide = wide.copy()
                wide.index = wide.index.year.astype(str)
        else:
            # Multiple series → each is a column; build wide from time snapshots
            parts = {}
            for lbl, df in dfs.items():
                s = df.iloc[:, 0].dropna()
                if isinstance(s.index, pd.DatetimeIndex):
                    s.index = s.index.year.astype(str)
                parts[lbl] = s
            wide = pd.DataFrame(parts).dropna(how="all").tail(10)
        if wide is None or wide.empty:
            print(f"    [warn] No data for Type F chart '{chart_spec.get('title')}' — skipping.")
            return None
        path = render_type_f(wide, render_spec, output_path)

    # ── Type G — Horizontal bar (entity/sector comparison) ────────────────
    elif chart_type == "G":
        if len(dfs) == 1:
            g_df = list(dfs.values())[0]
        else:
            # Multiple series → take latest value of each, build single-column DF
            latest = {lbl: float(df.iloc[:, 0].dropna().iloc[-1]) for lbl, df in dfs.items() if not df.empty}
            g_df = pd.DataFrame.from_dict(latest, orient="index", columns=[chart_spec.get("y_label", "%")])
        if g_df is None or g_df.empty:
            print(f"    [warn] No data for Type G chart '{chart_spec.get('title')}' — skipping.")
            return None
        path = render_type_g(g_df, render_spec, output_path)

    # ── Type P — Pie chart (composition snapshot) ─────────────────────────
    elif chart_type == "P":
        if len(dfs) == 1:
            wide = list(dfs.values())[0]
            if isinstance(wide.index, pd.DatetimeIndex):
                wide = wide.copy()
                wide.index = wide.index.year.astype(str)
        else:
            parts = {}
            for lbl, df in dfs.items():
                s = df.iloc[:, 0].dropna()
                if isinstance(s.index, pd.DatetimeIndex):
                    s.index = s.index.year.astype(str)
                parts[lbl] = s
            wide = pd.DataFrame(parts).dropna(how="all")
        if wide is None or wide.empty:
            print(f"    [warn] No data for Type P chart '{chart_spec.get('title')}' — skipping.")
            return None
        result_paths = render_type_p(wide, render_spec, output_path)

        # Multi-year: render_type_p returns a list [year1_path, ..., combined_path]
        if isinstance(result_paths, list):
            year_paths = result_paths[:-1]
            combined_path = result_paths[-1]
            years = [str(y) for y in wide.index.tolist()]
            years_shown = years[-len(year_paths):]
            pkgs = []
            for year, yp in zip(years_shown, year_paths):
                pkgs.append({
                    "path": yp,
                    "metadata": {
                        "title":         f"{chart_spec['title']} ({year})",
                        "chart_type":    "P",
                        "x_label":       "",
                        "y_label":       "",
                        "note":          "",
                        "kilde":         kilde_str,
                        "region_labels": list(dfs.keys()),
                    },
                })
            pkgs.append({
                "path": combined_path,
                "metadata": {
                    "title":         f"{chart_spec['title']} — Sammenligning",
                    "chart_type":    "P",
                    "x_label":       "",
                    "y_label":       "",
                    "note":          chart_spec.get("note", ""),
                    "kilde":         kilde_str,
                    "region_labels": list(dfs.keys()),
                },
            })
            return pkgs  # list of dicts — caller handles

        path = result_paths  # single-year: fall through to standard return

    # ── Types A / B / C — Time-series & bar charts ───────────────────────
    else:
        aligned = align_dates(dfs)
        merged = None
        for label, df in aligned.items():
            clean = drop_nulls(df)
            if merged is None:
                merged = clean
            else:
                # Outer join + forward-fill so Japanese/European holidays don't
                # punch holes in US series (and vice versa).
                merged = merged.join(clean, how="outer").ffill().dropna(how="all")

        if merged is None or merged.empty:
            print(f"    [warn] No data for chart '{chart_spec.get('title')}' — skipping (no data).")
            return None

        y_label = chart_spec.get("y_label", "")

        # Auto-apply YoY % transform ONLY when y_label explicitly says "YoY".
        if "yoy" in y_label.lower():
            cols_before = list(merged.columns)
            for col in cols_before:
                yoy = compute_yoy(merged, col)
                valid = yoy.dropna()
                if valid.empty:
                    print(f"    [warn] YoY transform for '{col}' produced no data "
                          f"(period too short — need period_days>=760 for monthly data). "
                          f"Dropping series from chart.")
                    merged = merged.drop(columns=[col])
                else:
                    merged = merged.drop(columns=[col]).join(yoy)
            merged = merged.dropna(how="all")

        # Honour explicit index_base_date from the orchestrator: trim data to start
        # from that date and rebase to 100 there (not at whatever first row exists).
        index_base_date = chart_spec.get("index_base_date")
        if index_base_date:
            try:
                base_ts = pd.Timestamp(index_base_date)
                # Find the nearest available trading day on or after base_ts
                future_idx = merged.index[merged.index >= base_ts]
                if not future_idx.empty:
                    nearest = future_idx[0]
                    merged = merged[merged.index >= nearest]
                    print(f"    [index] Trimmed to {nearest.date()} per index_base_date={index_base_date}")
                else:
                    print(f"    [warn] index_base_date {index_base_date} is after data end — ignoring")
                    index_base_date = None
            except Exception as e:
                print(f"    [warn] index_base_date parse failed: {e}")
                index_base_date = None

        # If unit conversions were applied, series are already harmonised — never index them.
        # Indexing would destroy the USD/MWh scale and contradict the chart title.
        conversions_applied = bool(specialist_result.get("conversion_note", ""))

        # Auto-apply indexing when y_label signals multi-unit comparison (Danish: "indekseret", English: "indexed")
        if not conversions_applied and (
            "base=100" in y_label.lower() or "basis=100" in y_label.lower()
            or "indexed" in y_label.lower() or "indekseret" in y_label.lower()
        ):
            base_date_ts = pd.Timestamp(index_base_date) if index_base_date else None
            if base_date_ts is not None and base_date_ts in merged.index:
                merged = index_to_100(merged, base_date=base_date_ts)
            else:
                merged = index_to_100(merged)

        # Safety net: if series have wildly incompatible scales (>10x range ratio),
        # auto-index even if y_label doesn't request it, to avoid invisible lines.
        # Skip when conversions were applied — the conversion already harmonised units.
        if not conversions_applied and len(merged.columns) > 1 and "yoy" not in y_label.lower():
            ranges = [merged[c].max() - merged[c].min() for c in merged.columns
                      if merged[c].notna().any()]
            if ranges and max(ranges) / (min(ranges) + 1e-9) > 10:
                merged = index_to_100(merged)
                chart_spec = {**chart_spec, "y_label": "Indekseret (basis=100)"}
                render_spec = {**chart_spec, "kilde": kilde_str}

        renderer = CHART_RENDERER_MAP[chart_type]
        path = renderer(merged, render_spec, output_path)

        if chart_type == "A":
            merged_for_events = merged

    metadata = {
        "title":         chart_spec["title"],
        "chart_type":    chart_spec.get("type", "?"),
        "x_label":       chart_spec.get("x_label", ""),
        "y_label":       chart_spec.get("y_label", ""),
        "note":          chart_spec.get("note", ""),
        "kilde":         kilde_str,
        "region_labels": list(dfs.keys()),
    }
    pkg = {"path": path, "metadata": metadata}
    if merged_for_events is not None:
        pkg["_merged"] = merged_for_events
    return pkg


def _run_specialist(name: str, task: dict) -> tuple[str, dict]:
    """Fetch data for one specialist. Returns (name, SpecialistResult)."""
    print(f"  [{name}] Fetching data...")
    fetch_fn = SPECIALIST_MAP[name]
    result = fetch_fn(task)
    n_series = len(result["dataframes"])
    print(f"  [{name}] Done — {n_series} series fetched.")
    return name, result


def run(brief: str, output_dir: str = "output", preferred_types: list = None, period_days: int = None) -> list:
    """
    Main pipeline entry point.
    brief: free-form topic string from department.
    output_dir: where to save PNG files and manifest.json.
    preferred_types: optional list of chart type codes e.g. ["A", "G"] — passed to orchestrator.
    Returns list of FigurePackage dicts: [{"path": str, "metadata": dict}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Orchestrate — 1 LLM call → TaskManifest
    print("\n[1/4] Orchestrating — asking Lead Agent to plan figures...")
    routing_hint = get_routing_hint(brief)
    if routing_hint:
        print(f"      [routing] Hint injected: {routing_hint.strip()[:80]}...")
    manifest = build_task_manifest(brief, preferred_types=preferred_types, routing_hint=routing_hint, period_days=period_days)
    specialists = manifest.get("specialists", [])
    print(f"      Specialists activated: {', '.join(specialists)}")

    # Step 2: Run all specialists in parallel
    print(f"\n[2/4] Fetching data ({len(specialists)} specialist(s) in parallel)...")
    specialist_results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(specialists) or 1) as executor:
        futures = {
            executor.submit(_run_specialist, name, manifest[name]): name
            for name in specialists
        }
        for future in as_completed(futures):
            name, result = future.result()
            specialist_results[name] = result

    # Step 2b: Apply unit conversions (date-matched FX where needed)
    for spec_name in specialists:
        series_specs = manifest.get(spec_name, {}).get("series", [])
        if not any(s.get("conversion") for s in series_specs):
            continue
        period_days = max(
            (c.get("period_days", 730) for c in manifest.get(spec_name, {}).get("charts", [])),
            default=730,
        )
        print(f"  [{spec_name}] Applying unit conversions...")
        converted_dfs, conv_note = apply_conversions(
            specialist_results[spec_name]["dataframes"], series_specs, period_days
        )
        specialist_results[spec_name]["dataframes"] = converted_dfs
        if conv_note:
            specialist_results[spec_name]["conversion_note"] = conv_note
            print(f"  [{spec_name}] Conversion: {conv_note[:80]}...")

    # Step 3: Render figures
    print("\n[3/4] Rendering figures...")
    packages = []
    fig_idx = 0
    for specialist_name in specialists:
        result = specialist_results[specialist_name]
        for chart_spec in result["chart_specs"]:
            output_path = os.path.join(output_dir, f"figure_{fig_idx:02d}.png")
            title = chart_spec.get("title", f"figure_{fig_idx:02d}")
            print(f"  Rendering figure {fig_idx + 1}: '{title}'")
            package = _render_figure(chart_spec, result, output_path)
            if package is None:
                fig_idx += 1
                continue

            # Multi-package return (multi-year pie): add individual year pies directly,
            # then let the combined figure fall through to the review loop below.
            if isinstance(package, list):
                pre_pkgs = package[:-1]   # individual year pies — no review needed
                for pre_pkg in pre_pkgs:
                    pre_pkg.pop("_merged", None)
                    packages.append(pre_pkg)
                    fig_idx += 1
                package = package[-1]     # combined figure → continues to review below
                output_path = package["path"]

            # Step 4: Devil's Advocate review (max 2 loops)
            print(f"  [reviewer] Checking figure {fig_idx + 1}...")
            final_approved = False
            last_flag = None
            data_mismatch_keywords = [
                "data does not match", "wrong data", "mismatch", "incorrect series",
                "plotted data", "title states", "actually plotted", "data source",
            ]
            for attempt in range(2):
                review = review_figure(package["path"], package["metadata"])
                status = review["status"]
                reason = review.get("reason", "")
                if status == "APPROVED":
                    print(f"  [reviewer] APPROVED")
                    final_approved = True
                    break
                last_flag = reason
                # Detect data/label mismatch — re-rendering can't fix wrong source data.
                if any(kw in reason.lower() for kw in data_mismatch_keywords):
                    print(f"  [reviewer] DATA MISMATCH — flagging in metadata.")
                    package["metadata"]["reviewer_flag"] = reason
                    final_approved = False
                    break
                print(f"  [reviewer] REVISION NEEDED: {reason} — re-rendering...")
                # Patch y_label if reviewer flagged a unit/label issue
                reason_lower = reason.lower()
                current_ylabel = chart_spec.get("y_label", "")
                if current_ylabel in ("pp", "PP", "p.p.", "ppts"):
                    chart_spec = {**chart_spec, "y_label": "Percentage points"}
                    print(f"  [reviewer] Patched y_label: {current_ylabel} → Percentage points")
                elif current_ylabel in ("bps", "bp", "BPS"):
                    chart_spec = {**chart_spec, "y_label": "Basis points (bps)"}
                    print(f"  [reviewer] Patched y_label: {current_ylabel} → Basis points (bps)")
                elif "percentage point" in reason_lower:
                    chart_spec = {**chart_spec, "y_label": "Percentage points"}
                    print(f"  [reviewer] Patched y_label → Percentage points (from reviewer hint)")
                elif "basis point" in reason_lower or "'bps'" in reason_lower:
                    chart_spec = {**chart_spec, "y_label": "Basis points (bps)"}
                    print(f"  [reviewer] Patched y_label → Basis points (bps) (from reviewer hint)")
                rerendered = _render_figure(chart_spec, result, output_path)
                if rerendered is not None:
                    package = rerendered
            # Only surface a reviewer flag if the figure was NOT approved in the end.
            # A flag from attempt 0 that was fixed on re-render should NOT be shown.
            # Suppress known structural false positives for Type G (still visible in Live log).
            _G_FP_PHRASES = ("y-axis", "y axis", "y_label", "category names",
                              "horizontal bar", "swapped axes", "remove the '%'",
                              "should display category")
            if (last_flag and chart_spec.get("type") == "G"):
                if any(p in last_flag.lower() for p in _G_FP_PHRASES):
                    print(f"  [reviewer] Suppressed known Type G structural false positive — see Live log")
                    last_flag = None
            if not final_approved and last_flag and "reviewer_flag" not in package["metadata"]:
                package["metadata"]["reviewer_flag"] = last_flag

            # Strip internal stash before saving
            merged_df = package.pop("_merged", None)
            packages.append(package)
            fig_idx += 1

            # Auto-generate companion event impact table for Type A charts with events
            events = chart_spec.get("events", [])
            if events and merged_df is not None:
                # Warn if any event falls outside the fetched data window
                for ev in events:
                    try:
                        ev_ts = pd.Timestamp(ev["date"])
                        if ev_ts < merged_df.index[0]:
                            print(f"  [warn] Event '{ev.get('label', ev['date'])}' ({ev['date']}) "
                                  f"is BEFORE the data window start ({merged_df.index[0].date()}). "
                                  f"Event table and marker will be missing. "
                                  f"Increase period_days to cover this event.")
                    except Exception:
                        pass
            if chart_spec.get("type") == "A" and events and merged_df is not None:
                table_path = os.path.join(output_dir, f"figure_{fig_idx:02d}.png")
                kilde_str = " og ".join(result["kilde"])
                impact_pkg = _build_event_impact_table(
                    merged_df, events, chart_spec, kilde_str, table_path
                )
                if impact_pkg:
                    packages.append(impact_pkg)
                    fig_idx += 1

    # Build rerender context — one entry per figure, stored for /rerender endpoint
    rerender_ctx = []
    fig_ctx_idx = 0
    for spec_name in specialists:
        result = specialist_results[spec_name]
        for chart_spec in result["chart_specs"]:
            rerender_ctx.append({
                "figure_id":    fig_ctx_idx,
                "specialist":   spec_name,
                "series_specs": manifest.get(spec_name, {}).get("series", []),
                "chart_spec":   chart_spec,
                "brief":        brief,
            })
            fig_ctx_idx += 1

    ctx_path = os.path.join(output_dir, "rerender_context.json")
    with open(ctx_path, "w") as f:
        json.dump(rerender_ctx, f, indent=2, default=str)

    # Step 5: Save manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"brief": brief, "date": str(date.today()), "figures": packages}, f, indent=2, default=str)

    print(f"\n[4/4] Done. {len(packages)} figure(s) saved to '{output_dir}/'")
    return packages

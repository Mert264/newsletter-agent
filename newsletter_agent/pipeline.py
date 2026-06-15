# newsletter_agent/pipeline.py
"""Main pipeline orchestration: brief → manifest → specialists (parallel) → normalize → render → review → output."""
from __future__ import annotations
import os
import re
import json
import pandas as pd
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from newsletter_agent.orchestrator import build_task_manifest
from newsletter_agent.specialists.energy import fetch_energy
from newsletter_agent.specialists.rates import fetch_rates
from newsletter_agent.specialists.macro import fetch_macro
from newsletter_agent.specialists.commodities import fetch_commodities
from newsletter_agent.specialists.equities import fetch_equities
from newsletter_agent.specialists.danish_equities import fetch_danish_equity
from newsletter_agent.specialists.eurostat import fetch_eurostat
from newsletter_agent.specialists.worldbank import fetch_worldbank
from newsletter_agent.specialists.imf import fetch_imf
from newsletter_agent.specialists.oecd import fetch_oecd
from newsletter_agent.processors.normalize import drop_nulls, align_dates, index_to_100, compute_yoy
from newsletter_agent.processors.converters import apply_conversions
from newsletter_agent.formatting import fmt_da, EXCEL_NUM_FORMAT
from newsletter_agent.routing import get_routing_hint
from newsletter_agent.renderers.charts import render_type_a, render_type_b, render_type_c, render_type_e, render_type_f, render_type_g, render_type_p
from newsletter_agent.renderers.tables import render_type_d
from newsletter_agent.reviewer import review_figure

_WB_DATA_GAP_COUNTRIES = {"JPN", "CHN", "SAU", "LBY", "ARE", "KWT", "QAT"}

_WB_TICKER_ORDER = [
    "NY.GDP.MKTP.KD.ZG",   # BNP-vækst
    "FP.CPI.TOTL.ZG",      # Inflation
    "SL.UEM.TOTL.ZS",      # Arbejdsløshed
    "GC.DOD.TOTL.GD.ZS",   # Offentlig gæld
    "BN.CAB.XOKA.GD.ZS",   # Betalingsbalance
]

_WB_TICKER_NAME = {
    "NY.GDP.MKTP.KD.ZG": "BNP-vækst",
    "FP.CPI.TOTL.ZG":    "Inflation",
    "SL.UEM.TOTL.ZS":    "Arbejdsløshed",
    "GC.DOD.TOTL.GD.ZS": "Offentlig gæld",
    "BN.CAB.XOKA.GD.ZS": "Betalingsbalance",
}

_WB_COUNTRY_NAMES = {
    "AFG": "Afghanistan", "ALB": "Albanien", "DZA": "Algeriet", "ARG": "Argentina",
    "ARM": "Armenien", "AUS": "Australien", "AUT": "Østrig", "AZE": "Aserbajdsjan",
    "BEL": "Belgien", "BGR": "Bulgarien", "BLR": "Hviderusland", "BRA": "Brasilien",
    "CAN": "Canada", "CHE": "Schweiz", "CHL": "Chile", "CHN": "Kina",
    "COL": "Colombia", "HRV": "Kroatien", "CZE": "Tjekkiet", "DNK": "Danmark",
    "EGY": "Egypten", "EST": "Estland", "ETH": "Etiopien", "FIN": "Finland",
    "FRA": "Frankrig", "DEU": "Tyskland", "GHA": "Ghana", "GRC": "Grækenland",
    "HUN": "Ungarn", "IND": "Indien", "IDN": "Indonesien", "IRN": "Iran",
    "IRQ": "Irak", "IRL": "Irland", "ISR": "Israel", "ITA": "Italien",
    "JPN": "Japan", "JOR": "Jordan", "KAZ": "Kasakhstan", "KEN": "Kenya",
    "KOR": "Sydkorea", "KWT": "Kuwait", "LBY": "Libyen", "LTU": "Litauen",
    "LVA": "Letland", "MAR": "Marokko", "MEX": "Mexico", "MYS": "Malaysia",
    "NGA": "Nigeria", "NLD": "Holland", "NOR": "Norge", "PAK": "Pakistan",
    "PER": "Peru", "PHL": "Filippinerne", "POL": "Polen", "PRT": "Portugal",
    "QAT": "Qatar", "ROU": "Rumænien", "RUS": "Rusland", "SAU": "Saudi-Arabien",
    "SEN": "Senegal", "SGP": "Singapore", "SVK": "Slovakiet", "SVN": "Slovenien",
    "ZAF": "Sydafrika", "ESP": "Spanien", "LKA": "Sri Lanka", "SWE": "Sverige",
    "THA": "Thailand", "TUR": "Tyrkiet", "UKR": "Ukraine", "ARE": "UAE",
    "GBR": "Storbritannien", "USA": "USA", "UZB": "Usbekistan",
    "VEN": "Venezuela", "VNM": "Vietnam", "YEM": "Yemen", "ZMB": "Zambia",
}


def _enforce_worldbank_single_country_layout(manifest: dict, period_days: int = None) -> dict:
    """Rebuild worldbank chart_specs if the LLM failed to follow the mandatory 10-chart layout.
    Only fires for single-country worldbank requests with wrong chart count or combined indicators."""
    if "worldbank" not in manifest.get("specialists", []):
        return manifest

    wb = manifest["worldbank"]
    series_list = wb.get("series", [])
    if not series_list:
        return manifest

    # Only enforce for single-country (all series share one ISO3)
    countries = {s.get("country", "").upper() for s in series_list if s.get("country")}
    if len(countries) != 1:
        return manifest

    iso3 = list(countries)[0]
    skip_debt = iso3 in _WB_DATA_GAP_COUNTRIES
    expected = 8 if skip_debt else 10

    current_charts = wb.get("charts", [])
    type_a_charts = [c for c in current_charts if c.get("type") == "A"]
    combined = any(len(c.get("series_labels", [])) > 1 for c in type_a_charts)

    # Check if a data-gap country still has gæld charts that will produce empty renders
    gæld_label = next((s.get("label", "") for s in series_list if s.get("ticker") == "GC.DOD.TOTL.GD.ZS"), "")
    has_stray_gæld = skip_debt and gæld_label and any(
        gæld_label in c.get("series_labels", []) for c in current_charts
    )

    if len(current_charts) >= expected and not combined and not has_stray_gæld:
        return manifest  # already correct

    print(f"  [manifest-enforce] {iso3}: {len(current_charts)} charts (expected {expected}). Rebuilding mandatory layout...")

    if period_days:
        years = max(5, min(30, period_days // 365))
    else:
        years = 20
    before_date = f"{2026 - years}-01-01"
    col_before = f"For {years} år siden"

    # Build label lookup from the series list (use first occurrence per ticker)
    label_by_ticker: dict[str, str] = {}
    for s in series_list:
        t = s.get("ticker", "")
        if t and t not in label_by_ticker:
            label_by_ticker[t] = s.get("label", t)

    country_name = _WB_COUNTRY_NAMES.get(iso3, iso3)

    def _note(ticker: str) -> str:
        ind = _WB_TICKER_NAME.get(ticker, ticker)
        texts = {
            "BNP-vækst":       f"Årlig real BNP-vækst for {country_name}. Viser procentvis ændring i samlet produktion i faste priser.",
            "Inflation":        f"Forbrugerprisindeks (CPI) for {country_name}. Viser den årlige stigning i forbrugerpriserne.",
            "Arbejdsløshed":    f"Arbejdsløshedsprocent for {country_name}. Andel af arbejdsstyrken uden beskæftigelse.",
            "Offentlig gæld":   f"Offentlig bruttogæld for {country_name} som andel af BNP.",
            "Betalingsbalance": f"Løbende betalingsbalance for {country_name} som andel af BNP. Positivt = overskud.",
        }
        return texts.get(ind, f"Makroøkonomisk nøgletal for {country_name}. Kilde: Verdensbanken.")

    available = [t for t in _WB_TICKER_ORDER
                 if t in label_by_ticker and not (t == "GC.DOD.TOTL.GD.ZS" and skip_debt)]
    all_labels = [label_by_ticker[t] for t in available]
    gdp_ticker = "NY.GDP.MKTP.KD.ZG"
    gdp_label = label_by_ticker.get(gdp_ticker)
    pd_ = period_days or 7300

    new_charts = []

    # Chart 1: BNP-vækst Type A
    if gdp_label:
        new_charts.append({
            "type": "A", "title": f"{country_name} — BNP-vækst (%)",
            "x_label": "Dato", "y_label": "%", "period_days": pd_,
            "series_labels": [gdp_label], "note": _note(gdp_ticker),
        })

    # Chart 2: Combined nøgletal overview Type D
    if all_labels:
        new_charts.append({
            "type": "D", "title": f"{country_name} — Nøgletal",
            "x_label": "", "y_label": "%", "period_days": pd_,
            "series_labels": all_labels,
            "before_date": before_date, "after_date": "latest",
            "col_before": col_before, "col_after": "Senest tilgængelige",
            "note": f"Oversigt over centrale makroøkonomiske nøgletal for {country_name}.",
        })

    # Charts 3-10: per-indicator A + D pairs (skip BNP-vækst)
    for ticker in available:
        if ticker == gdp_ticker:
            continue
        label = label_by_ticker[ticker]
        ind = _WB_TICKER_NAME.get(ticker, ticker)
        note = _note(ticker)
        new_charts.append({
            "type": "A", "title": f"{country_name} — {ind} (%)",
            "x_label": "Dato", "y_label": "%", "period_days": pd_,
            "series_labels": [label], "note": note,
        })
        new_charts.append({
            "type": "D", "title": f"{country_name} — {ind}: nøgletal",
            "x_label": "", "y_label": "%", "period_days": pd_,
            "series_labels": [label],
            "before_date": before_date, "after_date": "latest",
            "col_before": col_before, "col_after": "Senest tilgængelige",
            "note": note,
        })

    manifest["worldbank"]["charts"] = new_charts
    print(f"  [manifest-enforce] Rebuilt to {len(new_charts)} charts for {country_name}.")
    return manifest


from newsletter_agent.specialists.annual_report import fetch_annual_report
from newsletter_agent.specialists.bigmac import fetch_bigmac
from newsletter_agent.specialists.mag7 import fetch_mag7

SPECIALIST_MAP = {
    "energy":        fetch_energy,
    "rates":         fetch_rates,
    "macro":         fetch_macro,
    "commodities":   fetch_commodities,
    "equities":      fetch_equities,
    "eurostat":      fetch_eurostat,
    "worldbank":     fetch_worldbank,
    "imf":           fetch_imf,
    "oecd":          fetch_oecd,
    "annual_report":    fetch_annual_report,
    "bigmac":           fetch_bigmac,
    "danish_equities":  fetch_danish_equity,
    "mag7":             fetch_mag7,
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
    """Return the series value closest to date_str ('latest' → last observation).

    If date_str falls outside the series range, clamps to the nearest boundary value
    rather than silently returning the wrong end-point (which would make before=after → +0.0%).
    Raises ValueError when the series is empty.
    """
    clean = series.dropna()
    if not date_str or date_str == "latest":
        return float(clean.iloc[-1])
    ts = pd.Timestamp(date_str)
    # Guard: if requested date is AFTER series end, clamp to last available date
    if ts > clean.index.max():
        print(f"  [info] _snapshot_value: date {date_str} is after series end "
              f"{clean.index.max().date()} — clamping to last available value.")
        ts = clean.index.max()
    idx = clean.index.get_indexer([ts], method="nearest")[0]
    return float(clean.iloc[idx])


def _fmt(val: float) -> str:
    """Format a number for table display in Danish style (2.000.000,00)."""
    return fmt_da(val)


def _build_table(dfs: dict, chart_spec: dict, kilde_str: str, output_path: str) -> str:
    """Build and render a Type D snapshot/before-after table from real series data."""
    before_date = chart_spec.get("before_date", "")
    after_date  = chart_spec.get("after_date", "latest")
    col_before  = chart_spec.get("col_before", "Før")
    col_after   = chart_spec.get("col_after", "Nu")

    # Use absolute pp change for rate/yield series (y_label="%"), relative % otherwise
    y_label = chart_spec.get("y_label", "")
    use_absolute = y_label.strip() in ("%", "pp", "PP", "Percentage points", "Procentpoint",
                                        "Basis points (bps)", "YoY %", "YoY%")

    # First pass: collect raw values to enable data-driven use_absolute override
    raw_rows = []
    for label, df in dfs.items():
        series = df.iloc[:, 0].dropna()
        if series.empty:
            continue
        try:
            after_val  = _snapshot_value(series, after_date)
            before_val = _snapshot_value(series, before_date) if before_date else float(series.iloc[0])
            # Sanity check: if before == after, the before_date likely wasn't patched
            if before_date and abs(before_val - after_val) < 1e-9:
                print(f"    [info] Table '{label}': before_val == after_val ({before_val:.4f}) — "
                      f"before_date={before_date!r} may be outside data range.")
            raw_rows.append((label, before_val, after_val))
        except ValueError as e:
            print(f"    [warn] Table '{label}': {e} — skipping row.")
        except Exception as e:
            print(f"    [warn] Could not build table row for '{label}': {e}")

    # World Bank data: all core indicators are annual % values — always show change in pp.
    # This holds even for Offentlig gæld which can exceed 100% (e.g. Japan 260%, Hungary 80%).
    if not use_absolute and "Verdensbanken" in kilde_str:
        use_absolute = True

    # Data-driven override: if ALL values look like rates/percentages (abs < 30),
    # always use absolute pp change — even if the orchestrator forgot to set y_label="%".
    # This catches standalone D tables for bond yields, inflation, policy rates etc.
    # (Skipped when y_label already clearly indicates index levels or prices.)
    if not use_absolute:
        all_vals = [v for _, b, a in raw_rows for v in (b, a) if v is not None]
        if all_vals and max(abs(v) for v in all_vals) < 30:
            use_absolute = True

    # target_value: when set, the third column shows distance from target (e.g. 2%-mål)
    # instead of the period-on-period change.
    target_value = chart_spec.get("target_value")
    if target_value is not None:
        change_col = f"Afstand til {target_value}%-mål"
    else:
        change_col = "Ændring"

    rows = []
    for label, before_val, after_val in raw_rows:
        if target_value is not None:
            dist = after_val - target_value
            sign = "+" if dist >= 0 else ""
            change_str = f"{sign}{dist:.2f}".replace(".", ",") + " pp"
        else:
            change = after_val - before_val
            sign   = "+" if change >= 0 else ""
            if use_absolute:
                change_str = f"{sign}{change:.2f}".replace(".", ",") + " pp"
            else:
                pct = (change / abs(before_val) * 100) if before_val != 0 else 0.0
                change_str = f"{sign}{pct:.1f}%"
        rows.append({
            "indicator": label,
            col_before:  _fmt(before_val),
            col_after:   _fmt(after_val),
            change_col:  change_str,
        })

    data = {"columns": [col_before, col_after, change_col], "rows": rows}
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
        use_absolute = y_label.strip() in ("%", "pp", "PP", "Percentage points", "Procentpoint",
                                        "Basis points (bps)", "YoY %", "YoY%")

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




def _patch_chart_spec_for_missing(chart_spec: dict, still_missing: list) -> dict:
    """Update title and note when some requested series have no data.
    Removes missing country names from the chart title so the renderer and
    reviewer see a consistent chart (title matches the data actually present).
    Works for both single-indicator missing and whole-country missing cases."""
    new_spec = dict(chart_spec)

    # Extract the country/entity prefix from labels formatted as "Country — Indicator"
    missing_entities: list[str] = []
    for ml in still_missing:
        if " — " in ml:
            missing_entities.append(ml.split(" — ")[0].strip())

    if missing_entities:
        title = new_spec.get("title", "")
        for entity in missing_entities:
            esc = re.escape(entity)
            # "og Country" or "Country og" patterns (Danish "and")
            title = re.sub(rf"\s+og\s+{esc}", "", title, flags=re.IGNORECASE)
            title = re.sub(rf"\b{esc}\s+og\s+", "", title, flags=re.IGNORECASE)
            # Comma-separated lists: ", Country" or "Country,"
            title = re.sub(rf",?\s*{esc}\b", "", title, flags=re.IGNORECASE)
        # Remove dangling comparison markers left when the second entity was stripped
        title = re.sub(r"\s+vs\.?\s*$", "", title, flags=re.IGNORECASE)           # at end
        title = re.sub(r"\s+vs\.?\s*(?=[—\-])", " ", title, flags=re.IGNORECASE)  # mid-string before separator
        title = re.sub(r"\s+mod\s*$", "", title, flags=re.IGNORECASE)
        # Clean up stray separators and extra whitespace left after removal
        title = re.sub(r"\s{2,}", " ", title)
        title = re.sub(r"\s+—\s*$", "", title)   # trailing " —"
        title = title.strip(" —,")
        new_spec["title"] = title

    # Also scrub missing entity names from the original note text so the footer
    # does not reference countries/series that have no data (e.g. "Sverige" when
    # Sweden's World Bank series is absent).
    existing_note = new_spec.get("note", "").rstrip(". ")
    if missing_entities and existing_note:
        for entity in missing_entities:
            esc = re.escape(entity)
            existing_note = re.sub(rf"\s+og\s+{esc}", "", existing_note, flags=re.IGNORECASE)
            existing_note = re.sub(rf"\b{esc}\s+og\s+", "", existing_note, flags=re.IGNORECASE)
            existing_note = re.sub(rf",?\s*{esc}\b", "", existing_note, flags=re.IGNORECASE)
        existing_note = re.sub(r"\s{2,}", " ", existing_note).strip(" —,")

    missing_str = ", ".join(still_missing)
    gap_note = f"Data for {missing_str} ikke tilgængeligt via Verdensbanken."
    new_spec["note"] = f"{existing_note} {gap_note}".strip() if existing_note else gap_note
    return new_spec


def _render_figure(chart_spec: dict, specialist_result: dict, output_path: str,
                   global_pool: Optional[dict] = None) -> dict:
    """Render one figure from chart_spec + specialist data. Returns FigurePackage dict."""
    chart_type = chart_spec["type"]
    dfs = specialist_result["dataframes"]
    kilde_sources = list(specialist_result["kilde"])

    # ── Filter to series for this chart ──────────────────────────────────────
    series_labels = chart_spec.get("series_labels")
    _unresolved: list = []
    if series_labels:
        dfs = {k: v for k, v in dfs.items() if k in series_labels}
        missing = [lbl for lbl in series_labels if lbl not in specialist_result["dataframes"]]
        if missing and global_pool:
            # Cross-specialist: supplement with series fetched by another specialist.
            for lbl in missing:
                if lbl in global_pool["dataframes"]:
                    dfs[lbl] = global_pool["dataframes"][lbl]
            still_missing = [lbl for lbl in series_labels if lbl not in dfs]
            # Merge in any additional kilde sources from the contributing specialists.
            for k in global_pool.get("kilde", []):
                if k not in kilde_sources:
                    kilde_sources.append(k)
            if still_missing:
                print(f"    [warn] series_labels mismatch — missing even after global lookup: {still_missing}")
                print(f"           Available globally: {list(global_pool['dataframes'].keys())}")
                _unresolved = still_missing
        elif missing:
            print(f"    [warn] series_labels mismatch — these labels were requested but not fetched: {missing}")
            print(f"           Available labels: {list(specialist_result['dataframes'].keys())}")
            _unresolved = missing

    # Gracefully patch title/note for data gaps so the reviewer sees a consistent chart
    if _unresolved:
        chart_spec = _patch_chart_spec_for_missing(chart_spec, _unresolved)

    kilde_str = " og ".join(dict.fromkeys(kilde_sources))

    # ── Spread computation (compute_spread_vs) ────────────────────────────────
    compute_spread_vs = chart_spec.get("compute_spread_vs")
    if compute_spread_vs and len(dfs) > 1:
        ref_label = next(
            (lbl for lbl in dfs
             if compute_spread_vs.lower() in lbl.lower() or lbl.lower() in compute_spread_vs.lower()),
            None,
        )
        if ref_label:
            ref_series = dfs[ref_label].iloc[:, 0].dropna()
            spread_dfs = {}
            for lbl, df in dfs.items():
                if lbl == ref_label:
                    continue
                s = df.iloc[:, 0].dropna()
                common = s.index.intersection(ref_series.index)
                if not common.empty:
                    spread_dfs[lbl] = (s.loc[common] - ref_series.loc[common]).to_frame(lbl)
            if spread_dfs:
                dfs = spread_dfs
                print(f"    [spread] vs '{ref_label}' — {len(spread_dfs)} series computed")
                # Auto-set y_label to Procentpoint if not already meaningful
                if chart_spec.get("y_label", "") in ("", "%", "Procent", "Pct."):
                    chart_spec = {**chart_spec, "y_label": "Procentpoint"}
            else:
                print(f"    [warn] compute_spread_vs '{compute_spread_vs}' matched '{ref_label}' "
                      f"but produced no spread data (no overlapping dates?)")
        else:
            print(f"    [warn] compute_spread_vs '{compute_spread_vs}' matched no series "
                  f"in {list(dfs.keys())}")
    # ─────────────────────────────────────────────────────────────────────────

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
        if chart_spec.get("table_data"):
            from newsletter_agent.renderers.tables import render_type_d
            path = render_type_d(
                chart_spec["table_data"],
                {**chart_spec, "kilde": kilde_str},
                output_path,
            )
        else:
            path = _build_table(dfs, chart_spec, kilde_str, output_path)

    # ── Type E — Before/after grouped bar chart ───────────────────────────
    elif chart_type == "E":
        path = _build_before_after_bars(dfs, chart_spec, kilde_str, output_path)

    # ── Type F — 100% stacked bar (composition / energy mix) ─────────────
    elif chart_type == "F":
        # Cap years to match user's timeline selection (period_days → year count).
        _f_period = chart_spec.get("period_days", None)
        _f_year_cap = max(1, round(_f_period / 365)) if _f_period else 10

        # F expects a wide DataFrame: index=categories, columns=series labels
        # If specialist returns multiple single-column DFs, merge them wide.
        if len(dfs) == 1:
            wide = list(dfs.values())[0]
            if isinstance(wide.index, pd.DatetimeIndex):
                wide = wide.copy()
                wide.index = wide.index.year.astype(str)
            wide = wide.tail(_f_year_cap)
        else:
            # Multiple series → each is a column; build wide from time snapshots
            parts = {}
            for lbl, df in dfs.items():
                s = df.iloc[:, 0].dropna()
                if isinstance(s.index, pd.DatetimeIndex):
                    s.index = s.index.year.astype(str)
                parts[lbl] = s
            wide = pd.DataFrame(parts).dropna(how="all").tail(_f_year_cap)
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
            # Deduplicate index again after drop_nulls (ffill can surface hidden dupes)
            if clean.index.duplicated().any():
                clean = clean[~clean.index.duplicated(keep="last")]
            if merged is None:
                merged = clean
            else:
                # Outer join + forward-fill so weekends/public holidays don't punch holes.
                # limit=5: fills at most 5 consecutive missing positions (covers a trading week
                # for daily data; for monthly data prevents a stale series from propagating
                # its last value years into the future across other countries' data).
                merged = merged.join(clean, how="outer").ffill(limit=5).dropna(how="all")
                # Remove duplicate index rows introduced by the join (Yahoo Finance
                # occasionally returns duplicate timestamps that survive ffill).
                if merged.index.duplicated().any():
                    merged = merged[~merged.index.duplicated(keep="last")]
                # Remove any duplicate columns introduced by the join
                if merged.columns.duplicated().any():
                    merged = merged.loc[:, ~merged.columns.duplicated(keep="last")]

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
            if merged.empty:
                print(f"    [warn] All series dropped after YoY transform for '{chart_spec.get('title')}' — skipping.")
                return None

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
            # Normalise the y_label to the canonical Danish form so the axis is always clear.
            # Exception: DXY is a natural index — keep "Indeks" without the "(basis=100)" qualifier.
            _cols_lower_explicit = [c.lower() for c in merged.columns]
            _has_dxy_explicit = any(
                "dxy" in c or "dollar index" in c or "dollarindeks" in c
                for c in _cols_lower_explicit
            )
            if not _has_dxy_explicit:
                chart_spec = {**chart_spec, "y_label": "Indekseret (basis = 100)"}
                y_label = "Indekseret (basis = 100)"

        # Safety net: if series have wildly incompatible scales (>10x range ratio),
        # auto-index even if y_label doesn't request it, to avoid invisible lines.
        # Skip when conversions applied, or when y_label is already a rate/% (comparable by definition).
        _is_rate_label = y_label.strip() in ("%", "pp", "PP", "Procentpoint", "Percentage points",
                                              "Basis points (bps)", "YoY %", "YoY%")
        if not conversions_applied and len(merged.columns) > 1 and not _is_rate_label and "yoy" not in y_label.lower():
            ranges = [merged[c].max() - merged[c].min() for c in merged.columns
                      if merged[c].notna().any()]
            if ranges and max(ranges) / (min(ranges) + 1e-9) > 10:
                merged = index_to_100(merged)
                # If DXY is one of the series it is already a natural index — use "Indeks"
                # rather than "Indekseret (basis=100)" which implies deliberate rebasing.
                cols_lower = [c.lower() for c in merged.columns]
                has_dxy = any("dxy" in c or "dollar index" in c or "dollarindeks" in c for c in cols_lower)
                new_ylabel = "Indeks" if has_dxy else "Indekseret (basis=100)"
                chart_spec = {**chart_spec, "y_label": new_ylabel}
                render_spec = {**chart_spec, "kilde": kilde_str}

        # If DXY is present and y_label still says "Indekseret (basis=100)", downgrade to "Indeks"
        # so the reviewer doesn't flag it — DXY is a natural index, not deliberately rebased.
        if render_spec.get("y_label") in ("Indekseret (basis=100)", "Indexed (base=100)"):
            cols_lower = [c.lower() for c in merged.columns]
            if any("dxy" in c or "dollar index" in c or "dollarindeks" in c for c in cols_lower):
                render_spec = {**render_spec, "y_label": "Indeks"}
                chart_spec  = {**chart_spec,  "y_label": "Indeks"}

        # ── Final display-window trim ──────────────────────────────────────────
        # Specialists fetch data for max(period_days) across all their charts so YoY
        # transforms have enough history. After all transforms, trim merged to exactly
        # the user's requested display window before handing off to the renderer.
        # Only fires when display_period_days was stamped by the hard-enforce block
        # (i.e., the user explicitly chose a Tidsperiode). Not applied when index_base_date
        # governs the start date (that trim already happened above).
        _display_days = chart_spec.get("display_period_days")
        if _display_days and not index_base_date:
            _data_end = merged.index.max()
            _trim_start = _data_end - pd.Timedelta(days=_display_days)
            _trimmed = merged[merged.index >= _trim_start]
            if not _trimmed.empty:
                merged = _trimmed

        renderer = CHART_RENDERER_MAP[chart_type]
        path = renderer(merged, render_spec, output_path)

        if chart_type == "A":
            merged_for_events = merged

    _no_axis_types = {"D", "P"}
    # D-type charts rendered from table_data: use column names as region_labels so the
    # reviewer can confirm the table has meaningful content without seeing the dataframes.
    _table_data_chart = chart_spec.get("type") == "D" and bool(chart_spec.get("table_data"))
    if _table_data_chart:
        _tbl_cols = chart_spec.get("table_data", {}).get("columns", [])
        _region_labels = _tbl_cols if _tbl_cols else []
    else:
        _region_labels = list(dfs.keys())
    metadata = {
        "title":         chart_spec["title"],
        "chart_type":    chart_spec.get("type", "?"),
        "x_label":       "" if chart_spec.get("type") in _no_axis_types else chart_spec.get("x_label", ""),
        "y_label":       "" if chart_spec.get("type") in _no_axis_types else chart_spec.get("y_label", ""),
        "note":          chart_spec.get("note", ""),
        "kilde":         kilde_str,
        "region_labels": _region_labels,
    }
    pkg = {
        "path":     path,
        "metadata": metadata,
    }
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


def _safe_sheet_name(label: str) -> str:
    return label[:31].replace("/", "-").replace("\\", "-").replace("*", "").replace("?", "").replace("[", "").replace("]", "").replace(":", "-")


def _write_excel_per_figure(packages: list, specialist_results: dict, output_dir: str) -> list:
    """Write one Excel file per figure. Returns list of paths, empty string for figures with no data."""
    try:
        import openpyxl
    except ImportError:
        return [""] * len(packages)

    all_dfs: dict = {}
    for result in specialist_results.values():
        all_dfs.update(result.get("dataframes", {}))

    excel_paths = []
    for i, package in enumerate(packages):
        metadata = package.get("metadata", {})
        chart_type = metadata.get("chart_type", "")
        series_labels = metadata.get("region_labels", [])

        # D-type tables don't have time-series data to export
        if chart_type == "D" or not series_labels:
            excel_paths.append("")
            continue

        relevant = {lbl: all_dfs[lbl] for lbl in series_labels if lbl in all_dfs}
        if not relevant:
            excel_paths.append("")
            continue

        safe_title = re.sub(r'[\\/*?:\[\]|<>]', '-', metadata.get("title", f"figure_{i:02d}"))[:45]
        excel_path = os.path.join(output_dir, f"figure_{i:02d}_{safe_title}.xlsx")
        figure_png = package.get("path", "")

        try:
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                written = 0
                for label, df in relevant.items():
                    if df is None or df.empty or df.dropna(how="all").empty:
                        continue
                    sheet = _safe_sheet_name(label)
                    df_out = df.copy()
                    if hasattr(df_out.index, "strftime"):
                        df_out.index = df_out.index.strftime("%Y-%m-%d")
                    df_out.index.name = "Dato"
                    df_out.to_excel(writer, sheet_name=sheet)
                    # Apply Danish number format to all numeric cells
                    ws = writer.sheets[sheet]
                    for row in ws.iter_rows(min_row=2, min_col=2):
                        for cell in row:
                            if isinstance(cell.value, (int, float)):
                                cell.number_format = EXCEL_NUM_FORMAT
                    written += 1

                # Embed the chart image on a dedicated "Grafik" sheet
                if figure_png and os.path.exists(figure_png):
                    try:
                        from openpyxl.drawing.image import Image as XLImage
                        ws_img = writer.book.create_sheet("Grafik", 0)  # first sheet
                        img = XLImage(figure_png)
                        # Scale to fit a standard screen width (~900px at 96dpi ≈ col width ~130)
                        img.width  = 900
                        img.height = int(img.height * 900 / img.width) if img.width else 500
                        ws_img.add_image(img, "B2")
                        ws_img.sheet_view.showGridLines = False
                    except Exception as img_err:
                        print(f"  [excel] Image embed failed for figure {i}: {img_err}")

            if written == 0:
                excel_paths.append("")
                continue
            excel_paths.append(excel_path)
        except Exception as e:
            print(f"  [excel] Failed for figure {i}: {e}")
            excel_paths.append("")

    return excel_paths


def run(brief: str, output_dir: str = "output", preferred_types: list = None,
        period_days: int = None, model: str = None,
        start_date: str = None, end_date: str = None) -> list:
    """
    Main pipeline entry point.
    brief: free-form topic string from department.
    output_dir: where to save PNG files and manifest.json.
    preferred_types: optional list of chart type codes e.g. ["A", "G"] — passed to orchestrator.
    start_date / end_date: explicit ISO date strings — override period_days when provided.
    Returns list of FigurePackage dicts: [{"path": str, "metadata": dict}, ...]
    """
    # If explicit dates provided, derive period_days from them so existing logic still works
    if start_date and not period_days:
        try:
            from datetime import date as _date
            _s = pd.Timestamp(start_date)
            _e = pd.Timestamp(end_date) if end_date else pd.Timestamp.today()
            period_days = max(1, (_e - _s).days)
        except Exception:
            pass
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Orchestrate — 1 LLM call → TaskManifest
    print("\n[1/4] Orchestrating — asking Lead Agent to plan figures...")
    routing_hint = get_routing_hint(brief)
    if routing_hint:
        print(f"      [routing] Hint injected: {routing_hint.strip()[:80]}...")
    manifest = build_task_manifest(brief, preferred_types=preferred_types, routing_hint=routing_hint, period_days=period_days, model=model)
    manifest = _enforce_worldbank_single_country_layout(manifest, period_days=period_days)
    # Strip accidental source attribution from note fields — LLM occasionally includes
    # "Kilde: X" or "Source: X" despite the prompt rule; enforce it programmatically.
    _src_pat = re.compile(r'\s*(Kilde|Source|Data fra|Datakilde)\s*:\s*[^\.\n]+\.?', re.IGNORECASE)
    for _sp in manifest.get("specialists", []):
        for _chart in manifest.get(_sp, {}).get("charts", []):
            if "note" in _chart:
                _chart["note"] = _src_pat.sub("", _chart["note"]).strip()
    specialists = manifest.get("specialists", [])
    print(f"      Specialists activated: {', '.join(specialists)}")

    # Inject explicit date bounds into each specialist task so they don't fetch beyond the window
    if start_date or end_date:
        for spec_name in specialists:
            if start_date:
                manifest[spec_name]["start_date"] = start_date
            if end_date:
                manifest[spec_name]["end_date"] = end_date

    # Hard-enforce the user's period_days on every chart spec.
    # The LLM may inflate period_days (e.g. routing hints say 1825 days for employment)
    # even when the user selected a shorter window. Clamp here — YoY charts get 760 minimum.
    # display_period_days = the user's actual requested window, stored separately so the
    # renderer can trim to it even when period_days was inflated for YoY transform needs.
    if period_days:
        for spec_name in specialists:
            for chart in manifest.get(spec_name, {}).get("charts", []):
                is_yoy = "YoY" in chart.get("y_label", "") or "yoy" in chart.get("y_label", "").lower()
                min_days = 760 if is_yoy else period_days
                chart["period_days"] = max(min_days, period_days) if is_yoy else period_days
                chart["display_period_days"] = period_days  # user's actual display window

    # Patch before_date in companion D-type tables when end_date is a historical date.
    # The orchestrator computes before_date as "today - N days" (e.g. 2025-05-16 for "1 år siden").
    # When TIL is in the past (e.g. 2010-09-10), that date falls AFTER the data ends, so
    # _snapshot_value returns the last available value for both "Nu" and "1 år siden" → +0.0%.
    # Fix: recompute before_date relative to end_date instead of today.
    if end_date:
        _end_ts   = pd.Timestamp(end_date)
        _today_ts = pd.Timestamp.today().normalize()
        for spec_name in specialists:
            for chart in manifest.get(spec_name, {}).get("charts", []):
                if chart.get("type") != "D":
                    continue
                bd = chart.get("before_date", "")
                if not bd or bd in ("latest", ""):
                    continue
                try:
                    _bd_ts = pd.Timestamp(bd)
                    if _bd_ts > _end_ts:
                        # before_date was computed relative to today — rederive relative to end_date
                        _offset_days = max(0, (_today_ts - _bd_ts).days)
                        _corrected   = _end_ts - pd.Timedelta(days=_offset_days)
                        chart["before_date"] = str(_corrected.date())
                        print(f"  [table] Patched before_date {bd} → {chart['before_date']} "
                              f"(relative to end_date={end_date})")
                except Exception:
                    pass

    # Hard-enforce preferred_types: drop chart specs the LLM included despite the instruction,
    # and normalize Type D specs (strip axis labels so the reviewer never flags them).
    if preferred_types:
        allowed = set(preferred_types)
        for spec_name in specialists:
            spec_charts = manifest.get(spec_name, {}).get("charts", [])
            filtered = []
            for c in spec_charts:
                if c.get("type") not in allowed:
                    print(f"  [filter] Dropped type={c.get('type')} chart '{c.get('title','')}' — not in preferred_types")
                    continue
                if c.get("type") in ("D", "P"):
                    c["x_label"] = ""
                    c["y_label"] = ""
                filtered.append(c)
            manifest[spec_name]["charts"] = filtered

    # Step 2: Run all specialists in parallel
    n_charts = sum(len(manifest.get(s, {}).get("charts", [])) for s in specialists)
    print(f"\n[2/4] Fetching data — {len(specialists)} specialist(s), ~{n_charts} chart(s) planned...")
    specialist_results: dict[str, dict] = {}
    _specialist_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(specialists) or 1) as executor:
        futures = {
            executor.submit(_run_specialist, name, manifest[name]): name
            for name in specialists
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                _, result = future.result()
                specialist_results[name] = result
            except Exception as exc:
                import traceback as _tb
                err_detail = str(exc)
                print(f"  [{name}] FAILED — skipping specialist: {err_detail}")
                print(f"  [{name}] Traceback: {_tb.format_exc()[-400:]}")
                _specialist_errors[name] = err_detail
                specialists = [s for s in specialists if s != name]

    # Step 2b: Apply unit conversions (date-matched FX where needed)
    for spec_name in specialists:
        series_specs = manifest.get(spec_name, {}).get("series", [])
        if not any(s.get("conversion") for s in series_specs):
            continue
        conv_period_days = max(
            (c.get("period_days", 730) for c in manifest.get(spec_name, {}).get("charts", [])),
            default=730,
        )
        print(f"  [{spec_name}] Applying unit conversions...")
        converted_dfs, conv_note = apply_conversions(
            specialist_results[spec_name]["dataframes"], series_specs, conv_period_days
        )
        specialist_results[spec_name]["dataframes"] = converted_dfs
        if conv_note:
            specialist_results[spec_name]["conversion_note"] = conv_note
            print(f"  [{spec_name}] Conversion: {conv_note[:80]}...")

    # Universal date bounds enforcement — clip ALL DataFrames from ALL specialists.
    # Fires for both explicit date ranges (start_date/end_date) and preset periods
    # (period_days). Specialists may fetch more data than needed (e.g. a YoY chart
    # inflates period_days to 760 for transform history, pulling extra data for other
    # series on the same specialist). The display-window trim in _render_figure handles
    # the per-chart precision; this net ensures no data exceeds the end boundary.
    _net_end_ts = (
        pd.Timestamp(end_date) if end_date
        else pd.Timestamp.today().normalize() if (start_date or period_days)
        else None
    )
    _net_start_ts = pd.Timestamp(start_date) if start_date else None
    if _net_start_ts or _net_end_ts:
        for _sp in specialists:
            _dfs = specialist_results.get(_sp, {}).get("dataframes", {})
            for _lbl, _df in list(_dfs.items()):
                if not isinstance(_df.index, pd.DatetimeIndex):
                    continue  # EIA mix uses string-year index — handled separately
                if _net_start_ts is not None:
                    _df = _df[_df.index >= _net_start_ts]
                if _net_end_ts is not None:
                    _df = _df[_df.index <= _net_end_ts]
                _dfs[_lbl] = _df

    # Build global data pool for cross-specialist chart resolution.
    # Charts authored under specialist A can reference series fetched by specialist B
    # (e.g. global inflation: US/UK/JP from macro + EA from eurostat on one chart).
    global_pool: dict = {"dataframes": {}, "kilde": []}
    for _sp_name, _sp_result in specialist_results.items():
        global_pool["dataframes"].update(_sp_result["dataframes"])
        for _k in _sp_result.get("kilde", []):
            if _k not in global_pool["kilde"]:
                global_pool["kilde"].append(_k)

    # Step 3: Render figures
    print("\n[3/4] Rendering figures...")
    packages = []
    fig_idx = 0
    # Maps package list position → rerender context entry (None for event impact tables)
    _rerender_ctx_map: list[dict | None] = []
    # Still track render log for backward compat (specialist isolation, etc.)
    _render_log: list[tuple[str, dict, int]] = []
    for specialist_name in specialists:
        result = specialist_results[specialist_name]
        for chart_spec in result["chart_specs"]:
            output_path = os.path.join(output_dir, f"figure_{fig_idx:02d}.png")
            title = chart_spec.get("title", f"figure_{fig_idx:02d}")
            print(f"  Rendering figure {fig_idx + 1}: '{title}'")
            package = _render_figure(chart_spec, result, output_path, global_pool=global_pool)
            if package is None:
                fig_idx += 1
                continue

            # Multi-package return (multi-year pie): add individual year pies directly,
            # then let the combined figure fall through to the review loop below.
            n_pre = 0
            series_specs_for_ctx = manifest.get(specialist_name, {}).get("series", [])
            if isinstance(package, list):
                pre_pkgs = package[:-1]   # individual year pies — no review needed
                n_pre = len(pre_pkgs)
                for pre_pkg in pre_pkgs:
                    pre_pkg.pop("_merged", None)
                    packages.append(pre_pkg)
                    _rerender_ctx_map.append({
                        "figure_id":    len(_rerender_ctx_map),
                        "specialist":   specialist_name,
                        "series_specs": series_specs_for_ctx,
                        "chart_spec":   chart_spec,
                        "brief":        brief,
                    })
                    fig_idx += 1
                package = package[-1]     # combined figure → continues to review below
                output_path = package["path"]

            # Step 4: Devil's Advocate review (max 2 loops) — skip for summary cards
            if package.get("metadata", {}).get("_skip_review"):
                packages.append(package)
                _rerender_ctx_map.append(None)
                fig_idx += 1
                continue
            print(f"  [reviewer] Checking figure {fig_idx + 1}...")
            final_approved = False
            last_flag = None
            data_mismatch_keywords = [
                "data does not match", "wrong data", "mismatch", "incorrect series",
                "plotted data", "title states", "actually plotted", "data source",
            ]
            # Known structural false positives for Type G horizontal bar charts.
            # The reviewer sees y_label="%"  on the spec and flags it as wrong unit,
            # but for Type G, Y shows category names and X shows the metric — y_label
            # is internal metadata, not a visible axis. Suppress before re-rendering.
            _G_FP_PHRASES = ("y-axis", "y axis", "y_label", "category names",
                              "horizontal bar", "swapped axes", "remove the '%'",
                              "should display category")

            for attempt in range(2):
                review = review_figure(package["path"], package["metadata"])
                status = review["status"]
                reason = review.get("reason", "")
                if status == "APPROVED":
                    print(f"  [reviewer] APPROVED")
                    final_approved = True
                    break
                last_flag = reason
                # Pre-suppress Type G structural false positives before re-rendering.
                if chart_spec.get("type") == "G" and any(p in reason.lower() for p in _G_FP_PHRASES):
                    print(f"  [reviewer] Suppressed known Type G structural false positive")
                    final_approved = True
                    last_flag = None
                    break
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
                elif ("indekseret" in reason_lower or "indexed" in reason_lower) and (
                    "percent" in reason_lower or "%" in reason_lower or "procent" in reason_lower
                ):
                    chart_spec = {**chart_spec, "y_label": "%"}
                    print(f"  [reviewer] Patched y_label → % (Indekseret/% mismatch from reviewer hint)")
                rerendered = _render_figure(chart_spec, result, output_path, global_pool=global_pool)
                if isinstance(rerendered, list):
                    rerendered = rerendered[-1]  # combined figure only during re-review
                if rerendered is not None:
                    package = rerendered
            # Only surface a reviewer flag if the figure was NOT approved in the end.
            # A flag from attempt 0 that was fixed on re-render should NOT be shown.
            # (Type G false positives are already suppressed inline in the review loop above.)
            # DXY + FX rates rebasing false positive: reviewer flags "Indekseret (basis=100)"
            # as wrong for DXY, but it is correct — DXY and FX pairs live on incompatible scales.
            _DXY_FP_PHRASES = ("natural index", "trades as an index", "dxy is a natural",
                                "not a rebased", "remove 'basis=100'", "remove basis=100")
            if last_flag and any(p in last_flag.lower() for p in _DXY_FP_PHRASES):
                _chart_dfs = dfs if "dfs" in dir() else {}
                series_labels_lower = [l.lower() for l in _chart_dfs.keys()]
                if any("dxy" in l or "dollar index" in l for l in series_labels_lower):
                    print(f"  [reviewer] Suppressed DXY+FX rebasing false positive — see Live log")
                    last_flag = None
            if not final_approved and last_flag and "reviewer_flag" not in package["metadata"]:
                package["metadata"]["reviewer_flag"] = last_flag

            # Strip internal stash before saving
            merged_df = package.pop("_merged", None)
            packages.append(package)
            _rerender_ctx_map.append({
                "figure_id":    len(_rerender_ctx_map),
                "specialist":   specialist_name,
                "series_specs": series_specs_for_ctx,
                "chart_spec":   chart_spec,
                "brief":        brief,
            })
            _render_log.append((specialist_name, chart_spec, n_pre + 1))  # total packages from this spec
            fig_idx += 1

            # Auto-generate companion event impact table for Type A charts with events
            events = chart_spec.get("events", [])
            if events and merged_df is not None:
                # Warn if any event falls outside the fetched data window — surface in UI flag
                out_of_window = []
                for ev in events:
                    try:
                        ev_ts = pd.Timestamp(ev["date"])
                        if ev_ts < merged_df.index[0]:
                            msg = (f"Event '{ev.get('label', ev['date'])}' ({ev['date']}) "
                                   f"is before data window start ({merged_df.index[0].date()}). "
                                   f"Increase period_days to show this marker.")
                            print(f"  [warn] {msg}")
                            out_of_window.append(msg)
                    except Exception:
                        pass
                if out_of_window and "reviewer_flag" not in package["metadata"]:
                    package["metadata"]["reviewer_flag"] = " | ".join(out_of_window)
            if chart_spec.get("type") == "A" and events and merged_df is not None and (not preferred_types or "D" in preferred_types):
                table_path = os.path.join(output_dir, f"figure_{fig_idx:02d}.png")
                kilde_str = " og ".join(result["kilde"])
                impact_pkg = _build_event_impact_table(
                    merged_df, events, chart_spec, kilde_str, table_path
                )
                if impact_pkg:
                    packages.append(impact_pkg)
                    _rerender_ctx_map.append(None)  # event impact tables have no rerender context
                    fig_idx += 1

    # Build rerender context — inline map already has correct figure_id per package position.
    # None entries (event impact tables) are excluded — they have no rerender support.
    rerender_ctx = [entry for entry in _rerender_ctx_map if entry is not None]

    ctx_path = os.path.join(output_dir, "rerender_context.json")
    with open(ctx_path, "w") as f:
        json.dump(rerender_ctx, f, indent=2, default=str)

    # Step 5: Per-figure Excel export
    excel_paths = _write_excel_per_figure(packages, specialist_results, output_dir)
    n_excel = 0
    for i, ep in enumerate(excel_paths):
        if ep and i < len(packages):
            packages[i]["metadata"]["excel_path"] = os.path.basename(ep)
            n_excel += 1
    excel_path = "per_figure" if n_excel > 0 else ""
    if n_excel:
        print(f"       Excel: {n_excel} per-figure workbook(s) written")

    # Step 6: Save manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"brief": brief, "date": str(date.today()), "figures": packages}, f, indent=2, default=str)

    print(f"\n[4/4] Done. {len(packages)} figure(s) saved to '{output_dir}/'")
    if _specialist_errors:
        for name, err in _specialist_errors.items():
            print(f"  [pipeline] Specialist '{name}' failed: {err}")
    return packages

# newsletter_agent/specialists/annual_report_kpi.py
#
# 7 clean, investor-focused charts.
# Structure: Executive Summary → Snapshot + LTM → Trend → WACC → DCF Scenarios → Sensitivity → Multiples
import datetime
import pandas as pd
from newsletter_agent.specialists.annual_report_constants import STATUTORY_TAX_RATE


# ── Formatting helpers ────────────────────────────────────────────────────────

def _ts(years: list, values: list, label: str) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(f"{y}-12-31") for y in years])
    return pd.DataFrame({label: values}, index=idx)


def _pct(v: float, decimals: int = 2) -> str:
    return f"{v:.{decimals}%}"


def _num(v: float) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:   # ≥ $1T in USDm
        return f"{v/1_000_000:.2f}T"
    try:
        if v == int(v):
            return f"{int(v):,}"
    except (OverflowError, ValueError):
        pass
    return f"{v:,.1f}"


def _x(v: float, dec: int = 2) -> str:
    return f"{v:.{dec}f}x"


def _fy_label(year: int) -> str:
    return f"FY{year}A"


def _ltm_label(date_str: str) -> str:
    if not date_str:
        return "LTM"
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return f"LTM {d.strftime('%b %Y')}"
    except Exception:
        return "LTM"


def _last_updated(fmp_data: dict, ltm_date: str = "") -> str:
    # Prefer LTM date (more current than annual filing date)
    date_str = ltm_date or (fmp_data.get("income") or [{}])[0].get("date", "")
    if not date_str:
        return "N/A"
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        suffix = " (LTM)" if ltm_date else " (Annual)"
        return d.strftime("%d %b %Y") + suffix
    except Exception:
        return date_str[:10]


def _confidence(upside: float, reformulated: dict) -> str:
    flags   = reformulated.get("flags", [])
    bad     = sum(1 for f in flags if "negativ" in f.lower() or "anomali" in f.lower())
    if bad > 2 or abs(upside) > 1.0:
        return "Low — data quality issues detected"
    if bad > 0 or abs(upside) > 0.5:
        return "Medium — validate balance sheet classification"
    return "Medium — standard DCF uncertainty applies"


def _analyst_next_rev(estimates: list):
    valid = sorted(
        [e for e in (estimates or []) if (e.get("estimatedRevenueAvg") or 0) > 0],
        key=lambda x: x.get("date", ""),
    )
    if not valid:
        return None
    e  = valid[0]
    lo = e.get("estimatedRevenueLow",  0) or 0
    av = e.get("estimatedRevenueAvg",  0) or 0
    hi = e.get("estimatedRevenueHigh", 0) or 0
    yr = (e.get("date") or "")[:4]
    label = f"FY{yr}E" if yr else "Next FY"
    if lo and hi:
        return f"{label}: {_num(av)}m  ({_num(lo)}–{_num(hi)}m)"
    return f"{label}: {_num(av)}m"


# ── LTM balance-sheet derived metrics ────────────────────────────────────────

def _ltm_noa_nfo(ltm_bal: dict, ltm_revenue: float = 0.0):
    if not ltm_bal:
        return None, None
    def s(k):
        return float(ltm_bal.get(k) or 0)
    cash_total    = s("cashAndCashEquivalents")
    op_cash_floor = 0.02 * ltm_revenue
    excess_cash   = max(0.0, cash_total - op_cash_floor)
    fin_assets = excess_cash + s("shortTermInvestments") + s("longTermInvestments")
    fin_liabs  = s("shortTermDebt") + s("longTermDebt") + s("capitalLeaseObligations")
    op_assets  = s("totalAssets") - fin_assets
    op_liabs   = s("totalLiabilities") - fin_liabs
    return op_assets - op_liabs, fin_liabs - fin_assets


# ── Main builder ─────────────────────────────────────────────────────────────

def build_chart_specs(
    ticker: str, company_name: str, hq_country: str,
    reformulated: dict, wacc_data: dict, dcf_scenarios: dict,
    sensitivity: dict, fmp_data: dict,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:

    years    = reformulated["years"]
    profile  = fmp_data.get("profile", {})
    currency = profile.get("currency", "USD")
    price    = float(profile.get("price") or 0)
    kilde    = "FMP, Damodaran"
    rf_entry = wacc_data["rf_entry"]
    wacc     = wacc_data["wacc"]
    iso3     = wacc_data["iso3"]

    base_sc    = dcf_scenarios["base"]
    bear_sc    = dcf_scenarios["bear"]
    bull_sc    = dcf_scenarios["bull"]
    base_price = base_sc["price"]
    bear_price = bear_sc["price"]
    bull_price = bull_sc["price"]

    t = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])

    # LTM data
    ltm_inc = fmp_data.get("ltm_income",   {}) or {}
    ltm_cf  = fmp_data.get("ltm_cashflow", {}) or {}
    ltm_bal = fmp_data.get("ltm_balance",  {}) or {}
    has_ltm = bool(ltm_inc.get("revenue"))

    dfs: dict[str, pd.DataFrame] = {}
    specs = []

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 1 — Executive Summary
    # ══════════════════════════════════════════════════════════════════════════
    upside     = (base_price - price) / price if price > 0 else 0
    nfo_latest = reformulated["NFO"][-1]
    net_cash   = -nfo_latest
    nc_str     = (f"+{_num(net_cash)}m (net cash)" if net_cash >= 0
                  else f"{_num(net_cash)}m (net debt)")

    rev_cagr   = reformulated["historical_avgs"]["revenue_cagr"]
    og_avg     = reformulated["historical_avgs"]["OG"]
    fy_latest  = _fy_label(years[-1])
    n_avg_yrs  = reformulated.get("n_avg_years", len(years))
    cagr_label = f"FY{years[0]}–FY{years[-1]}"
    ltm_date   = ltm_inc.get("date", "") if has_ltm else ""

    exec_rows = [
        {"indicator": "Current Price",              "Value": f"{price:.2f} {currency}"},
        {"indicator": "Fair Value Range",           "Value": f"{bear_price:.0f} – {bull_price:.0f} {currency}"},
        {"indicator": "Base Fair Value",            "Value": f"{base_price:.2f} {currency}"},
        {"indicator": "Upside / Downside",          "Value": f"{upside:+.1%}"},
        {"indicator": "",                           "Value": ""},
        {"indicator": "WACC",                       "Value": _pct(wacc)},
        {"indicator": "Terminal Growth",            "Value": _pct(base_sc["g"])},
        {"indicator": "Net Fin. Obligations (NFO)", "Value": nc_str},
        {"indicator": f"{fy_latest} Revenue",       "Value": f"{_num(reformulated['revenue'][-1])}m {currency}"},
    ]

    est_str = _analyst_next_rev(fmp_data.get("estimates", []))
    if est_str:
        exec_rows.append({"indicator": "Consensus Revenue",  "Value": est_str})

    exec_rows += [
        {"indicator": "",                                        "Value": ""},
        {"indicator": f"Revenue CAGR ({cagr_label})",           "Value": _pct(rev_cagr)},
        {"indicator": f"NOPAT Margin ({n_avg_yrs}yr avg)",      "Value": _pct(og_avg)},
        {"indicator": "Confidence",                             "Value": _confidence(upside, reformulated)},
        {"indicator": "Last Updated",                           "Value": _last_updated(fmp_data, ltm_date)},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — Valuation Summary",
        "note": (
            f"Fair value range = Bear {bear_price:.0f} / Base {base_price:.0f} / Bull {bull_price:.0f} {currency}. "
            f"WACC {_pct(wacc)}, terminal growth {_pct(base_sc['g'])}. "
            f"Penman DCF: FCF = NOPAT − ΔNOA. Data: FMP. Valuation is model output, not a factual result."
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Value"], "rows": exec_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 2 — Financial Snapshot (FY2021A–FY2025A + LTM)
    # ══════════════════════════════════════════════════════════════════════════
    n_show   = min(5, len(years))
    show_yrs = years[-n_show:]
    show_idx = [years.index(y) for y in show_yrs]

    # Annual FMP rows ordered oldest→newest for the shown window
    annual_rows = list(reversed(fmp_data["income"][:n_show]))

    yr_cols: list[str] = [_fy_label(y) for y in show_yrs]

    # LTM column
    ltm_col = _ltm_label(ltm_inc.get("date", "")) if has_ltm else None
    if ltm_col:
        yr_cols.append(ltm_col)

    # LTM computed values
    ltm_rev = float(ltm_inc.get("revenue") or 0) if has_ltm else None
    ltm_noa, ltm_nfo = _ltm_noa_nfo(ltm_bal, ltm_rev or 0.0) if has_ltm else (None, None)
    ltm_oi  = float(ltm_inc.get("operatingIncome") or 0) * (1 - t) if has_ltm else None
    ltm_fcf = (float(ltm_cf.get("freeCashFlow") or 0) or
               float((ltm_cf.get("operatingCashFlow") or 0) +
                     (ltm_cf.get("capitalExpenditure") or 0))) if has_ltm else None
    if has_ltm and ltm_fcf == 0:
        ltm_fcf = None
    prev_noa_for_ltm = reformulated["NOA"][-1] if reformulated["NOA"] else None
    ltm_avg_noa  = ((ltm_noa + prev_noa_for_ltm) / 2
                    if ltm_noa is not None and prev_noa_for_ltm else ltm_noa)
    ltm_rnoa = (ltm_oi / ltm_avg_noa if ltm_oi and ltm_avg_noa else None)
    ltm_og   = (ltm_oi / ltm_rev if ltm_oi and ltm_rev else None)
    ltm_ato  = (ltm_rev / ltm_avg_noa if ltm_rev and ltm_avg_noa else None)
    # SPREAD = RNOA − NBC; compute LTM NBC from interest expense / avg NFO
    ltm_nbc = None
    if ltm_nfo is not None and ltm_nfo != 0:
        ltm_int_ex  = float(ltm_inc.get("interestExpense") or 0)
        prior_nfo   = reformulated["NFO"][-1] if reformulated["NFO"] else 0
        avg_ltm_nfo = (ltm_nfo + prior_nfo) / 2 if prior_nfo else ltm_nfo
        if avg_ltm_nfo != 0:
            ltm_nbc = (ltm_int_ex * (1 - t)) / avg_ltm_nfo
    ltm_spread = (ltm_rnoa - ltm_nbc) if (ltm_rnoa is not None and ltm_nbc is not None) else None

    def _snap_row(label, hist_vals, fmt_fn, ltm_val=None):
        row = {"indicator": label}
        for ci, (col, idx) in enumerate(zip(yr_cols[:n_show], show_idx)):
            v = hist_vals[idx]
            row[col] = fmt_fn(v) if v is not None else "—"
        if ltm_col and ltm_val is not None:
            row[ltm_col] = fmt_fn(ltm_val)
        elif ltm_col:
            row[ltm_col] = "—"
        return row

    snap_rows = [
        _snap_row(f"Revenue ({currency}m)",          reformulated["revenue"],  _num,  ltm_rev),
        _snap_row(f"NOPAT ({currency}m)",            reformulated["OI"],       _num,  ltm_oi),
        _snap_row(f"Cash FCF ({currency}m)",         reformulated["cash_fcf"], _num,  ltm_fcf),
        _snap_row(f"NOA ({currency}m)",              reformulated["NOA"],      _num,  ltm_noa),
        _snap_row(f"NFO ({currency}m)",              reformulated["NFO"],      _num,  ltm_nfo),
        _snap_row("RNOA",                            reformulated["RNOA"],     _pct,  ltm_rnoa),
        _snap_row("NOPAT Margin",                    reformulated["OG"],       _pct,  ltm_og),
        _snap_row("Asset Turnover (ATO)",            reformulated["ATO"],      _x,    ltm_ato),
        _snap_row("SPREAD (RNOA − NBC)",             reformulated["SPREAD"],   _pct,  ltm_spread),
    ]

    # Collect any anomaly notes
    _notes = []
    neg_noa_yrs = [y for y in show_yrs if reformulated["NOA"][years.index(y)] <= 0]
    if neg_noa_yrs:
        _notes.append(
            f"NOA ≤ 0 in {', '.join(str(y) for y in neg_noa_yrs)} — "
            f"RNOA/ATO excluded from averages."
        )
    if any("NOA steg" in f for f in reformulated.get("flags", [])):
        _notes.append(f"NOA anomaly in {show_yrs[-1]} — DCF uses ATO-normalised starting NOA.")

    snap_note = (
        f"NOPAT = EBIT × (1−t), t = {_pct(t)} statutory (normalized, not effective rate). "
        f"Penman FCF = NOPAT − ΔNOA; Cash FCF = OCF − CapEx. "
        f"NOA = Operating Assets − Operating Liabilities. "
        f"NFO = Net Financial Obligations (term debt + lease liabilities − excess cash − marketable securities). "
        f"Negative NFO = net cash position. "
        + (" ".join(_notes) if _notes else "")
    )

    specs.append({
        "type": "D",
        "title": f"{company_name} — Financial Snapshot",
        "note": snap_note,
        "kilde": kilde,
        "table_data": {"columns": yr_cols, "rows": snap_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 3 — Revenue & Operating Income Trend (line chart)
    # ══════════════════════════════════════════════════════════════════════════
    lbl_rev = f"{ticker} — Revenue ({currency}m)"
    lbl_oi  = f"{ticker} — NOPAT ({currency}m)"
    dfs[lbl_rev] = _ts(years, reformulated["revenue"], lbl_rev)
    dfs[lbl_oi]  = _ts(years, reformulated["OI"],      lbl_oi)

    df_trend = dfs[lbl_rev].join(dfs[lbl_oi])
    dfs["trend_rev_oi"] = df_trend

    specs.append({
        "type": "A", "freq": "A",
        "title": f"{company_name} — Revenue & NOPAT ({currency}m)",
        "y_label": f"{currency}m",
        "series_labels": ["trend_rev_oi"],
        "note": (
            f"Revenue CAGR = {_pct(rev_cagr)} ({cagr_label}, organic, M&A-adjusted). "
            f"NOPAT = EBIT × (1−t = {_pct(t)}) — after-tax operating income (not GAAP operating income)."
        ),
        "kilde": kilde,
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 4 — WACC Calculation
    # ══════════════════════════════════════════════════════════════════════════
    MRP = wacc_data["MRP"]

    wacc_rows = [
        {"indicator": "Risk-free Rate",         "Parameter": "rf",     "Value": _pct(wacc_data["rf"]),
         "Source": f"{rf_entry['bond_name']} (spot)"},
        {"indicator": "Beta (raw)",             "Parameter": "β",      "Value": f"{wacc_data['beta_raw']:.4f}",
         "Source": "FMP /profile"},
        {"indicator": "Beta (Blume adj.)",      "Parameter": "β_adj",  "Value": f"{wacc_data['beta_adj']:.4f}",
         "Source": "2/3 × β + 1/3"},
        {"indicator": "Equity Risk Premium",    "Parameter": "MRP",    "Value": _pct(MRP),
         "Source": "Damodaran US mature-market ERP"},
        {"indicator": "Country Risk Premium",   "Parameter": "CRP",    "Value": _pct(wacc_data["CRP"]),
         "Source": f"Damodaran {iso3}"},
        {"indicator": "Cost of Equity",         "Parameter": "rE",     "Value": _pct(wacc_data["rE"]),
         "Source": "rf + β_adj × (MRP + CRP)"},
        {"indicator": "Credit Spread",          "Parameter": "rs",     "Value": _pct(wacc_data["rs"]),
         "Source": wacc_data["rating"] or "ICR fallback"},
        {"indicator": "Tax Rate",               "Parameter": "t",      "Value": _pct(wacc_data["t"]),
         "Source": f"Statutory {iso3}"},
        {"indicator": "Cost of Debt (after-tax)", "Parameter": "rD",   "Value": _pct(wacc_data["rD"]),
         "Source": "(rf + rs) × (1 − t)"},
        {"indicator": "Equity Weight",          "Parameter": "E/V",    "Value": _pct(wacc_data["E"] / wacc_data["V"]),
         "Source": "Market cap / (E + D)"},
        {"indicator": "Debt Weight",            "Parameter": "D/V",    "Value": _pct(wacc_data["D"] / wacc_data["V"]),
         "Source": "NFO / (E + D)"},
        {"indicator": "━━ WACC",               "Parameter": "WACC",   "Value": _pct(wacc),
         "Source": "E/V × rE + D/V × rD"},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — WACC",
        "note": (
            f"WACC = {_pct(wacc)}. "
            f"rf = {rf_entry['bond_name']} spot yield ({iso3}). "
            f"MRP = Damodaran US mature-market ERP = {_pct(MRP)}. "
            f"Beta adjusted via Blume (1975)."
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Parameter", "Value", "Source"], "rows": wacc_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 5 — DCF Scenarios: Bear / Base / Bull
    # ══════════════════════════════════════════════════════════════════════════
    def _sc_price_str(sc_name):
        sc = dcf_scenarios[sc_name]
        vs = (sc["price"] - price) / price if price > 0 else 0
        return f"{sc['price']:.0f} {currency}  ({vs:+.0%})"

    sc_rows = [
        {"indicator": "Revenue Growth (CAGR)",
         "Bear": _pct(bear_sc["cagr"]), "Base": _pct(base_sc["cagr"]), "Bull": _pct(bull_sc["cagr"])},
        {"indicator": "Operating Margin",
         "Bear": _pct(bear_sc["og"]), "Base": _pct(base_sc["og"]), "Bull": _pct(bull_sc["og"])},
        {"indicator": "WACC",
         "Bear": _pct(bear_sc["wacc"]), "Base": _pct(base_sc["wacc"]), "Bull": _pct(bull_sc["wacc"])},
        {"indicator": "Terminal Growth",
         "Bear": _pct(bear_sc["g"]), "Base": _pct(base_sc["g"]), "Bull": _pct(bull_sc["g"])},
        {"indicator": ""},
        {"indicator": f"Enterprise Value ({currency}m)",
         "Bear": _num(bear_sc["detail"]["EV"]),
         "Base": _num(base_sc["detail"]["EV"]),
         "Bull": _num(bull_sc["detail"]["EV"])},
        {"indicator": f"Fair Value / Share ({currency})",
         "Bear": f"{bear_price:.0f}", "Base": f"{base_price:.0f}", "Bull": f"{bull_price:.0f}"},
        {"indicator": "vs. Current Price",
         "Bear": f"{(bear_price - price)/price if price > 0 else 0:+.1%}",
         "Base": f"{(base_price - price)/price if price > 0 else 0:+.1%}",
         "Bull": f"{(bull_price - price)/price if price > 0 else 0:+.1%}"},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — DCF Scenarios",
        "note": (
            f"Penman FCF = OI − ΔNOA. 5-year forecast + Gordon Growth terminal value. "
            f"Bear: low growth, compressed margins, higher WACC. "
            f"Bull: higher growth, expanding margins, lower WACC. "
            f"Current price = {price:.2f} {currency}."
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Bear", "Base", "Bull"], "rows": sc_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 6 — Sensitivity: Fair Value / Share over WACC × g
    # ══════════════════════════════════════════════════════════════════════════
    wacc_axis  = sensitivity["wacc_axis"]
    g_axis     = sensitivity["g_axis"]
    wacc_base  = sensitivity["wacc_base"]
    g_base     = sensitivity["g_base"]
    sens_cols  = [_pct(w, decimals=2) for w in wacc_axis]
    sens_rows  = []
    for ri, g in enumerate(g_axis):
        row = {"indicator": f"g = {_pct(g)}"}
        for ci, w in enumerate(wacc_axis):
            val = sensitivity["grid"][ri][ci]
            cell = f"{val:.0f}" if val is not None else "—"
            if abs(w - wacc_base) < 1e-6 and abs(g - g_base) < 1e-6:
                cell = f"★ {cell}"
            row[_pct(w, 2)] = cell
        sens_rows.append(row)

    specs.append({
        "type": "D",
        "title": f"{company_name} — Sensitivity: Fair Value / Share ({currency})",
        "note": (
            f"Columns = WACC. Rows = terminal growth g. "
            f"★ = base case (WACC = {_pct(wacc_base)}, g = {_pct(g_base)}). "
            f"Range: WACC ± 1 ppt in 0.25 ppt steps, g 1–3%."
        ),
        "kilde": kilde,
        "table_data": {"columns": sens_cols, "rows": sens_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 7 — Market Multiples
    # ══════════════════════════════════════════════════════════════════════════
    m       = (fmp_data.get("metrics") or [{}])[0]
    mkt_cap = float(profile.get("marketCap") or profile.get("mktCap") or 0)
    _inc0   = (fmp_data.get("income") or [{}])[0]
    _bal0   = (fmp_data.get("balance") or [{}])[0]
    _rev    = float(_inc0.get("revenue") or 0)
    _equity = float(_bal0.get("totalStockholdersEquity") or 0)
    pb_val  = m.get("pbRatio") or (mkt_cap / _equity if _equity else None)
    ps_val  = m.get("priceToSalesRatio") or (mkt_cap / _rev if _rev else None)

    mult_rows = [
        {"indicator": "P/E",       "Trailing": f"{m['peRatio']:.1f}x"    if m.get("peRatio")    else "N/A"},
        {"indicator": "EV/EBITDA", "Trailing": f"{m['evToEbitda']:.1f}x" if m.get("evToEbitda") else "N/A"},
        {"indicator": "P/B",       "Trailing": f"{pb_val:.1f}x"          if pb_val              else "N/A"},
        {"indicator": "P/S",       "Trailing": f"{ps_val:.1f}x"          if ps_val              else "N/A"},
        {"indicator": "EV/FCF",    "Trailing": f"{m['evToFCF']:.1f}x"    if m.get("evToFCF")    else "N/A"},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — Market Multiples",
        "note": "Trailing multiples from FMP. P/B and P/S computed from market cap if not directly available.",
        "kilde": kilde,
        "table_data": {"columns": ["Trailing"], "rows": mult_rows},
    })

    return specs, dfs

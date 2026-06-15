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
    if abs(v) >= 1_000_000:
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
        fmt = d.strftime("%b'%y")
        return f"LTM {fmt}"
    except Exception:
        return "LTM"


def _last_updated(fmp_data: dict, ltm_date: str = "") -> str:
    date_str = ltm_date or (fmp_data.get("income") or [{}])[0].get("date", "")
    if not date_str:
        return "N/A"
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        suffix = " (LTM)" if ltm_date else " (Årsregnskab)"
        return d.strftime("%d %b %Y") + suffix
    except Exception:
        return date_str[:10]


def _confidence(upside: float, reformulated: dict) -> str:
    flags = reformulated.get("flags", [])
    bad   = sum(1 for f in flags if "negativ" in f.lower() or "anomali" in f.lower())
    if bad > 2 or abs(upside) > 1.0:
        return "Lav — datakvalitetsproblemer påvist"
    if bad > 0 or abs(upside) > 0.5:
        return "Middel — valider balanceklassificering"
    return "Middel — standard DCF-usikkerhed"


def _analyst_next_rev(estimates: list):
    from datetime import date as _date
    today_str = _date.today().isoformat()
    # Keep only future estimates with a valid revenue avg
    valid = sorted(
        [e for e in (estimates or [])
         if (e.get("estimatedRevenueAvg") or 0) > 0
         and (e.get("date") or "") >= today_str],
        key=lambda x: x.get("date", ""),
    )
    if not valid:
        return None
    e  = valid[0]
    lo = e.get("estimatedRevenueLow",  0) or 0
    av = e.get("estimatedRevenueAvg",  0) or 0
    hi = e.get("estimatedRevenueHigh", 0) or 0
    yr = (e.get("date") or "")[:4]
    label = f"FY{yr}E" if yr else "Næste FY"
    if lo and hi:
        return f"{label}: {_num(av)}m  ({_num(lo)}–{_num(hi)}m)"
    return f"{label}: {_num(av)}m"


# ── LTM balance-sheet derived metrics ────────────────────────────────────────

def _ltm_noa_nfo(ltm_bal: dict, ltm_revenue: float = 0.0):
    if not ltm_bal:
        return None, None, None, None, None, None
    def s(k):
        return float(ltm_bal.get(k) or 0)
    cash_total    = s("cashAndCashEquivalents")
    op_cash_floor = 0.02 * ltm_revenue
    excess_cash   = max(0.0, cash_total - op_cash_floor)
    fin_assets = excess_cash + s("shortTermInvestments") + s("longTermInvestments")
    fin_liabs  = s("shortTermDebt") + s("longTermDebt") + s("capitalLeaseObligations")
    op_assets  = s("totalAssets") - fin_assets
    op_liabs   = s("totalLiabilities") - fin_liabs
    return (op_assets - op_liabs, fin_liabs - fin_assets,
            op_assets, op_liabs, fin_liabs, fin_assets)


# ── Sector valuation benchmarks (Damodaran / market consensus ranges) ─────────

_SECTOR_BENCHMARKS: dict = {
    "Technology":             {"pe": "22–35×", "ev_ebitda": "18–28×"},
    "Consumer Cyclical":      {"pe": "18–25×", "ev_ebitda": "10–16×"},
    "Healthcare":             {"pe": "18–25×", "ev_ebitda": "13–20×"},
    "Financial Services":     {"pe": "10–16×", "ev_ebitda": "N/A"},
    "Energy":                 {"pe": "10–15×", "ev_ebitda": "5–9×"},
    "Utilities":              {"pe": "14–20×", "ev_ebitda": "8–12×"},
    "Communication Services": {"pe": "16–26×", "ev_ebitda": "9–15×"},
    "Consumer Defensive":     {"pe": "18–24×", "ev_ebitda": "11–16×"},
    "Industrials":            {"pe": "17–25×", "ev_ebitda": "11–17×"},
    "Real Estate":            {"pe": "28–50×", "ev_ebitda": "16–22×"},
    "Basic Materials":        {"pe": "12–20×", "ev_ebitda": "7–11×"},
    "_default":               {"pe": "15–25×", "ev_ebitda": "10–18×"},
}


# ── Main builder ─────────────────────────────────────────────────────────────

def build_chart_specs(
    ticker: str, company_name: str, hq_country: str,
    reformulated: dict, wacc_data: dict, dcf_scenarios: dict,
    sensitivity: dict, fmp_data: dict,
) -> tuple:

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

    ltm_inc = fmp_data.get("ltm_income",   {}) or {}
    ltm_cf  = fmp_data.get("ltm_cashflow", {}) or {}
    ltm_bal = fmp_data.get("ltm_balance",  {}) or {}
    has_ltm = bool(ltm_inc.get("revenue"))

    dfs: dict = {}
    specs = []

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 1 — Executive Summary
    # ══════════════════════════════════════════════════════════════════════════
    upside     = (base_price - price) / price if price > 0 else 0
    nfo_latest = reformulated["NFO"][-1]
    net_cash   = -nfo_latest
    nc_str     = (f"+{_num(net_cash)}m (nettokasse)" if net_cash >= 0
                  else f"{_num(net_cash)}m (nettogæld)")

    rev_cagr   = reformulated["historical_avgs"]["revenue_cagr"]
    og_avg     = reformulated["historical_avgs"]["OG"]
    fy_latest  = _fy_label(years[-1])
    n_avg_yrs  = reformulated.get("n_avg_years", len(years))
    cagr_label = f"FY{years[0]}–FY{years[-1]}"
    ltm_date   = ltm_inc.get("date", "") if has_ltm else ""

    # Gross debt from most recent annual balance sheet
    _b0 = fmp_data.get("balance", [{}])[0] if fmp_data.get("balance") else {}
    _gross_debt = (float(_b0.get("shortTermDebt") or 0)
                   + float(_b0.get("longTermDebt") or 0)
                   + float(_b0.get("capitalLeaseObligations") or 0))
    _gross_debt_str = f"{_num(_gross_debt)}m {currency}" if _gross_debt > 0 else f"0m {currency}"

    exec_rows = [
        {"indicator": "Aktuel kurs",                 "Værdi": f"{price:.2f} {currency}"},
        {"indicator": "Fair value-interval",         "Værdi": f"{bear_price:.0f} – {bull_price:.0f} {currency}"},
        {"indicator": "Basis fair value",            "Værdi": f"{base_price:.2f} {currency}"},
        {"indicator": "Op-/nedside",                 "Værdi": f"{upside:+.1%}"},
        {"indicator": "",                            "Værdi": ""},
        {"indicator": "WACC",                        "Værdi": _pct(wacc)},
        {"indicator": "Terminal vækst",              "Værdi": _pct(base_sc["g"])},
        {"indicator": "Bruttogæld",                  "Værdi": _gross_debt_str},
        {"indicator": "Netto finansiel stilling",    "Værdi": nc_str},
        {"indicator": f"{fy_latest} Omsætning",      "Værdi": f"{_num(reformulated['revenue'][-1])}m {currency}"},
    ]

    est_str = _analyst_next_rev(fmp_data.get("estimates", []))
    if est_str:
        exec_rows.append({"indicator": "Konsensus omsætning", "Værdi": est_str})

    exec_rows += [
        {"indicator": "",                                        "Værdi": ""},
        {"indicator": f"Omsætnings-CAGR ({cagr_label})",       "Værdi": _pct(rev_cagr)},
        {"indicator": f"NOPAT-margin ({n_avg_yrs}år gns.)",    "Værdi": _pct(og_avg)},
        {"indicator": "Konfidensgrad",                          "Værdi": _confidence(upside, reformulated)},
        {"indicator": "Senest opdateret",                       "Værdi": _last_updated(fmp_data, ltm_date)},
    ]

    # DCF-implied multiples vs sector benchmarks
    _shares_m  = float(fmp_data["income"][0].get("weightedAverageShsOutDil") or 1)
    _eps       = float(fmp_data["income"][0].get("epsDiluted") or 0)
    _ebitda_m  = float(fmp_data["income"][0].get("ebitda") or 0) or float(fmp_data["income"][0].get("operatingIncome") or 0)
    _dcf_ev    = base_price * _shares_m + nfo_latest
    _dcf_pe    = f"{base_price / _eps:.1f}×"    if _eps > 0      else "N/A"
    _dcf_ev_eb = f"{_dcf_ev / _ebitda_m:.1f}×"  if _ebitda_m > 0 else "N/A"
    _sector    = profile.get("sector", "_default")
    _bench     = _SECTOR_BENCHMARKS.get(_sector, _SECTOR_BENCHMARKS["_default"])

    exec_rows += [
        {"indicator": "",                                    "Værdi": ""},
        {"indicator": "━━ DCF-afledte nøgletal",            "Værdi": ""},
        {"indicator": "DCF Implied P/E",                    "Værdi": _dcf_pe},
        {"indicator": "DCF Implied EV/EBITDA",              "Værdi": _dcf_ev_eb},
        {"indicator": f"Sektorbenchmark P/E ({_sector})",   "Værdi": _bench["pe"]},
        {"indicator": "Sektorbenchmark EV/EBITDA",          "Værdi": _bench["ev_ebitda"]},
    ]

    # Note: separate upside/downside explanation avoids contradicting the general model note
    if price > 0 and abs(upside) > 0.50:
        if upside < 0:
            _model_note = (
                f"Penman opgør kun regnskabsmæssig kapital — brand, platform og IP fremgår ikke af balancen. "
                f"{upside:+.0%} nedside er typisk for immaterielintensive selskaber og afspejler ikke nødvendigvis fejlprissætning."
            )
        else:
            _model_note = (
                f"{upside:+.0%} opside: verificer NOA-klassificering og datakomplethed inden der handles på signalet."
            )
    else:
        _model_note = (
            f"Basis fair value inden for 0,1×–10× af markedsprisen er modelkonsistent; "
            f"større afvigelse skyldes typisk immaterielle aktiver ikke optaget på balancen."
        )

    _exec_note = f"Penman DCF-værdiansættelse. Kilde: FMP og Damodaran."

    specs.append({
        "type": "D",
        "title": f"{company_name} — Værdiansættelsesoversigt",
        "note": _exec_note,
        "kilde": kilde,
        "table_data": {"columns": ["Værdi"], "rows": exec_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 2 — Financial Snapshot (FY + LTM)
    # ══════════════════════════════════════════════════════════════════════════
    n_show   = min(5, len(years))
    show_yrs = years[-n_show:]
    show_idx = [years.index(y) for y in show_yrs]

    yr_cols: list = [_fy_label(y) for y in show_yrs]
    ltm_col = _ltm_label(ltm_inc.get("date", "")) if has_ltm else None
    if ltm_col:
        yr_cols.append(ltm_col)

    ltm_rev = float(ltm_inc.get("revenue") or 0) if has_ltm else None
    (ltm_noa, ltm_nfo,
     ltm_op_assets, ltm_op_liabs,
     ltm_gross_debt, ltm_fin_assets) = (
        _ltm_noa_nfo(ltm_bal, ltm_rev or 0.0) if has_ltm
        else (None, None, None, None, None, None)
    )
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
    ltm_nbc  = None
    if ltm_nfo is not None and ltm_nfo != 0:
        ltm_int_ex  = float(ltm_inc.get("interestExpense") or 0)
        prior_nfo   = reformulated["NFO"][-1] if reformulated["NFO"] else 0
        avg_ltm_nfo = (ltm_nfo + prior_nfo) / 2 if prior_nfo else ltm_nfo
        if avg_ltm_nfo != 0:
            ltm_nbc = (ltm_int_ex * (1 - t)) / avg_ltm_nfo
    ltm_spread = (ltm_rnoa - ltm_nbc) if (ltm_rnoa is not None and ltm_nbc is not None) else None

    ltm_gross_profit = float(ltm_inc.get("grossProfit") or 0) if has_ltm else None
    ltm_ebit         = float(ltm_inc.get("operatingIncome") or 0) if has_ltm else None
    ltm_dna          = float(ltm_cf.get("depreciationAndAmortization") or 0) if has_ltm else None
    ltm_capex_raw    = float(ltm_cf.get("capitalExpenditure") or 0) if has_ltm else None
    ltm_capex_abs    = abs(ltm_capex_raw) if ltm_capex_raw is not None else None
    ltm_dnwc         = float(ltm_cf.get("changeInWorkingCapital") or 0) if has_ltm else None

    def _snap_row(label, hist_vals, fmt_fn, ltm_val=None):
        row = {"indicator": label}
        for col, idx in zip(yr_cols[:n_show], show_idx):
            v = hist_vals[idx]
            row[col] = fmt_fn(v) if v is not None else "—"
        if ltm_col and ltm_val is not None:
            row[ltm_col] = fmt_fn(ltm_val)
        elif ltm_col:
            row[ltm_col] = "—"
        return row

    def _sep(label):
        row = {"indicator": f"━━ {label}"}
        for col in yr_cols:
            row[col] = ""
        return row

    capex_abs_hist = [abs(v) if v is not None else None
                      for v in reformulated.get("capex", [None] * len(years))]

    snap_rows = [
        # ── P&L ──────────────────────────────────────────────────────────────────
        _sep("Resultatopgørelse"),
        _snap_row(f"Omsætning ({currency}m)",             reformulated["revenue"],      _num, ltm_rev),
        _snap_row(f"Bruttoavance ({currency}m)",          reformulated["gross_profit"], _num, ltm_gross_profit),
        _snap_row(f"EBIT ({currency}m)",                  reformulated["ebit"],         _num, ltm_ebit),
        _snap_row(f"NOPAT ({currency}m)",                 reformulated["OI"],           _num, ltm_oi),
        _snap_row("NOPAT-margin",                         reformulated["OG"],           _pct, ltm_og),

        # ── FCF bridge (fra NOPAT) ────────────────────────────────────────────────
        _sep("FCF (fra NOPAT)"),
        _snap_row(f"+ D&A ({currency}m)",                 reformulated["dna"],          _num, ltm_dna),
        _snap_row(f"− CapEx ({currency}m)",               capex_abs_hist,               _num, ltm_capex_abs),
        _snap_row(f"± ΔNWC ({currency}m)",                reformulated["dnwc"],         _num, ltm_dnwc),
        _snap_row(f"= Cash FCF ({currency}m)",            reformulated["cash_fcf"],     _num, ltm_fcf),

        # ── Kapitalstruktur ───────────────────────────────────────────────────────
        _sep("Kapitalstruktur"),
        _snap_row(f"Driftsaktiver ({currency}m)",         reformulated["op_assets"],    _num, ltm_op_assets),
        _snap_row(f"− Driftsforpligtelser ({currency}m)", reformulated["op_liabs"],     _num, ltm_op_liabs),
        _snap_row(f"= NOA ({currency}m)",                 reformulated["NOA"],          _num, ltm_noa),
        _snap_row(f"Bruttogæld ({currency}m)",            reformulated["gross_debt"],   _num, ltm_gross_debt),
        _snap_row(f"− Finansielle aktiver ({currency}m)", reformulated["fin_assets"],   _num, ltm_fin_assets),
        _snap_row(f"= NFO ({currency}m)",                 reformulated["NFO"],          _num, ltm_nfo),

        # ── Afkastnøgletal ────────────────────────────────────────────────────────
        _sep("Afkastnøgletal"),
        _snap_row("RNOA",                                 reformulated["RNOA"],         _pct, ltm_rnoa),
        _snap_row("Aktivomsætning (ATO)",                 reformulated["ATO"],          _x,   ltm_ato),
        _snap_row("SPREAD (RNOA − NBC)",                  reformulated["SPREAD"],       _pct, ltm_spread),
    ]

    _notes = []
    neg_noa_yrs = [y for y in show_yrs if reformulated["NOA"][years.index(y)] <= 0]
    if neg_noa_yrs:
        _notes.append(
            f"NOA ≤ 0 i {', '.join(str(y) for y in neg_noa_yrs)} — RNOA/ATO udeladt fra gennemsnit."
        )
    if any("NOA steg" in f for f in reformulated.get("flags", [])):
        _notes.append(f"NOA-anomali i {show_yrs[-1]} — DCF anvender ATO-normaliseret start-NOA.")
    # Extreme RNOA: asset-light / platform companies where NOA << earnings
    _rnoa_vals = [v for v in reformulated["RNOA"] if v is not None]
    if _rnoa_vals and max(_rnoa_vals) > 1.0:
        _notes.append(
            f"RNOA >100% indikerer at selskabet skaber meget overskud relativt til regnskabsmæssig kapital "
            f"— typisk for platform- og teknologiselskaber med store immaterielle aktiver (brand, IP) "
            f"der ikke aktiveres i balancen. Penman-modellen undervurderer NOA for disse selskaber."
        )

    _penman_fcf = reformulated["FCF"][-1]
    _cash_fcf   = reformulated["cash_fcf"][-1]
    _latest_yr  = years[-1]
    if (_penman_fcf is not None and _cash_fcf is not None
            and _penman_fcf != 0 and abs((_cash_fcf - _penman_fcf) / abs(_penman_fcf)) > 0.20):
        _gap_pct   = (_cash_fcf - _penman_fcf) / abs(_penman_fcf)
        _direction = "højere" if _gap_pct > 0 else "lavere"
        _delta_noa = (reformulated["NOA"][-1] - reformulated["NOA"][-2]
                      if len(reformulated["NOA"]) >= 2 else 0)
        _notes.append(
            f"FY{_latest_yr}: Cash FCF ({_num(_cash_fcf)}m) er {abs(_gap_pct):.0%} {_direction} end Penman FCF "
            f"({_num(_penman_fcf)}m). Forskellen drives af ΔNOA = {_num(_delta_noa)}m — modellen fratrækker "
            f"NOA-vækst som reinvesteret kapital. Cash FCF er det mest direkte likviditetsmål."
        )

    snap_note = (
        f"P&L: Bruttoavance = Omsætning − COGS. EBIT = driftsoverskud før skat. "
        f"NOPAT = EBIT × (1−t = {_pct(t)} lovpligtig) — driftsoverskud efter skat, uafhæng af kapitalstruktur. "
        f"FCF: Cash FCF = NOPAT + D&A − CapEx ± ΔNWC (rapporterede pengestrømsopgørelsesværdier; "
        f"øvrige poster, fx udskudt skat og aktiebaseret vederlæggelse, indgår ikke i broen). "
        f"Kapital: NOA = Driftsaktiver − Driftsforpligtelser. "
        f"NFO = Bruttogæld − Finansielle aktiver; negativ = nettokasse. "
        f"Benchmarks: NOPAT-margin >10%, ATO >1×. SPREAD > 0 er værdiskabende finansiel gearing. "
        + (" ".join(_notes) if _notes else "")
    )

    if False:  # Regnskabsoversigt — full financial statements, not for analysts
        specs.append({
            "type": "D",
            "title": f"{company_name} — Regnskabsoversigt",
            "note": snap_note,
            "kilde": kilde,
            "table_data": {"columns": yr_cols, "rows": snap_rows},
        })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 3 — Revenue & NOPAT Trend
    # ══════════════════════════════════════════════════════════════════════════
    # Auto-scale: if any revenue value exceeds 10,000m, display in billions
    _max_rev = max((v for v in reformulated["revenue"] if v is not None), default=0)
    _use_bn  = _max_rev > 10_000
    _scale_f = 1_000 if _use_bn else 1
    _unit    = f"{currency}mia." if _use_bn else f"{currency}m"

    _rev_scaled = [v / _scale_f if v is not None else None for v in reformulated["revenue"]]
    _oi_scaled  = [v / _scale_f if v is not None else None for v in reformulated["OI"]]

    lbl_rev = f"{ticker} — Omsætning ({_unit})"
    lbl_oi  = f"{ticker} — NOPAT ({_unit})"
    dfs[lbl_rev] = _ts(years, _rev_scaled, lbl_rev)
    dfs[lbl_oi]  = _ts(years, _oi_scaled,  lbl_oi)
    dfs["trend_rev_oi"] = dfs[lbl_rev].join(dfs[lbl_oi])

    specs.append({
        "type": "A", "freq": "A",
        "title": f"{company_name} — Omsætning & NOPAT ({_unit})",
        "x_label": "Regnskabsår",
        "y_label": _unit,
        "series_labels": ["trend_rev_oi"],
        "note": f"Omsætning og NOPAT, FY{years[0]}–FY{years[-1]}. Kilde: FMP.",
        "kilde": kilde,
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 4 — WACC
    # ══════════════════════════════════════════════════════════════════════════
    MRP = wacc_data["MRP"]

    wacc_rows = [
        {"indicator": "Risikofri rente",             "Parameter": "rf",    "Værdi": _pct(wacc_data["rf"]),
         "Kilde": f"{rf_entry['bond_name']} (spot)"},
        {"indicator": "Beta (rå)",                   "Parameter": "β",     "Værdi": f"{wacc_data['beta_raw']:.4f}",
         "Kilde": "FMP /profile"},
        {"indicator": "Beta (Blume-just.)",          "Parameter": "β_adj", "Værdi": f"{wacc_data['beta_adj']:.4f}",
         "Kilde": "2/3 × β_raw + 1/3 × 1"},
        {"indicator": "Aktierisikopræmie",           "Parameter": "MRP",   "Værdi": _pct(MRP),
         "Kilde": "Damodaran US mature-market ERP"},
        {"indicator": "Landerisikopræmie",           "Parameter": "CRP",   "Værdi": _pct(wacc_data["CRP"]),
         "Kilde": f"Damodaran {iso3}"},
        {"indicator": "Egenkapitalomkostning",       "Parameter": "rE",    "Værdi": _pct(wacc_data["rE"]),
         "Kilde": "rf + β_adj × (MRP + CRP)"},
        {"indicator": "Kreditspænd",                 "Parameter": "rs",    "Værdi": _pct(wacc_data["rs"]),
         "Kilde": wacc_data["rating"] or "ICR fallback"},
        {"indicator": "Skattesats",                  "Parameter": "t",     "Værdi": _pct(wacc_data["t"]),
         "Kilde": f"Lovpligtig ({iso3}) — ikke effektiv sats"},
        {"indicator": "Låneomkostning (efter skat)", "Parameter": "rD",    "Værdi": _pct(wacc_data["rD"]),
         "Kilde": "(rf + rs) × (1 − t)"},
        {"indicator": "Egenkapitalvægt",             "Parameter": "E/V",   "Værdi": _pct(wacc_data["E"] / wacc_data["V"]),
         "Kilde": "Markedsværdi / (E + D)"},
        {"indicator": "Gældsvægt",                   "Parameter": "D/V",   "Værdi": _pct(wacc_data["D"] / wacc_data["V"]),
         "Kilde": "NFO / (E + D)" if wacc_data["D"] > 0 else "Nettokasse → D=0"},
        {"indicator": "━━ WACC",                    "Parameter": "WACC",  "Værdi": _pct(wacc),
         "Kilde": "E/V × rE + D/V × rD"},
    ]

    _crp_note = f"{_pct(wacc_data['CRP'])} (CRP = 0%)" if wacc_data["CRP"] == 0 else f"{_pct(MRP)} + CRP {_pct(wacc_data['CRP'])}"
    if False:  # WACC standalone table — detail for internal QA, not for analysts
        specs.append({
            "type": "D",
            "title": f"{company_name} — WACC",
            "note": (
                f"WACC = {_pct(wacc)} — diskonteringsrenten anvendt på alle fremtidige pengestrømme. "
                f"rf = {rf_entry['bond_name']} spotrente (fremadskuende). Beta Blume-justeret (2/3 × β_raw + 1/3 × 1). "
                f"MRP = Damodaran US-markedspræmie {_crp_note}. "
                f"Et WACC-skift på 1 ppt flytter fair value ~15–25%. Typisk interval: 7–10% investment-grade, 10–14% ved højere risiko."
            ),
            "kilde": kilde,
            "table_data": {"columns": ["Parameter", "Værdi", "Kilde"], "rows": wacc_rows},
        })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 5 — DCF Scenarios
    # ══════════════════════════════════════════════════════════════════════════
    sc_rows = [
        {"indicator": "Omsætningsvækst (CAGR)",
         "Bear": _pct(bear_sc["cagr"]), "Base": _pct(base_sc["cagr"]), "Bull": _pct(bull_sc["cagr"])},
        {"indicator": "NOPAT-margin",
         "Bear": _pct(bear_sc["og"]),   "Base": _pct(base_sc["og"]),   "Bull": _pct(bull_sc["og"])},
        {"indicator": "WACC",
         "Bear": _pct(bear_sc["wacc"]), "Base": _pct(base_sc["wacc"]), "Bull": _pct(bull_sc["wacc"])},
        {"indicator": "Terminal vækst",
         "Bear": _pct(bear_sc["g"]),    "Base": _pct(base_sc["g"]),    "Bull": _pct(bull_sc["g"])},
        {"indicator": ""},
        {"indicator": f"Virksomhedsværdi ({currency}m)",
         "Bear": _num(bear_sc["detail"]["EV"]),
         "Base": _num(base_sc["detail"]["EV"]),
         "Bull": _num(bull_sc["detail"]["EV"])},
        {"indicator": f"Fair value / aktie ({currency})",
         "Bear": f"{bear_price:.0f}", "Base": f"{base_price:.0f}", "Bull": f"{bull_price:.0f}"},
        {"indicator": "vs. Aktuel kurs",
         "Bear": f"{(bear_price - price)/price if price > 0 else 0:+.1%}",
         "Base": f"{(base_price - price)/price if price > 0 else 0:+.1%}",
         "Bull": f"{(bull_price - price)/price if price > 0 else 0:+.1%}"},
    ]

    _spread_pct = (bull_price - bear_price) / price if price > 0 else 0
    _spread_note = (
        f"Bear-til-bull spænd: {_num(bull_price - bear_price)} {currency} ({_spread_pct:+.0%} af markedskurs). "
        + ("Bredt spænd indikerer høj modelusikkerhed." if _spread_pct > 0.3 else "Relativt smalt spænd indikerer stabil, forudsigelig forretning.")
    )

    _dcf_note = f"5-årig Penman DCF, WACC {_pct(wacc)}, terminal vækst {_pct(base_sc['g'])}. Kilde: FMP."

    specs.append({
        "type": "D",
        "title": f"{company_name} — DCF-scenarier",
        "note": _dcf_note,
        "kilde": kilde,
        "table_data": {"columns": ["Bear", "Base", "Bull"], "rows": sc_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 6 — DCF Prognose (Basis) — transparency table
    # ══════════════════════════════════════════════════════════════════════════
    _bd         = base_sc["detail"]
    _rev_source_note = "analytikerkonsensus" if fmp_data.get("estimates") else "historisk CAGR"
    _pv_fcf_sum = _bd.get("total_PV", 0)
    _pv_tv      = _bd.get("PV_TV", 0)
    _ev_val     = _bd.get("EV", 0)
    _eq_val     = _bd.get("equity_value", 0)

    dcf_detail_rows = [
        {"indicator": "Omsætningsvækst (CAGR)",          "Basisscenarie": _pct(base_sc["cagr"])},
        {"indicator": "NOPAT-margin",                    "Basisscenarie": _pct(base_sc["og"])},
        {"indicator": "WACC",                            "Basisscenarie": _pct(base_sc["wacc"])},
        {"indicator": "Terminal vækst",                  "Basisscenarie": _pct(base_sc["g"])},
        {"indicator": ""},
        {"indicator": f"PV(FCF) sum ({currency}m)",      "Basisscenarie": _num(_pv_fcf_sum)},
        {"indicator": f"Terminalværdi PV ({currency}m)", "Basisscenarie": _num(_pv_tv)},
        {"indicator": f"Virksomhedsværdi ({currency}m)", "Basisscenarie": _num(_ev_val)},
        {"indicator": f"Egenkapitalværdi ({currency}m)", "Basisscenarie": _num(_eq_val)},
        {"indicator": f"Fair value / aktie ({currency})", "Basisscenarie": f"{base_price:.0f}"},
    ]

    if False:  # DCF Prognose (Basis) — redundant with DCF-scenarier, not for analysts
        specs.append({
            "type": "D",
            "title": f"{company_name} — DCF Prognose (Basis)",
            "note": (
                f"Basisscenarie: CAGR {_pct(base_sc['cagr'])} (baseret på {_rev_source_note}), "
                f"NOPAT-margin {_pct(base_sc['og'])} (historisk gennemsnit). "
                f"WACC {_pct(base_sc['wacc'])} og terminal vækst {_pct(base_sc['g'])} er modelindgange. "
                f"EV = PV(FCF) + PV(terminalværdi). Egenkapitalværdi = EV − NFO − NCI."
            ),
            "kilde": kilde,
            "table_data": {"columns": ["Basisscenarie"], "rows": dcf_detail_rows},
        })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 7 — Sensitivity
    # ══════════════════════════════════════════════════════════════════════════
    wacc_axis = sensitivity["wacc_axis"]
    g_axis    = sensitivity["g_axis"]
    wacc_base = sensitivity["wacc_base"]
    g_base    = sensitivity["g_base"]
    sens_cols = [_pct(w, decimals=2) for w in wacc_axis]
    sens_rows = []
    for ri, g in enumerate(g_axis):
        row = {"indicator": f"g = {_pct(g)}"}
        for ci, w in enumerate(wacc_axis):
            val  = sensitivity["grid"][ri][ci]
            cell = f"{val:.0f}" if val is not None else "—"
            # Use tolerance of 1e-4 to handle floating-point imprecision
            if abs(w - wacc_base) < 1e-4 and abs(g - g_base) < 1e-4:
                cell = f"★ {cell}"
            row[_pct(w, 2)] = cell
        sens_rows.append(row)

    # Best-case cell for investor insight
    _best_val = sensitivity["grid"][0][-1]  # lowest g, highest WACC (most conservative of top row)
    _best_note = ""
    if _best_val and price > 0:
        _best_updown = (_best_val - price) / price
        _best_note = f" Selv ved bedste scenarie ({sens_cols[-1]} WACC, g {_pct(g_axis[0])}) er fair value {_best_val:.0f} {currency} ({_best_updown:+.0%} vs. marked)."

    specs.append({
        "type": "D",
        "title": f"{company_name} — Følsomhed: Fair value / aktie ({currency})",
        "note": "Fair value pr. aktie ved varierende WACC og terminal vækst. Kilde: FMP.",
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
        {"indicator": "P/E",       "Seneste 12M": f"{m['peRatio']:.1f}×"    if m.get("peRatio")    else "N/A"},
        {"indicator": "EV/EBITDA", "Seneste 12M": f"{m['evToEbitda']:.1f}×" if m.get("evToEbitda") else "N/A"},
        {"indicator": "P/B",       "Seneste 12M": f"{pb_val:.1f}×"          if pb_val              else "N/A"},
        {"indicator": "P/S",       "Seneste 12M": f"{ps_val:.1f}×"          if ps_val              else "N/A"},
        {"indicator": "EV/FCF",    "Seneste 12M": f"{m['evToFCF']:.1f}×"    if m.get("evToFCF")    else "N/A"},
    ]

    # Dynamic observation: flag when actual multiples exceed reference ranges
    _above = []
    if m.get("peRatio") and m["peRatio"] > 25:
        _above.append(f"P/E {m['peRatio']:.0f}× (norm 15–25×)")
    if m.get("evToEbitda") and m["evToEbitda"] > 18:
        _above.append(f"EV/EBITDA {m['evToEbitda']:.0f}× (norm 10–18×)")
    if m.get("evToFCF") and m["evToFCF"] > 35:
        _above.append(f"EV/FCF {m['evToFCF']:.0f}× (norm 20–35×)")
    if pb_val and pb_val > 5:
        _above.append(f"P/B {pb_val:.0f}× (norm 2–5×)")
    if ps_val and ps_val > 4:
        _above.append(f"P/S {ps_val:.1f}× (norm 1–4×)")

    if _above:
        _mult_obs = " " + ", ".join(_above) + " — markedet indpriser høje vækstforventninger."
    else:
        _mult_obs = ""

    specs.append({
        "type": "D",
        "title": f"{company_name} — Markedsnøgletal",
        "note": (
            "Krydstjek af DCF med markedsbaseret prissætning. "
            "Reference: P/E 15–25×, EV/EBITDA 10–18×, EV/FCF 20–35×, P/B 2–5×, P/S 1–4×. "
            "Kapitalintensive selskaber i den lave ende, aktivlette platforme i den høje."
            + _mult_obs
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Seneste 12M"], "rows": mult_rows},
    })

    return specs, dfs


# ── Peer comparison table ──────────────────────────────────────────────────────

def build_peer_comparison_spec(peer_data: dict, company_name: str, ticker: str):
    """Build a chart spec (type D table) comparing the target company against peers.

    peer_data is the dict returned by fetch_peer_comparison().
    Returns None if peer_data is empty or unusable.
    """
    if not peer_data or not peer_data.get("companies"):
        return None

    companies = peer_data["companies"]

    def _fmt_mult(v, suffix="×", dec=1):
        if v is None:
            return "N/A"
        try:
            return f"{float(v):.{dec}f}{suffix}"
        except (TypeError, ValueError):
            return "N/A"

    def _fmt_pct(v):
        if v is None:
            return "N/A"
        try:
            val = float(v)
            # FMP sometimes returns already-multiplied percentages (e.g. 0.15 vs 15.0)
            if abs(val) < 5:
                val *= 100
            return f"{val:.1f}%"
        except (TypeError, ValueError):
            return "N/A"

    rows = []
    for c in companies:
        label = f"★ {c['ticker']}" if c.get("is_target") else c["ticker"]
        rows.append({
            "Selskab":    f"{label} — {c['name']}" if c["name"] != c["ticker"] else label,
            "P/E":        _fmt_mult(c.get("pe")),
            "EV/EBITDA":  _fmt_mult(c.get("ev_ebitda")),
            "P/B":        _fmt_mult(c.get("pb")),
            "EV/FCF":     _fmt_mult(c.get("ev_fcf")),
            "ROE":        _fmt_pct(c.get("roe")),
        })

    n_peers = sum(1 for c in companies if not c.get("is_target"))
    note = (
        f"TTM-nøgletal for {company_name} (★) sammenlignet med {n_peers} børsnoterede peers. "
        f"Kilde: FMP. Alle nøgletal er beregnet på rullende 12-månedersbasis. "
        f"N/A angiver manglende data for den pågældende peer."
    )

    return {
        "type":       "D",
        "title":      f"{company_name} — Peer-sammenligning",
        "note":       note,
        "kilde":      ["FMP"],
        "table_data": {"columns": ["P/E", "EV/EBITDA", "P/B", "EV/FCF", "ROE"], "rows": rows},
    }

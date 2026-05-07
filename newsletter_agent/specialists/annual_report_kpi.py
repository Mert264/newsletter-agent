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
        fmt = d.strftime("%b'%y")   # e.g. "Mar'26" — fits narrow columns
        return f"LTM {fmt}"
    except Exception:
        return "LTM"


def _last_updated(fmp_data: dict, ltm_date: str = "") -> str:
    # Prefer LTM date (more current than annual filing date)
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
    flags   = reformulated.get("flags", [])
    bad     = sum(1 for f in flags if "negativ" in f.lower() or "anomali" in f.lower())
    if bad > 2 or abs(upside) > 1.0:
        return "Lav — datakvalitetsproblemer påvist"
    if bad > 0 or abs(upside) > 0.5:
        return "Middel — valider balanceklassificering"
    return "Middel — standard DCF-usikkerhed"


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
    label = f"FY{yr}E" if yr else "Næste FY"
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


# ── Sector valuation benchmarks (Damodaran / market consensus ranges) ─────────

_SECTOR_BENCHMARKS: dict[str, dict] = {
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
    nc_str     = (f"+{_num(net_cash)}m (nettokasse)" if net_cash >= 0
                  else f"{_num(net_cash)}m (nettogæld)")

    rev_cagr   = reformulated["historical_avgs"]["revenue_cagr"]
    og_avg     = reformulated["historical_avgs"]["OG"]
    fy_latest  = _fy_label(years[-1])
    n_avg_yrs  = reformulated.get("n_avg_years", len(years))
    cagr_label = f"FY{years[0]}–FY{years[-1]}"
    ltm_date   = ltm_inc.get("date", "") if has_ltm else ""

    exec_rows = [
        {"indicator": "Aktuel kurs",                 "Value": f"{price:.2f} {currency}"},
        {"indicator": "Fair value-interval",         "Value": f"{bear_price:.0f} – {bull_price:.0f} {currency}"},
        {"indicator": "Basis fair value",            "Value": f"{base_price:.2f} {currency}"},
        {"indicator": "Op-/nedside",                 "Value": f"{upside:+.1%}"},
        {"indicator": "",                            "Value": ""},
        {"indicator": "WACC",                        "Value": _pct(wacc)},
        {"indicator": "Terminal vækst",              "Value": _pct(base_sc["g"])},
        {"indicator": "Netto fin. forpl. (NFO)",     "Value": nc_str},
        {"indicator": f"{fy_latest} Omsætning",      "Value": f"{_num(reformulated['revenue'][-1])}m {currency}"},
    ]

    est_str = _analyst_next_rev(fmp_data.get("estimates", []))
    if est_str:
        exec_rows.append({"indicator": "Konsensus omsætning", "Value": est_str})

    exec_rows += [
        {"indicator": "",                                          "Value": ""},
        {"indicator": f"Omsætnings-CAGR ({cagr_label})",         "Value": _pct(rev_cagr)},
        {"indicator": f"NOPAT-margin ({n_avg_yrs}år gns.)",      "Value": _pct(og_avg)},
        {"indicator": "Konfidensgrad",                            "Value": _confidence(upside, reformulated)},
        {"indicator": "Senest opdateret",                         "Value": _last_updated(fmp_data, ltm_date)},
    ]

    # DCF-implied multiples vs sector benchmarks
    _shares_m  = float(fmp_data["income"][0].get("weightedAverageShsOutDil") or 1)
    _eps       = float(fmp_data["income"][0].get("epsDiluted") or 0)
    _ebitda_m  = float(fmp_data["income"][0].get("ebitda") or 0) or float(fmp_data["income"][0].get("operatingIncome") or 0)
    _dcf_mktcp = base_price * _shares_m          # USD millions
    _dcf_ev    = _dcf_mktcp + nfo_latest          # USD millions (NFO already in millions)
    _dcf_pe    = f"{base_price / _eps:.1f}×"      if _eps > 0       else "N/A"
    _dcf_ev_eb = f"{_dcf_ev / _ebitda_m:.1f}×"   if _ebitda_m > 0  else "N/A"
    _sector    = profile.get("sector", "_default")
    _bench     = _SECTOR_BENCHMARKS.get(_sector, _SECTOR_BENCHMARKS["_default"])

    exec_rows += [
        {"indicator": "",                                  "Value": ""},
        {"indicator": "━━ DCF-Implied Multiples",         "Value": ""},
        {"indicator": "DCF Implied P/E",                  "Value": _dcf_pe},
        {"indicator": "DCF Implied EV/EBITDA",            "Value": _dcf_ev_eb},
        {"indicator": f"Sektorbenchmark P/E ({_sector})", "Value": _bench["pe"]},
        {"indicator": "Sektorbenchmark EV/EBITDA",        "Value": _bench["ev_ebitda"]},
    ]

    _exec_note = (
        f"Penman DCF: FCF = NOPAT − ΔNOA, WACC {_pct(wacc)}, terminal vækst {_pct(base_sc['g'])}. "
        f"Basis fair value inden for 0,1×–10× af markedsprisen er modelkonsistent; "
        f"en større afvigelse skyldes typisk immaterielle aktiver, der ikke er optaget på balancen. "
        f"Kilde: FMP — modeloutput, ikke et faktisk resultat."
    )
    if price > 0 and abs(upside) > 0.50:
        if upside < 0:
            _exec_note += (
                f" {upside:+.0%} implicit nedside: Penman opgør kun regnskabsmæssig kapital — "
                f"brand, platform og IP fremgår ikke af balancen. Gabet afspejler en regnskabsmæssig begrænsning, ikke nødvendigvis fejlprissætning."
            )
        else:
            _exec_note += (
                f" {upside:+.0%} implicit opside: verificer NOA-klassificering og datakomplethed, inden der handles på signalet."
            )

    specs.append({
        "type": "D",
        "title": f"{company_name} — Værdiansættelsesoversigt",
        "note": _exec_note,
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
        _snap_row(f"Omsætning ({currency}m)",        reformulated["revenue"],  _num,  ltm_rev),
        _snap_row(f"NOPAT ({currency}m)",             reformulated["OI"],       _num,  ltm_oi),
        _snap_row(f"Cash FCF ({currency}m)",          reformulated["cash_fcf"], _num,  ltm_fcf),
        _snap_row(f"NOA ({currency}m)",               reformulated["NOA"],      _num,  ltm_noa),
        _snap_row(f"NFO ({currency}m)",               reformulated["NFO"],      _num,  ltm_nfo),
        _snap_row("RNOA",                             reformulated["RNOA"],     _pct,  ltm_rnoa),
        _snap_row("NOPAT-margin",                     reformulated["OG"],       _pct,  ltm_og),
        _snap_row("Aktivomsætning (ATO)",             reformulated["ATO"],      _x,    ltm_ato),
        _snap_row("SPREAD (RNOA − NBC)",              reformulated["SPREAD"],   _pct,  ltm_spread),
    ]

    # Collect any anomaly notes
    _notes = []
    neg_noa_yrs = [y for y in show_yrs if reformulated["NOA"][years.index(y)] <= 0]
    if neg_noa_yrs:
        _notes.append(
            f"NOA ≤ 0 i {', '.join(str(y) for y in neg_noa_yrs)} — "
            f"RNOA/ATO udeladt fra gennemsnit."
        )
    if any("NOA steg" in f for f in reformulated.get("flags", [])):
        _notes.append(f"NOA-anomali i {show_yrs[-1]} — DCF anvender ATO-normaliseret start-NOA.")

    # Cash FCF vs Penman FCF divergence — explain when gap is large (>20%)
    _penman_fcf = reformulated["FCF"][-1]
    _cash_fcf   = reformulated["cash_fcf"][-1]
    if (_penman_fcf is not None and _cash_fcf is not None
            and _penman_fcf != 0 and abs((_cash_fcf - _penman_fcf) / abs(_penman_fcf)) > 0.20):
        _gap_pct    = (_cash_fcf - _penman_fcf) / abs(_penman_fcf)
        _direction  = "højere" if _gap_pct > 0 else "lavere"
        _delta_noa  = (reformulated["NOA"][-1] - reformulated["NOA"][-2]
                       if len(reformulated["NOA"]) >= 2 else 0)
        _notes.append(
            f"Cash FCF ({_num(_cash_fcf)}m) er {abs(_gap_pct):.0%} {_direction} end Penman FCF "
            f"({_num(_penman_fcf)}m). Forskellen drives af en ΔNOA på {_num(_delta_noa)}m — modellen "
            f"behandler hver krone NOA-vækst som reinvesteret kapital og fratrækker den fra NOPAT. "
            f"Når NOA stiger markant (f.eks. aktivudvidelse eller leasingomklassificering), "
            f"undervurderer Penman FCF den faktisk genererede likviditet. "
            f"Cash FCF er det mest direkte mål for reelt genereret likviditet."
        )

    snap_note = (
        f"NOPAT = EBIT × (1−t = {_pct(t)} lovpligtig) — driftsoverskud efter skat, uafhængig af kapitalstruktur. "
        f"NOA = Driftsaktiver − Driftsforpligtelser. Benchmarks: NOPAT-margin >10%, ATO (Omsætning/NOA) >1×. "
        f"Penman FCF = NOPAT − ΔNOA; Cash FCF = DFC − Investeringer. NFO negativ = nettokasse. "
        + (" ".join(_notes) if _notes else "")
    )

    specs.append({
        "type": "D",
        "title": f"{company_name} — Regnskabsoversigt",
        "note": snap_note,
        "kilde": kilde,
        "table_data": {"columns": yr_cols, "rows": snap_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 3 — Revenue & Operating Income Trend (line chart)
    # ══════════════════════════════════════════════════════════════════════════
    lbl_rev = f"{ticker} — Omsætning ({currency}m)"
    lbl_oi  = f"{ticker} — NOPAT ({currency}m)"
    dfs[lbl_rev] = _ts(years, reformulated["revenue"], lbl_rev)
    dfs[lbl_oi]  = _ts(years, reformulated["OI"],      lbl_oi)

    df_trend = dfs[lbl_rev].join(dfs[lbl_oi])
    dfs["trend_rev_oi"] = df_trend

    specs.append({
        "type": "A", "freq": "A",
        "title": f"{company_name} — Omsætning & NOPAT ({currency}m)",
        "x_label": "Regnskabsår",
        "y_label": f"{currency}m",
        "series_labels": ["trend_rev_oi"],
        "note": (
            f"Viser omsætningsudvikling (toplinje) over for driftsoverskud efter skat (NOPAT = EBIT×(1−{_pct(t)})). "
            f"Omsætnings-CAGR: {_pct(rev_cagr)} ({cagr_label}). "
            f"Når NOPAT vokser hurtigere end omsætningen, udvides marginerne — det mest værdiskabende signal. "
            f"Et voksende gab afslører operationel løftestang; et aftagende gab signalerer omkostningspres."
        ),
        "kilde": kilde,
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 4 — WACC Calculation
    # ══════════════════════════════════════════════════════════════════════════
    MRP = wacc_data["MRP"]

    wacc_rows = [
        {"indicator": "Risikofri rente",              "Parameter": "rf",     "Value": _pct(wacc_data["rf"]),
         "Kilde": f"{rf_entry['bond_name']} (spot)"},
        {"indicator": "Beta (rå)",                    "Parameter": "β",      "Value": f"{wacc_data['beta_raw']:.4f}",
         "Kilde": "FMP /profile"},
        {"indicator": "Beta (Blume-just.)",           "Parameter": "β_adj",  "Value": f"{wacc_data['beta_adj']:.4f}",
         "Kilde": "2/3 × β + 1/3"},
        {"indicator": "Aktierisikopræmie",            "Parameter": "MRP",    "Value": _pct(MRP),
         "Kilde": "Damodaran US mature-market ERP"},
        {"indicator": "Landerisikopræmie",            "Parameter": "CRP",    "Value": _pct(wacc_data["CRP"]),
         "Kilde": f"Damodaran {iso3}"},
        {"indicator": "Egenkapitalomkostning",        "Parameter": "rE",     "Value": _pct(wacc_data["rE"]),
         "Kilde": "rf + β_adj × (MRP + CRP)"},
        {"indicator": "Kreditspænd",                  "Parameter": "rs",     "Value": _pct(wacc_data["rs"]),
         "Kilde": wacc_data["rating"] or "ICR fallback"},
        {"indicator": "Skattesats",                   "Parameter": "t",      "Value": _pct(wacc_data["t"]),
         "Kilde": f"Lovpligtig/normaliseret ({iso3}) — ikke effektiv sats"},
        {"indicator": "Låneomkostning (efter skat)",  "Parameter": "rD",     "Value": _pct(wacc_data["rD"]),
         "Kilde": "(rf + rs) × (1 − t)"},
        {"indicator": "Egenkapitalvægt",              "Parameter": "E/V",    "Value": _pct(wacc_data["E"] / wacc_data["V"]),
         "Kilde": "Market cap / (E + D)"},
        {"indicator": "Gældsvægt",                    "Parameter": "D/V",    "Value": _pct(wacc_data["D"] / wacc_data["V"]),
         "Kilde": "NFO / (E + D)" if wacc_data["D"] > 0 else "Nettokasse → D=0 (Penman nettogæld)"},
        {"indicator": "━━ WACC",                     "Parameter": "WACC",   "Value": _pct(wacc),
         "Kilde": "E/V × rE + D/V × rD"},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — WACC",
        "note": (
            f"WACC = {_pct(wacc)} — diskonteringsrenten anvendt på alle fremtidige pengestrømme. "
            f"rf = {rf_entry['bond_name']} spotrente (fremadskuende). Beta Blume-justeret (2/3 β + 1/3). "
            f"MRP = Damodaran US-markedspræmie {_pct(MRP)} + CRP. "
            f"Et WACC-skift på 1 ppt flytter fair value ~15–25%. Typisk: 7–10% investment-grade large caps, 10–14% ved højere risiko."
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Parameter", "Value", "Kilde"], "rows": wacc_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 5 — DCF Scenarios: Bear / Base / Bull
    # ══════════════════════════════════════════════════════════════════════════
    def _sc_price_str(sc_name):
        sc = dcf_scenarios[sc_name]
        vs = (sc["price"] - price) / price if price > 0 else 0
        return f"{sc['price']:.0f} {currency}  ({vs:+.0%})"

    sc_rows = [
        {"indicator": "Omsætningsvækst (CAGR)",
         "Bear": _pct(bear_sc["cagr"]), "Base": _pct(base_sc["cagr"]), "Bull": _pct(bull_sc["cagr"])},
        {"indicator": "NOPAT-margin",
         "Bear": _pct(bear_sc["og"]), "Base": _pct(base_sc["og"]), "Bull": _pct(bull_sc["og"])},
        {"indicator": "WACC",
         "Bear": _pct(bear_sc["wacc"]), "Base": _pct(base_sc["wacc"]), "Bull": _pct(bull_sc["wacc"])},
        {"indicator": "Terminal vækst",
         "Bear": _pct(bear_sc["g"]), "Base": _pct(base_sc["g"]), "Bull": _pct(bull_sc["g"])},
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

    _dcf_note = (
        f"5-årig Penman FCF (NOPAT − ΔNOA) + Gordon Growth terminalværdi. "
        f"Bear = lav vækst, pressede marginer, højere WACC. Bull = stærkere vækst, ekspanderende marginer, lavere WACC. "
        f"Bredt bear-til-bull spænd = høj følsomhed; smalt spænd = stabil, forudsigelig forretning. "
        f"Aktuel kurs = {price:.2f} {currency}."
    )
    if price > 0 and abs(upside) > 0.50:
        if upside < 0:
            _dcf_note += (
                f" Alle scenarier under marked ({upside:+.0%} basis): gabet afspejler sandsynligvis immateriel franchise-værdi, der ikke fremgår af balancen."
            )
        else:
            _dcf_note += (
                f" Alle scenarier over marked ({upside:+.0%} basis): verificer NOA og datakomplethed, inden der handles."
            )

    specs.append({
        "type": "D",
        "title": f"{company_name} — DCF-scenarier",
        "note": _dcf_note,
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
        "title": f"{company_name} — Følsomhed: Fair value / aktie ({currency})",
        "note": (
            f"Hver celle viser fair value per aktie ved et givet (WACC, g)-par. "
            f"Kolonner = WACC, rækker = terminal vækst g. ★ = basisscenarie (WACC {_pct(wacc_base)}, g {_pct(g_base)}). "
            f"WACC-akse: ±1 ppt i 0,25 ppt-trin. g-akse: 1–3%."
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
        {"indicator": "P/E",       "Trailing 12M": f"{m['peRatio']:.1f}x"    if m.get("peRatio")    else "N/A"},
        {"indicator": "EV/EBITDA", "Trailing 12M": f"{m['evToEbitda']:.1f}x" if m.get("evToEbitda") else "N/A"},
        {"indicator": "P/B",       "Trailing 12M": f"{pb_val:.1f}x"          if pb_val              else "N/A"},
        {"indicator": "P/S",       "Trailing 12M": f"{ps_val:.1f}x"          if ps_val              else "N/A"},
        {"indicator": "EV/FCF",    "Trailing 12M": f"{m['evToFCF']:.1f}x"    if m.get("evToFCF")    else "N/A"},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — Markedsnøgletal",
        "note": (
            "Krydstjek af DCF med markedsbaseret prissætning. "
            "Reference: P/E 15–25×, EV/EBITDA 10–18×, EV/FCF 20–35×, P/B 2–5×, P/S 1–4×. "
            "Kapitalintensive selskaber i den lave ende, asset-light platforme i den høje. Trailing 12 måneder. Kilde: FMP."
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Trailing 12M"], "rows": mult_rows},
    })

    return specs, dfs

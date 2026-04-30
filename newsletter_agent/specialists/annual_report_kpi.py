# newsletter_agent/specialists/annual_report_kpi.py
#
# Produces 7 clean, investor-focused charts following the Penman/WACC/DCF paper structure.
# Flow: Financial Snapshot → Trend Chart → WACC → DCF → Valuation Bridge → Sensitivity → Multiples
import pandas as pd
from newsletter_agent.specialists.annual_report_constants import MSCI_WORLD_35YR_RETURN


def _ts(years: list, values: list, label: str) -> pd.DataFrame:
    """Build a DatetimeIndex DataFrame (Dec-31 per year) from year list and values."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"{y}-12-31") for y in years])
    return pd.DataFrame({label: values}, index=idx)


def _pct(v: float) -> str:
    return f"{v:.2%}"

def _num(v: float) -> str:
    """Format as integer thousands if whole, else 1 decimal place."""
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.1f}"

def _x(v: float, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}x"


def build_chart_specs(
    ticker: str, company_name: str, hq_country: str,
    reformulated: dict, wacc_data: dict, dcf_results: dict,
    sensitivity: dict, fmp_data: dict,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:

    years    = reformulated["years"]
    profile  = fmp_data.get("profile", {})
    currency = profile.get("currency", "USD")
    price    = float(profile.get("price") or 0)
    kilde    = "FMP, Damodaran"
    rf_entry = wacc_data["rf_entry"]
    wacc     = wacc_data["wacc"]
    dcf_price = dcf_results["price_per_share"]

    # ── Shared DataFrames ─────────────────────────────────────────────────────
    dfs: dict[str, pd.DataFrame] = {}

    lbl_rev = f"{ticker} — Omsætning ({currency}m)"
    lbl_oi  = f"{ticker} — OI/NOPAT ({currency}m)"
    dfs[lbl_rev] = _ts(years, reformulated["revenue"], lbl_rev)
    dfs[lbl_oi]  = _ts(years, reformulated["OI"],      lbl_oi)

    # Fundamental vs market (Type B)
    lbl_fund   = "Fundamental pris"
    lbl_market = "Markedspris"
    dfs[lbl_fund]   = _ts([years[-1]], [dcf_price], lbl_fund)
    dfs[lbl_market] = _ts([years[-1]], [price],     lbl_market)

    specs = []

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 1 — Penman Regnskabsanalyse (Financial snapshot, last 3–5 years)
    # Shows what an investor wants to see first: business quality over time
    # ══════════════════════════════════════════════════════════════════════════
    n_show    = min(5, len(years))
    show_yrs  = years[-n_show:]
    show_idx  = [years.index(y) for y in show_yrs]
    yr_cols   = [str(y) for y in show_yrs]

    def _snap_row(label, vals, fmt_fn):
        row = {"indicator": label}
        for y, i in zip(show_yrs, show_idx):
            v = vals[i]
            row[str(y)] = fmt_fn(v) if v is not None else "—"
        return row

    fcf_vals = reformulated["FCF"]
    snap_rows = [
        _snap_row(f"Nettoomsætning ({currency}m)", reformulated["revenue"], _num),
        _snap_row(f"OI/NOPAT ({currency}m)",       reformulated["OI"],      _num),
        _snap_row(f"FCF ({currency}m)",             fcf_vals,                _num),
        _snap_row(f"NOA ({currency}m)",             reformulated["NOA"],     _num),
        _snap_row(f"NFO ({currency}m)",             reformulated["NFO"],     _num),
        _snap_row("RNOA",                           reformulated["RNOA"],    _pct),
        _snap_row("OG (overskudsgrad)",             reformulated["OG"],      _pct),
        _snap_row("ATO",                            reformulated["ATO"],     lambda v: _x(v)),
        _snap_row("SPREAD (RNOA − NBC)",            reformulated["SPREAD"],  _pct),
    ]

    _rnoa_latest = reformulated["RNOA"][-1]
    _noa_note    = (
        f" RNOA > 100%: ekstremt lav NOA (negativt driftskapital) — "
        f"karakteristisk for kapitallettte teknologiselskaber [CALC]."
        if _rnoa_latest > 1.0 else ""
    )
    _noa_flag_note = ""
    for flag in reformulated.get("flags", []):
        if "NOA steg" in flag:
            _noa_flag_note = (
                f" ⚠ NOA-anomali detekteret i {show_yrs[-1]}: DCF anvender ATO-normaliseret startpunkt [ASSUMED]."
            )
            break

    specs.append({
        "type": "D",
        "title": f"{company_name} — Penman Regnskabsanalyse [CALC]",
        "note": (
            f"OI = EBIT × (1−t), t = {_pct(wacc_data['t'])} [ASSUMED]. "
            f"FCF = OI − ΔNOA (første år mangler ΔNOA) [CALC]. "
            f"NOA = Driftsaktiver − Driftsforpligtelser. NFO = Finansiel gæld − Finansielle aktiver [CALC]."
            f"{_noa_note}{_noa_flag_note}"
        ),
        "kilde": kilde,
        "table_data": {"columns": yr_cols, "rows": snap_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 2 — Omsætning & OI Trend (Type A — historical line chart)
    # ══════════════════════════════════════════════════════════════════════════
    df_trend = dfs[lbl_rev].join(dfs[lbl_oi])
    dfs["trend_rev_oi"] = df_trend

    rev_cagr = reformulated["historical_avgs"]["revenue_cagr"]
    specs.append({
        "type": "A", "freq": "A",
        "title": f"{company_name} — Omsætning & OI/NOPAT ({currency}m)",
        "y_label": f"{currency}m",
        "series_labels": ["trend_rev_oi"],
        "note": (
            f"Historisk omsætning og driftsoverskud efter skat [CALC]. "
            f"Revenue CAGR = {_pct(rev_cagr)} (organisk, M&A-justeret) [ASSUMED]."
        ),
        "kilde": kilde,
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 3 — WACC Beregning (step-by-step, one comprehensive table)
    # Follows paper methodology exactly: rf → β → MRP → CRP → rE → rs → rD → WACC
    # ══════════════════════════════════════════════════════════════════════════
    MRP = MSCI_WORLD_35YR_RETURN - wacc_data["rf"]   # country-specific MRP
    iso3 = wacc_data["iso3"]

    wacc_rows = [
        {"indicator": "1. Risikofri rente",
         "Parameter": "rf", "Værdi": _pct(wacc_data["rf"]), "Label": "ASSUMED",
         "Kilde": f"{rf_entry['bond_name']} ({rf_entry['maturity_yr']}yr hist. avg)"},
        {"indicator": "2. Beta (ukorrigeret)",
         "Parameter": "β_raw", "Værdi": f"{wacc_data['beta_raw']:.4f}", "Label": "SOURCED",
         "Kilde": "FMP /profile"},
        {"indicator": "3. Beta (Blume 1975)",
         "Parameter": "β_adj", "Værdi": f"{wacc_data['beta_adj']:.4f}", "Label": "CALC",
         "Kilde": "2/3×β_raw + 1/3"},
        {"indicator": "4. Markedsrisikopræmie",
         "Parameter": "MRP", "Værdi": _pct(MRP), "Label": "SOURCED",
         "Kilde": f"MSCI World 35yr aritm. − rf_{iso3}"},
        {"indicator": "5. Landerisikopræmie",
         "Parameter": "CRP", "Værdi": _pct(wacc_data["CRP"]), "Label": "SOURCED",
         "Kilde": f"Damodaran {iso3}"},
        {"indicator": "6. Egenkapitalomkostning",
         "Parameter": "rE", "Værdi": _pct(wacc_data["rE"]), "Label": "CALC",
         "Kilde": "rf + β × (MRP + CRP)"},
        {"indicator": "7. Kreditvurdering / rs",
         "Parameter": "rs", "Værdi": _pct(wacc_data["rs"]), "Label": "SOURCED",
         "Kilde": wacc_data["rating"] if wacc_data["rating"] else "ICR fallback"},
        {"indicator": "8. Skattesats",
         "Parameter": "t", "Værdi": _pct(wacc_data["t"]), "Label": "ASSUMED",
         "Kilde": f"Statutory {iso3}"},
        {"indicator": "9. Gældsomkostning (efter skat)",
         "Parameter": "rD", "Værdi": _pct(wacc_data["rD"]), "Label": "CALC",
         "Kilde": "(rf + rs) × (1 − t)"},
        {"indicator": "10. Egenkapitalvægt",
         "Parameter": "E/V", "Værdi": _pct(wacc_data["E"] / wacc_data["V"]), "Label": "CALC",
         "Kilde": "Markedsværdi / (E + D)"},
        {"indicator": "11. Gældsvægt",
         "Parameter": "D/V", "Værdi": _pct(wacc_data["D"] / wacc_data["V"]), "Label": "CALC",
         "Kilde": "NFO / (E + D)"},
        {"indicator": "═══ WACC",
         "Parameter": "WACC", "Værdi": _pct(wacc), "Label": "CALC",
         "Kilde": "E/V×rE + D/V×rD"},
    ]

    specs.append({
        "type": "D",
        "title": f"{company_name} — WACC Beregning [CALC]",
        "note": (
            f"WACC = E/V × rE + D/V × rD = {_pct(wacc)} [CALC]. "
            f"rf = {rf_entry['maturity_yr']}år historisk gns. for {iso3} [ASSUMED]. "
            f"MRP = MSCI World 35år aritmetisk gns. − rf = {_pct(MRP)} [SOURCED]. "
            f"β justeret med Blume (1975): β_adj = 2/3×β_raw + 1/3 [CALC]."
        ),
        "kilde": kilde,
        "table_data": {"columns": ["Parameter", "Værdi", "Label", "Kilde"], "rows": wacc_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 4 — DCF Prognosemodel (5yr forecast + terminal, paper's Table 7 format)
    # ══════════════════════════════════════════════════════════════════════════
    fy   = dcf_results["forecast_years"]
    cols = fy + ["Terminalår"]

    def _frow(label, vals, terminal_val=None):
        row = {"indicator": label}
        for i, yr in enumerate(fy):
            row[yr] = _num(vals[i]) if vals[i] is not None else "—"
        row["Terminalår"] = _num(terminal_val) if terminal_val is not None else ""
        return row

    dcf_rows = [
        _frow(f"Nettoomsætning [EST]",         dcf_results["revenue_forecast"]),
        _frow(f"Driftsoverskud OI [EST]",       dcf_results["OI_forecast"]),
        _frow(f"NOA [EST]",                     dcf_results["NOA_forecast"]),
        _frow(f"ΔNOA [EST]",                    dcf_results["dNOA_forecast"]),
        {**{"indicator": "Discount faktor [CALC]"},
         **{yr: f"{d:.4f}" for yr, d in zip(fy, dcf_results["discount_factors"])},
         "Terminalår": ""},
        _frow(f"FCF (OI − ΔNOA) [EST]",         dcf_results["FCF_forecast"]),
        _frow(f"Nutidsværdi af FCF [CALC]",      dcf_results["PV_FCF"]),
        {"indicator": ""},
        {"indicator": "Total nutidsværdi [CALC]",          "Terminalår": _num(dcf_results["total_PV"])},
        {"indicator": "Terminalværdi [CALC]",              "Terminalår": _num(dcf_results["TV"])},
        {"indicator": "Nutidsværdi af terminalværdi [CALC]","Terminalår": _num(dcf_results["PV_TV"])},
        {"indicator": ""},
        {"indicator": "Virksomhedsværdi EV [CALC]",        "Terminalår": _num(dcf_results["EV"])},
        {"indicator": "− NFO [CALC]",                      "Terminalår": _num(dcf_results["NFO"])},
        {"indicator": "Egenkapitalværdi [CALC]",           "Terminalår": _num(dcf_results["equity_value"])},
        {"indicator": "Antal aktier (fortyndet) [SOURCED]","Terminalår": f"{dcf_results['diluted_shares']:.0f}m"},
        {"indicator": "Pris per aktie [CALC]",             "Terminalår": f"{dcf_price:.2f} {currency}"},
    ]

    og_avg  = reformulated["historical_avgs"]["OG"]
    ato_avg = reformulated["historical_avgs"]["ATO"]
    specs.append({
        "type": "D",
        "title": f"{company_name} — DCF Prognosemodel [EST/CALC]",
        "note": (
            f"5-årig prognose (Penman FCF = OI − ΔNOA) [CALC]. "
            f"Salgsvækst = {_pct(rev_cagr)} [ASSUMED]. "
            f"OG = {_pct(og_avg)} (hist. gns.) [CALC]. "
            f"ATO = {ato_avg:.2f}x (hist. gns.) [CALC]. "
            f"WACC = {_pct(wacc)}, g = {_pct(dcf_results['g'])} [ASSUMED]. "
            f"TV = FCF_T+1 / (WACC − g) [CALC]."
        ),
        "kilde": kilde,
        "table_data": {"columns": cols, "rows": dcf_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 5 — Fundamental vs. Markedspris (Type B bar chart)
    # ══════════════════════════════════════════════════════════════════════════
    pct_diff  = (dcf_price - price) / price if price > 0 else 0
    direction = "undervurderet" if dcf_price > price else "overvurderet"
    specs.append({
        "type": "B",
        "title": f"{company_name} — Fundamental vs. Markedspris ({currency})",
        "y_label": f"{currency} pr. aktie",
        "series_labels": [lbl_fund, lbl_market],
        "note": (
            f"Fundamental pris = {dcf_price:.2f} {currency} [CALC]. "
            f"Markedspris = {price:.2f} {currency} [SOURCED]. "
            f"Afvigelse: {_pct(abs(pct_diff))} ({direction}). "
            f"WACC = {_pct(wacc)}, g = {_pct(dcf_results['g'])} [ASSUMED]."
        ),
        "kilde": kilde,
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 6 — Følsomhedsanalyse: Pris/aktie over WACC × g
    # ══════════════════════════════════════════════════════════════════════════
    wacc_axis  = sensitivity["wacc_axis"]
    g_axis     = sensitivity["g_axis"]
    wacc_base  = sensitivity["wacc_base"]
    g_base     = sensitivity["g_base"]
    sens_cols  = [_pct(w) for w in wacc_axis]
    sens_rows  = []
    for row_idx, g in enumerate(g_axis):
        row = {"indicator": f"g={_pct(g)}"}
        for col_idx, w in enumerate(wacc_axis):
            cell_val = sensitivity["grid"][row_idx][col_idx]
            cell_str = f"{cell_val:.1f}" if cell_val is not None else "—"
            if abs(w - wacc_base) < 1e-6 and abs(g - g_base) < 1e-6:
                cell_str = f"★{cell_str}"
            row[_pct(w)] = cell_str
        sens_rows.append(row)

    specs.append({
        "type": "D",
        "title": f"{company_name} — Følsomhedsanalyse: Pris/aktie ({currency}) [CALC]",
        "note": (
            f"Kolonner = WACC (%). Rækker = terminalvækst g. "
            f"★ = base case (WACC={_pct(wacc_base)}, g={_pct(g_base)}) [ASSUMED]. "
            f"Interval: WACC ± 1 pct.point (0,25% trin), g 1–3% [CALC]."
        ),
        "kilde": kilde,
        "table_data": {"columns": sens_cols, "rows": sens_rows},
    })

    # ══════════════════════════════════════════════════════════════════════════
    # Chart 7 — Markedsmultipler (quick investor reference)
    # ══════════════════════════════════════════════════════════════════════════
    metrics = fmp_data.get("metrics", [{}])
    m       = metrics[0] if metrics else {}
    mkt_cap = fmp_data["profile"].get("marketCap", 0) or 0
    _inc0   = fmp_data["income"][0] if fmp_data.get("income") else {}
    _bal0   = fmp_data["balance"][0] if fmp_data.get("balance") else {}
    _rev    = _inc0.get("revenue") or _inc0.get("totalRevenue") or 0
    _equity = _bal0.get("totalStockholdersEquity") or 0
    pb_val  = m.get("pbRatio") or (mkt_cap / _equity if _equity else None)
    ps_val  = m.get("priceToSalesRatio") or (mkt_cap / _rev if _rev else None)

    specs.append({
        "type": "D",
        "title": f"{company_name} — Markedsmultipler [SOURCED/CALC]",
        "note": (
            "Trailing multiples fra FMP [SOURCED]. "
            "P/B og P/S beregnet fra markedsværdi / bogført egenkapital/omsætning hvis ikke direkte tilgængeligt [CALC]."
        ),
        "kilde": kilde,
        "table_data": {
            "columns": ["Multipel", "Trailing [SOURCED]"],
            "rows": [
                {"indicator": "P/E",       "Multipel": "P/E",       "Trailing [SOURCED]": f"{m['peRatio']:.1f}x"   if m.get("peRatio")    else "N/A"},
                {"indicator": "EV/EBITDA", "Multipel": "EV/EBITDA", "Trailing [SOURCED]": f"{m['evToEbitda']:.1f}x" if m.get("evToEbitda") else "N/A"},
                {"indicator": "P/B",       "Multipel": "P/B",       "Trailing [SOURCED]": f"{pb_val:.1f}x"         if pb_val              else "N/A"},
                {"indicator": "P/S",       "Multipel": "P/S",       "Trailing [SOURCED]": f"{ps_val:.1f}x"         if ps_val              else "N/A"},
                {"indicator": "P/FCF",     "Multipel": "P/FCF",     "Trailing [SOURCED]": f"{m['pfcfRatio']:.1f}x" if m.get("pfcfRatio")  else "N/A"},
            ],
        },
    })

    return specs, dfs

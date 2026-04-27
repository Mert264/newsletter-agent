# newsletter_agent/specialists/annual_report_kpi.py
import pandas as pd


def _ts(years: list, values: list, label: str) -> pd.DataFrame:
    """Build a DatetimeIndex DataFrame from year list and values."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"{y}-12-31") for y in years])
    return pd.DataFrame({label: values}, index=idx)


def _pct(v: float) -> str:
    return f"{v:.2%}"

def _num(v: float, scale: float = 1) -> str:
    return f"{v / scale:,.1f}"


def build_chart_specs(
    ticker: str, company_name: str, hq_country: str,
    reformulated: dict, wacc_data: dict, dcf_results: dict,
    sensitivity: dict, fmp_data: dict,
) -> tuple[list[dict], dict[str, pd.DataFrame]]:

    years   = reformulated["years"]
    profile = fmp_data.get("profile", {})
    currency= profile.get("currency", "")
    price   = float(profile.get("price") or 0)
    kilde   = f"FMP, Damodaran ({ticker})"
    rf_entry= wacc_data["rf_entry"]
    wacc    = wacc_data["wacc"]
    iso3    = wacc_data["iso3"]
    dcf_price = dcf_results["price_per_share"]

    # ── Shared DataFrames for type A charts ──────────────────────────────────
    dfs: dict[str, pd.DataFrame] = {}

    lbl_rev    = f"{ticker} — Omsætning ({currency}m)"
    lbl_oi     = f"{ticker} — OI/NOPAT ({currency}m)"
    lbl_fcf    = f"{ticker} — FCF ({currency}m)"
    lbl_rnoa   = f"{ticker} — RNOA (%)"
    lbl_roce   = f"{ticker} — ROCE (%)"
    lbl_spread = f"{ticker} — SPREAD (%)"
    lbl_wacc_line = f"{ticker} — WACC (%)"
    lbl_rnoa_vs   = f"{ticker} — RNOA vs WACC (%)"
    lbl_flev   = f"{ticker} — FLEV"
    lbl_nfo    = f"{ticker} — NFO ({currency}m)"

    scale = 1  # values already in native currency units

    dfs[lbl_rev]    = _ts(years, reformulated["revenue"],    lbl_rev)
    dfs[lbl_oi]     = _ts(years, reformulated["OI"],         lbl_oi)
    fcf_vals        = [v if v is not None else float("nan") for v in reformulated["FCF"]]
    dfs[lbl_fcf]    = _ts(years, fcf_vals, lbl_fcf)
    dfs[lbl_rnoa]   = _ts(years, [v * 100 for v in reformulated["RNOA"]], lbl_rnoa)
    dfs[lbl_roce]   = _ts(years, [v * 100 for v in reformulated["ROCE"]], lbl_roce)
    dfs[lbl_spread] = _ts(years, [v * 100 for v in reformulated["SPREAD"]], lbl_spread)
    dfs[lbl_wacc_line] = _ts(years, [wacc * 100] * len(years), lbl_wacc_line)
    spread_rnoa_wacc = [r * 100 - wacc * 100 for r in reformulated["RNOA"]]
    dfs[lbl_rnoa_vs] = _ts(years, spread_rnoa_wacc, lbl_rnoa_vs)
    dfs[lbl_flev]   = _ts(years, reformulated["FLEV"], lbl_flev)
    dfs[lbl_nfo]    = _ts(years, reformulated["NFO"],  lbl_nfo)

    # Fundamental vs market price (type B)
    lbl_fund   = f"{ticker} — Fundamental pris"
    lbl_market = f"{ticker} — Markedspris"
    dfs[lbl_fund]   = _ts([years[-1]], [dcf_price],  lbl_fund)
    dfs[lbl_market] = _ts([years[-1]], [price],       lbl_market)

    # ── Chart specs (18 total) ───────────────────────────────────────────────
    specs = []

    # Chart 1: Forecast assumptions table
    specs.append({
        "type": "D", "title": f"{company_name} — Forecast Assumptions [ASSUMED/SOURCED]",
        "note": (f"rf={_pct(wacc_data['rf'])} ({rf_entry['bond_name']}, "
                 f"{rf_entry['maturity_yr']}yr historical avg [ASSUMED]). "
                 f"β_raw={wacc_data['beta_raw']:.2f} [SOURCED], "
                 f"β_adj={wacc_data['beta_adj']:.4f} (Blume 1975 [CALC]). "
                 f"MRP={_pct(wacc_data['MRP'])} [SOURCED], CRP={_pct(wacc_data['CRP'])} [SOURCED]. "
                 f"t={_pct(wacc_data['t'])} statutory [ASSUMED]."),
        "kilde": kilde,
        "table_data": {
            "columns": ["Parameter", "Værdi", "Label", "Kilde"],
            "rows": [
                {"indicator": "rf (risikofri rente)",    "Parameter": "rf",    "Værdi": _pct(wacc_data["rf"]),    "Label": "ASSUMED",  "Kilde": rf_entry["bond_name"]},
                {"indicator": "β_raw",                   "Parameter": "β_raw", "Værdi": f"{wacc_data['beta_raw']:.4f}", "Label": "SOURCED", "Kilde": "FMP /profile"},
                {"indicator": "β_adj (Blume 1975)",      "Parameter": "β_adj", "Værdi": f"{wacc_data['beta_adj']:.4f}", "Label": "CALC",    "Kilde": "2/3×β_raw+1/3"},
                {"indicator": "MRP (markedsrisikopræmie)","Parameter": "MRP",  "Værdi": _pct(wacc_data["MRP"]),   "Label": "SOURCED",  "Kilde": "Damodaran MSCI World 35yr"},
                {"indicator": "CRP (landrisikopræmie)",  "Parameter": "CRP",   "Værdi": _pct(wacc_data["CRP"]),   "Label": "SOURCED",  "Kilde": f"Damodaran {iso3}"},
                {"indicator": "rE (egenkapitalomkostning)","Parameter": "rE",  "Værdi": _pct(wacc_data["rE"]),   "Label": "CALC",     "Kilde": "CAPM"},
                {"indicator": "Moody's rating",          "Parameter": "rating","Værdi": wacc_data["rating"],       "Label": "SOURCED",  "Kilde": "FMP /rating"},
                {"indicator": "rs (kreditspænd)",        "Parameter": "rs",    "Værdi": _pct(wacc_data["rs"]),    "Label": "SOURCED",  "Kilde": "Damodaran spread tabel"},
                {"indicator": "rD (gældsomkostning, after-tax)","Parameter": "rD","Værdi": _pct(wacc_data["rD"]),"Label": "CALC",   "Kilde": "(rf+rs)×(1−t)"},
                {"indicator": "WACC",                    "Parameter": "WACC",  "Værdi": _pct(wacc_data["wacc"]), "Label": "CALC",     "Kilde": "D/V×rD + E/V×rE"},
                {"indicator": "OG (driftsmargin, avg)",  "Parameter": "OG",    "Værdi": _pct(reformulated["historical_avgs"]["OG"]), "Label": "CALC", "Kilde": "FMP 10yr avg"},
                {"indicator": "ATO (aktivomsætning, avg)","Parameter": "ATO",  "Værdi": f"{reformulated['historical_avgs']['ATO']:.2f}x", "Label": "CALC", "Kilde": "FMP 10yr avg"},
                {"indicator": "g (terminalvækst)",       "Parameter": "g",     "Værdi": _pct(dcf_results["g"]),  "Label": "ASSUMED",  "Kilde": "Gordons vækstmodel"},
                {"indicator": "t (skattesats, statutær)","Parameter": "t",     "Værdi": _pct(wacc_data["t"]),    "Label": "ASSUMED",  "Kilde": f"Statutory {iso3}"},
            ],
        },
    })

    # Chart 2: Bond yield table
    specs.append({
        "type": "D", "title": f"{company_name} — Risikofri Rente [ASSUMED]",
        "note": (f"rf = {_pct(rf_entry['rate'])} er det {rf_entry['maturity_yr']}-årige historiske gennemsnit "
                 f"af {rf_entry['bond_name']}. Aktuel spotrente = {_pct(rf_entry['spot'])} — vises kun til reference, "
                 f"ikke anvendt i beregninger. Historisk gennemsnit afspejler den langsigtede ligevægt "
                 f"og matcher terminalperiodens løbetid [ASSUMED]."),
        "kilde": kilde,
        "table_data": {
            "columns": ["Land", "Obligation", "Løbetid", "Hist. avg. [ASSUMED]", "Spot (ref.)"],
            "rows": [
                {"indicator": iso3,
                 "Land": iso3, "Obligation": rf_entry["bond_name"],
                 "Løbetid": f"{rf_entry['maturity_yr']}yr",
                 "Hist. avg. [ASSUMED]": _pct(rf_entry["rate"]),
                 "Spot (ref.)": _pct(rf_entry["spot"])},
            ],
        },
    })

    # Chart 3: Moody's rating + spread table
    specs.append({
        "type": "D", "title": f"{company_name} — Kreditvurdering og Kreditspænd [SOURCED]",
        "note": (f"Moody's kreditvurdering: {wacc_data['rating']}. "
                 f"Kreditspænd (rs) = {_pct(wacc_data['rs'])} [SOURCED]. "
                 f"ICR-baseret krydscheck: {_pct(wacc_data['rs_icr'])} [CALC]."),
        "kilde": kilde,
        "table_data": {
            "columns": ["Kreditvurdering", "Kreditspænd [SOURCED]", "ICR krydscheck [CALC]", "Anvendt"],
            "rows": [
                {"indicator": company_name,
                 "Kreditvurdering": wacc_data["rating"],
                 "Kreditspænd [SOURCED]": _pct(wacc_data["rs"]),
                 "ICR krydscheck [CALC]": _pct(wacc_data["rs_icr"]),
                 "Anvendt": "Moody's (primær)" if wacc_data["rs_moody"] else "ICR (fallback)"},
            ],
        },
    })

    # Chart 4: WACC breakdown
    specs.append({
        "type": "D", "title": f"{company_name} — WACC Komponentopdeling [CALC]",
        "note": f"WACC = D/V × rD + E/V × rE = {_pct(wacc_data['wacc'])} [CALC].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Komponent", "Værdi [CALC]"],
            "rows": [
                {"indicator": "rE (egenkapitalomkostning)", "Komponent": "rE", "Værdi [CALC]": _pct(wacc_data["rE"])},
                {"indicator": "rD (after-tax gældsomkostning)", "Komponent": "rD", "Værdi [CALC]": _pct(wacc_data["rD"])},
                {"indicator": "E/V (egenkapitalvægt)", "Komponent": "E/V", "Værdi [CALC]": _pct(wacc_data["E"] / wacc_data["V"])},
                {"indicator": "D/V (gældsvægt)",       "Komponent": "D/V", "Værdi [CALC]": _pct(wacc_data["D"] / wacc_data["V"])},
                {"indicator": "WACC",                   "Komponent": "WACC","Værdi [CALC]": _pct(wacc_data["wacc"])},
            ],
        },
    })

    # Chart 5: Penman reformulated BS (recent 5 years)
    display_years = years[-5:]
    specs.append({
        "type": "D", "title": f"{company_name} — Penman Reformuleret Balance [CALC]",
        "note": "NOA = Driftsaktiver − Driftsforpligtelser. NFO = Finansielle forpligtelser − Finansielle aktiver [CALC].",
        "kilde": kilde,
        "table_data": {
            "columns": [str(y) for y in display_years],
            "rows": [
                {"indicator": f"NOA [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["NOA"][years.index(y)]) for y in display_years}},
                {"indicator": f"NFO [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["NFO"][years.index(y)]) for y in display_years}},
                {"indicator": f"Egenkapital [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["common_equity"][years.index(y)]) for y in display_years}},
                {"indicator": f"NCI [{currency}m] [CALC]",
                 **{str(y): _num(reformulated["NCI"][years.index(y)]) for y in display_years}},
            ],
        },
    })

    # Chart 6: Key Penman ratios snapshot (latest year)
    ly = len(years) - 1
    specs.append({
        "type": "D", "title": f"{company_name} — Nøgletal (Penman) {years[ly]} [CALC]",
        "note": "RNOA = OI / avg NOA. OG = OI / Omsætning. ATO = Omsætning / avg NOA. "
                "SPREAD = RNOA − NBC. Positiv SPREAD → finansiel gearing skaber værdi [CALC].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Nøgletal", f"{years[ly]} [CALC]"],
            "rows": [
                {"indicator": "RNOA",   "Nøgletal": "RNOA",   f"{years[ly]} [CALC]": _pct(reformulated["RNOA"][ly])},
                {"indicator": "OG",     "Nøgletal": "OG",     f"{years[ly]} [CALC]": _pct(reformulated["OG"][ly])},
                {"indicator": "ATO",    "Nøgletal": "ATO",    f"{years[ly]} [CALC]": f"{reformulated['ATO'][ly]:.2f}x"},
                {"indicator": "ROCE",   "Nøgletal": "ROCE",   f"{years[ly]} [CALC]": _pct(reformulated["ROCE"][ly])},
                {"indicator": "FLEV",   "Nøgletal": "FLEV",   f"{years[ly]} [CALC]": f"{reformulated['FLEV'][ly]:.2f}x"},
                {"indicator": "NBC",    "Nøgletal": "NBC",    f"{years[ly]} [CALC]": _pct(reformulated["NBC"][ly])},
                {"indicator": "SPREAD", "Nøgletal": "SPREAD", f"{years[ly]} [CALC]": _pct(reformulated["SPREAD"][ly])},
            ],
        },
    })

    # Charts 7–12: Type A time series
    specs.append({
        "type": "A", "title": f"{company_name} — Omsætning ({currency}m)",
        "series_labels": [lbl_rev],
        "note": f"10-årig historisk omsætning [CALC]. Revenue CAGR = {_pct(reformulated['historical_avgs']['revenue_cagr'])} (organisk, M&A-justeret [ASSUMED]).",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — Driftsoverskud OI/NOPAT ({currency}m)",
        "series_labels": [lbl_oi],
        "note": f"OI = EBIT × (1 − t). t = {_pct(wacc_data['t'])} [ASSUMED]. Penman definition [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — Frit Cashflow FCF ({currency}m)",
        "series_labels": [lbl_fcf],
        "note": "FCF = OI − ΔNOA (Penman). Første år mangler da ΔNOA kræver forudgående år [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — RNOA, ROCE og SPREAD (%)",
        "series_labels": [lbl_rnoa, lbl_roce, lbl_spread],
        "note": "RNOA = OI / avg NOA. ROCE = Comprehensive NI / avg egenkapital. SPREAD = RNOA − NBC [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — RNOA vs. WACC Spread (%)",
        "series_labels": [lbl_rnoa_vs],
        "note": f"Positiv bar → RNOA > WACC → virksomheden skaber reel driftsøkonomisk værdi. WACC = {_pct(wacc)} [CALC].",
        "kilde": kilde,
    })
    specs.append({
        "type": "A", "title": f"{company_name} — Finansiel Gearing (FLEV) og NFO ({currency}m)",
        "series_labels": [lbl_flev, lbl_nfo],
        "note": "FLEV = NFO / Egenkapital. NFO = Finansielle forpligtelser − Finansielle aktiver (Penman) [CALC].",
        "kilde": kilde,
    })

    # Chart 13: DCF forecast table
    fy    = dcf_results["forecast_years"]
    cols  = fy + ["Terminalår"]
    def _frow(label, vals, terminal_val=None):
        row = {"indicator": label}
        for i, yr in enumerate(fy):
            row[yr] = _num(vals[i]) if vals[i] is not None else ""
        row["Terminalår"] = _num(terminal_val) if terminal_val is not None else ""
        return row

    specs.append({
        "type": "D", "title": f"{company_name} — DCF Forecast Tabel [EST/CALC]",
        "note": (f"5-årig prognose. Omsætningsvækst = {_pct(reformulated['historical_avgs']['revenue_cagr'])} [ASSUMED]. "
                 f"OG avg = {_pct(reformulated['historical_avgs']['OG'])} [CALC]. "
                 f"ATO avg = {reformulated['historical_avgs']['ATO']:.2f}x [CALC]. "
                 f"WACC = {_pct(wacc)} [CALC]."),
        "kilde": kilde,
        "table_data": {
            "columns": cols,
            "rows": [
                _frow(f"Nettoomsætning [EST]", dcf_results["revenue_forecast"]),
                _frow(f"Driftsoverskud (OI) [EST]", dcf_results["OI_forecast"]),
                _frow(f"NOA [EST]", dcf_results["NOA_forecast"]),
                _frow(f"ΔNOA [EST]", dcf_results["dNOA_forecast"]),
                {**{"indicator": "Discount factor [CALC]"}, **{yr: f"{d:.4f}" for yr, d in zip(fy, dcf_results["discount_factors"])}, "Terminalår": ""},
                _frow(f"FCF (OI − ΔNOA) [EST]", dcf_results["FCF_forecast"]),
                _frow(f"Nutidsværdi af FCF [CALC]", dcf_results["PV_FCF"]),
                {"indicator": ""},
                {"indicator": f"Total nutidsværdi [CALC]", "Terminalår": _num(dcf_results["total_PV"])},
                {"indicator": f"Terminalværdi [CALC]",     "Terminalår": _num(dcf_results["TV"])},
                {"indicator": f"Nutidsværdi af terminalværdi [CALC]", "Terminalår": _num(dcf_results["PV_TV"])},
                {"indicator": ""},
                {"indicator": f"Virksomhedsværdi (EV) [CALC]", "Terminalår": _num(dcf_results["EV"])},
                {"indicator": f"NFO [CALC]",                   "Terminalår": _num(dcf_results["NFO"])},
                {"indicator": f"NCI [CALC]",                   "Terminalår": _num(dcf_results["NCI"])},
                {"indicator": f"Egenkapitalværdi [CALC]",      "Terminalår": _num(dcf_results["equity_value"])},
                {"indicator": f"Antal aktier (fortyndet) [SOURCED]", "Terminalår": f"{dcf_results['diluted_shares']:.2f}m"},
                {"indicator": f"Pris per aktie [CALC]",        "Terminalår": f"{dcf_results['price_per_share']:.2f} {currency}"},
            ],
        },
    })

    # Chart 14: DCF bridge summary
    specs.append({
        "type": "D", "title": f"{company_name} — DCF Brobygger [CALC]",
        "note": f"EV = Σ PV(FCF) + PV(TV). Egenkapitalværdi = EV − NFO − NCI. g = {_pct(dcf_results['g'])} [ASSUMED].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Post", "Beløb [CALC]"],
            "rows": [
                {"indicator": "Total nutidsværdi af FCF [CALC]",        "Post": "Σ PV(FCF)",   "Beløb [CALC]": _num(dcf_results["total_PV"])},
                {"indicator": "Nutidsværdi af terminalværdi [CALC]",    "Post": "PV(TV)",      "Beløb [CALC]": _num(dcf_results["PV_TV"])},
                {"indicator": "Virksomhedsværdi (EV) [CALC]",           "Post": "EV",          "Beløb [CALC]": _num(dcf_results["EV"])},
                {"indicator": "Fratruk NFO [CALC]",                     "Post": "− NFO",       "Beløb [CALC]": _num(dcf_results["NFO"])},
                {"indicator": "Fratruk NCI [CALC]",                     "Post": "− NCI",       "Beløb [CALC]": _num(dcf_results["NCI"])},
                {"indicator": "Egenkapitalværdi [CALC]",                "Post": "= Egenkapital","Beløb [CALC]": _num(dcf_results["equity_value"])},
                {"indicator": f"Pris per aktie [CALC]",                 "Post": "÷ aktier",    "Beløb [CALC]": f"{dcf_results['price_per_share']:.2f} {currency}"},
            ],
        },
    })

    # Chart 15: Sensitivity grid (WACC × g → price)
    wacc_axis = sensitivity["wacc_axis"]
    g_axis    = sensitivity["g_axis"]
    wacc_base = sensitivity["wacc_base"]
    g_base    = sensitivity["g_base"]
    sens_cols = [f"WACC {_pct(w)}" for w in wacc_axis]
    sens_rows = []
    for row_idx, g in enumerate(g_axis):
        row = {"indicator": f"g = {_pct(g)} [ASSUMED]"}
        for col_idx, w in enumerate(wacc_axis):
            cell_val = sensitivity["grid"][row_idx][col_idx]
            cell_str = f"{cell_val:.1f}" if cell_val is not None else "—"
            if abs(w - wacc_base) < 1e-6 and abs(g - g_base) < 1e-6:
                cell_str = f"★ {cell_str}"  # highlight base case
            row[f"WACC {_pct(w)}"] = cell_str
        sens_rows.append(row)
    specs.append({
        "type": "D", "title": f"{company_name} — Følsomhedsanalyse: Pris/aktie ({currency}) [CALC]",
        "note": (f"★ = base case (WACC={_pct(wacc_base)}, g={_pct(g_base)}) [ASSUMED]. "
                 f"Pris per aktie varierer med WACC ± 1 pct.point (0,25% trin) og g 1–3% [CALC]."),
        "kilde": kilde,
        "table_data": {"columns": sens_cols, "rows": sens_rows},
    })

    # Chart 16: Fundamental vs market price (type B)
    pct_diff  = (dcf_price - price) / price if price > 0 else 0
    direction = "undervurderet" if dcf_price > price else "overvurderet"
    specs.append({
        "type": "B", "title": f"{company_name} — Fundamental vs. Markedspris ({currency})",
        "series_labels": [lbl_fund, lbl_market],
        "note": (f"Fundamental pris = {dcf_price:.2f} {currency} [CALC]. "
                 f"Markedspris = {price:.2f} {currency} [SOURCED]. "
                 f"Margen: {_pct(abs(pct_diff))} ({direction}). "
                 f"Vurdering baseret på DCF med WACC={_pct(wacc)}, g={_pct(dcf_results['g'])} [ASSUMED]."),
        "kilde": kilde,
    })

    # Chart 17: Multiples table
    metrics = fmp_data.get("metrics", [{}])
    m = metrics[0] if metrics else {}
    specs.append({
        "type": "D", "title": f"{company_name} — Nøgletalssammenligning [SOURCED/CALC]",
        "note": "Trailing multiples fra FMP [SOURCED]. Forward multiples kun hvis analytikerestimat tilgængeligt [EST].",
        "kilde": kilde,
        "table_data": {
            "columns": ["Multipel", "Trailing [SOURCED]"],
            "rows": [
                {"indicator": "P/E",       "Multipel": "P/E",       "Trailing [SOURCED]": f"{m.get('peRatio', 'N/A'):.1f}x" if m.get("peRatio") else "N/A"},
                {"indicator": "EV/EBITDA", "Multipel": "EV/EBITDA", "Trailing [SOURCED]": f"{m.get('evToEbitda', 'N/A'):.1f}x" if m.get("evToEbitda") else "N/A"},
                {"indicator": "P/B",       "Multipel": "P/B",       "Trailing [SOURCED]": f"{m.get('pbRatio', 'N/A'):.1f}x"   if m.get("pbRatio") else "N/A"},
                {"indicator": "P/S",       "Multipel": "P/S",       "Trailing [SOURCED]": f"{m.get('priceToSalesRatio', 'N/A'):.1f}x" if m.get("priceToSalesRatio") else "N/A"},
                {"indicator": "P/FCF",     "Multipel": "P/FCF",     "Trailing [SOURCED]": f"{m.get('pfcfRatio', 'N/A'):.1f}x" if m.get("pfcfRatio") else "N/A"},
            ],
        },
    })

    # Chart 18: Regional revenue breakdown (type G — skip gracefully if unavailable)
    seg_data = fmp_data.get("revenue_segments", [])
    if seg_data:
        lbl_seg = f"{ticker} — Geografisk omsætning"
        seg_latest = seg_data[0] if seg_data else {}
        seg_vals   = {k: v for k, v in seg_latest.items() if k != "date" and v}
        if seg_vals:
            idx  = pd.DatetimeIndex([pd.Timestamp(f"{years[-1]}-12-31")] * len(seg_vals))
            df_g = pd.DataFrame({"value": list(seg_vals.values())},
                                 index=pd.Index(list(seg_vals.keys())))
            dfs[lbl_seg] = df_g
            specs.append({
                "type": "G", "title": f"{company_name} — Geografisk Omsætningsfordeling",
                "series_labels": [lbl_seg],
                "note": f"Geografisk omsætningsfordeling, {years[-1]} [SOURCED].",
                "kilde": kilde,
            })
        else:
            specs.append(_placeholder_chart18(company_name, kilde))
    else:
        specs.append(_placeholder_chart18(company_name, kilde))

    return specs, dfs


def _placeholder_chart18(company_name: str, kilde: str) -> dict:
    return {
        "type": "D", "title": f"{company_name} — Geografisk Omsætning (ikke tilgængelig)",
        "note": "Segmentdata ikke tilgængeligt for denne virksomhed via FMP [SOURCED].",
        "kilde": kilde,
        "table_data": {"columns": ["Status"], "rows": [{"indicator": "Segmentdata ikke tilgængeligt"}]},
    }

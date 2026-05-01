from newsletter_agent.specialists.annual_report_constants import (
    RF_BY_COUNTRY, MSCI_WORLD_35YR_RETURN, MOODY_TO_SPREAD,
    CRP_BY_COUNTRY, STATUTORY_TAX_RATE, normalize_country, icr_to_spread,
)


def compute_wacc(fmp_data: dict, reformulated: dict, hq_country: str) -> dict:
    iso3     = normalize_country(hq_country)
    rf_entry = RF_BY_COUNTRY.get(iso3, RF_BY_COUNTRY["_default"])
    rf       = rf_entry["rate"]
    t        = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])

    profile  = fmp_data.get("profile", {})
    beta_raw = float(profile.get("beta") or 1.0)
    beta_adj = (2 / 3) * beta_raw + (1 / 3)

    MRP = MSCI_WORLD_35YR_RETURN - rf
    CRP = CRP_BY_COUNTRY.get(iso3, CRP_BY_COUNTRY["_default"])
    rE  = rf + beta_adj * (MRP + CRP)

    rating   = ""
    rs_moody = None
    for r in fmp_data.get("rating", []):
        if "moody" in (r.get("ratingAgency") or "").lower():
            rating   = r.get("rating", "")
            rs_moody = MOODY_TO_SPREAD.get(rating)
            break

    income = fmp_data.get("income", [{}])
    ebit   = float(income[0].get("operatingIncome") or 0)
    int_ex = float(income[0].get("interestExpense") or 1)
    icr    = ebit / int_ex if int_ex != 0 else 8.5
    rs_icr = icr_to_spread(icr)

    rs = rs_moody if rs_moody is not None else rs_icr
    if rs_moody is None:
        rating = f"ICR fallback (ICR={icr:.1f})"

    rD = (rf + rs) * (1 - t)

    NFO    = reformulated["NFO"][-1]
    mktcap = float(profile.get("mktCap") or 0)
    D      = max(NFO, 0)
    E      = mktcap
    if E == 0:
        print("  [annual_report] WARNING: mktCap=0 — WACC collapses to pure-debt cost. Check FMP profile.")
    V      = D + E if (D + E) > 0 else 1
    wacc   = (D / V) * rD + (E / V) * rE

    checker_inputs = {
        "rf_re":         rf,
        "rf_rd":         rf,
        "rating_spread": rs,
        "icr_spread":    rs_icr,
        "beta_raw":      beta_raw,
        "beta_adj":      beta_adj,
        "shares_source": "diluted",
        "tax_type":      "statutory",
        "nci_present":   any(v > 0 for v in reformulated["NCI"]),
        "bond_type":     "nominal",
    }

    return {
        "rf": rf, "rf_entry": rf_entry, "t": t,
        "beta_raw": beta_raw, "beta_adj": beta_adj,
        "MRP": MRP, "CRP": CRP, "rE": rE,
        "rating": rating, "rs": rs, "rs_moody": rs_moody, "rs_icr": rs_icr,
        "rD": rD, "D": D, "E": E, "V": V, "wacc": wacc,
        "checker_inputs": checker_inputs,
        "iso3": iso3,
    }


def _dcf_price(reformulated: dict, wacc: float, g: float,
               NFO: float, NCI: float, diluted_shares: float,
               base_year: int, n_years: int = 5) -> tuple:
    avgs     = reformulated["historical_avgs"]
    rev_cagr = avgs["revenue_cagr"]
    og_avg   = avgs["OG"]
    ato_avg  = avgs["ATO"]
    base_rev = reformulated["revenue"][-1]

    forecast_years, rev_f, oi_f, noa_f, dnoa_f, fcf_f, df_f, pv_f = [], [], [], [], [], [], [], []

    # Q1: If latest reported NOA is anomalous vs historical ATO, normalize the starting point.
    # This prevents a spurious first-year ΔNOA reversal from dominating the valuation.
    noa_raw         = reformulated["NOA"][-1]
    noa_ato_implied = base_rev / ato_avg if ato_avg > 0 else noa_raw
    if noa_raw > 2.0 * noa_ato_implied and noa_ato_implied > 0:
        prev_NOA = noa_ato_implied   # ATO-normalised starting NOA
    else:
        prev_NOA = noa_raw

    for t_idx in range(1, n_years + 1):
        yr_label = f"{base_year + t_idx}E"
        rev      = base_rev * ((1 + rev_cagr) ** t_idx)
        oi       = rev * og_avg
        noa      = rev / ato_avg if ato_avg != 0 else prev_NOA
        dnoa     = noa - prev_NOA
        fcf      = oi - dnoa
        disc     = (1 + wacc) ** t_idx
        pv       = fcf / disc

        forecast_years.append(yr_label)
        rev_f.append(rev); oi_f.append(oi); noa_f.append(noa)
        dnoa_f.append(dnoa); fcf_f.append(fcf); df_f.append(disc); pv_f.append(pv)
        prev_NOA = noa

    total_PV = sum(pv_f)
    fcf_t1   = fcf_f[-1] * (1 + g)
    TV       = fcf_t1 / (wacc - g) if (wacc - g) > 0 else 0
    PV_TV    = TV / ((1 + wacc) ** n_years)
    EV       = total_PV + PV_TV
    eq_val   = EV - NFO - NCI
    price    = eq_val / diluted_shares if diluted_shares > 0 else 0

    detail = dict(
        forecast_years=forecast_years,
        revenue_forecast=rev_f, OI_forecast=oi_f,
        NOA_forecast=noa_f, dNOA_forecast=dnoa_f,
        FCF_forecast=fcf_f, discount_factors=df_f, PV_FCF=pv_f,
        total_PV=total_PV, TV=TV, PV_TV=PV_TV, EV=EV,
        NFO=NFO, NCI=NCI, equity_value=eq_val,
        diluted_shares=diluted_shares, price_per_share=price,
        g=g, n_years=n_years,
    )
    return price, detail


def compute_dcf(reformulated: dict, wacc: float, g: float = 0.02,
                NFO: float = 0.0, NCI: float = 0.0,
                diluted_shares: float = 1.0, base_year: int = 2024) -> dict:
    _, detail = _dcf_price(reformulated, wacc, g, NFO, NCI, diluted_shares, base_year)
    return detail


def _analyst_fwd_cagr(estimates: list, base_rev: float):
    """Derive forward CAGR from analyst consensus revenue estimates (already in millions)."""
    if not estimates or base_rev <= 0:
        return None
    valid = sorted(
        [e for e in estimates if (e.get("estimatedRevenueAvg") or 0) > 0],
        key=lambda x: x.get("date", ""),
    )
    if not valid:
        return None
    est_rev = float(valid[-1]["estimatedRevenueAvg"])
    n_yrs   = len(valid)
    return (est_rev / base_rev) ** (1.0 / n_yrs) - 1


def compute_dcf_scenarios(
    reformulated: dict, wacc_base: float,
    NFO: float, NCI: float, diluted_shares: float, base_year: int,
    estimates=None,
) -> dict:
    """Run Bear / Base / Bull DCF scenarios. Returns dict keyed by scenario name."""
    avgs      = reformulated["historical_avgs"]
    hist_cagr = avgs["revenue_cagr"]
    base_rev  = reformulated["revenue"][-1]

    fwd_cagr = _analyst_fwd_cagr(estimates, base_rev)
    base_cagr = fwd_cagr if fwd_cagr is not None else hist_cagr

    scenario_params = {
        "bear": (max(base_cagr - 0.04, -0.02), -0.02, +0.010, 0.015),
        "base": (base_cagr,                     0.00,  0.000,  0.020),
        "bull": (min(base_cagr + 0.04,  0.20),  0.02,  -0.010, 0.025),
    }

    results = {}
    for name, (cagr, og_delta, wacc_delta, g) in scenario_params.items():
        wacc = wacc_base + wacc_delta
        og   = avgs["OG"] + og_delta
        mod  = {**reformulated, "historical_avgs": {**avgs, "OG": og, "revenue_cagr": cagr}}
        price, detail = _dcf_price(mod, wacc, g, NFO, NCI, diluted_shares, base_year)
        results[name] = {
            "price":  round(price, 2),
            "detail": detail,
            "wacc":   round(wacc, 4),
            "og":     round(og, 4),
            "cagr":   round(cagr, 4),
            "g":      g,
        }
    return results


def compute_sensitivity(reformulated: dict, wacc_base: float, g_base: float,
                        NFO: float, NCI: float, diluted_shares: float,
                        base_year: int) -> dict:
    wacc_steps = [round(wacc_base + (i - 4) * 0.0025, 4) for i in range(9)]
    g_steps    = [0.01, 0.015, 0.02, 0.025, 0.03]
    grid       = []
    for g in g_steps:
        row = []
        for w in wacc_steps:
            if w <= g:
                row.append(None)
            else:
                price, _ = _dcf_price(reformulated, w, g, NFO, NCI, diluted_shares, base_year)
                row.append(round(price, 2))
        grid.append(row)
    return {
        "wacc_axis": wacc_steps,
        "g_axis":    g_steps,
        "grid":      grid,
        "wacc_base": wacc_base,
        "g_base":    g_base,
    }

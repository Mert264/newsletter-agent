from __future__ import annotations

import os

from newsletter_agent.specialists.annual_report_constants import (
    RF_BY_COUNTRY, US_MATURE_ERP, MOODY_TO_SPREAD,
    CRP_BY_COUNTRY, STATUTORY_TAX_RATE, normalize_country, icr_to_spread,
)


def _fetch_us10y_from_fred() -> float | None:
    """Fetch the latest US 10-year Treasury yield (DGS10) from FRED.

    Returns the yield as a decimal (e.g. 0.044 for 4.4%) or None on failure.
    Never raises — always wraps in try/except so the pipeline cannot crash.
    """
    try:
        from fredapi import Fred
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            return None
        fred = Fred(api_key=api_key)
        series = fred.get_series("DGS10", observation_start="2020-01-01")
        series = series.dropna()
        if series.empty:
            return None
        latest_pct = float(series.iloc[-1])   # FRED returns percent (e.g. 4.40)
        return round(latest_pct / 100, 6)
    except Exception as exc:
        print(f"  [annual_report] FRED fetch failed — falling back to hardcoded rf: {exc}")
        return None


def _live_rf(iso3: str, rf_entry: dict) -> tuple:
    """Return (rf, source_label) using live FRED data for the base rate when available.

    For all countries the US 10-yr Treasury is used as the base risk-free rate
    (standard global DCF practice); country risk is captured via CRP.
    If FRED is unavailable, falls back to the hardcoded spot rate in RF_BY_COUNTRY.
    """
    us_live = _fetch_us10y_from_fred()
    if us_live is not None:
        if iso3 == "USA":
            return us_live, f"FRED DGS10 live ({us_live * 100:.2f}%)"
        else:
            # Shift local hardcoded spot by the delta between live and hardcoded USA spot
            usa_hardcoded_spot = RF_BY_COUNTRY.get("USA", RF_BY_COUNTRY["_default"])["spot"]
            delta = us_live - usa_hardcoded_spot
            adjusted = round(rf_entry["spot"] + delta, 6)
            return adjusted, f"local govt bond + FRED DGS10 delta ({us_live * 100:.2f}%)"
    return rf_entry["spot"], "hardcoded spot (FRED unavailable)"


def compute_wacc(fmp_data: dict, reformulated: dict, hq_country: str) -> dict:
    iso3     = normalize_country(hq_country)
    rf_entry = RF_BY_COUNTRY.get(iso3, RF_BY_COUNTRY["_default"])
    rf, rf_source = _live_rf(iso3, rf_entry)
    t        = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])

    profile  = fmp_data.get("profile", {})
    beta_raw = float(profile.get("beta") or 1.0)
    beta_adj = (2 / 3) * beta_raw + (1 / 3)

    MRP = US_MATURE_ERP
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
        icr_display = "Aaa equiv." if icr > 100 else f"{icr:.1f}"
        rating = f"ICR fallback (ICR={icr_display})"

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
        "rf_source":     rf_source,
        "rating_spread": rs,
        "icr_spread":    rs_icr,
        "beta_raw":      beta_raw,
        "beta_adj":      beta_adj,
        "shares_source": "diluted",
        "tax_type":      "statutory",
        "nci_present":   any(v > 0 for v in reformulated["NCI"]),
        "bond_type":     "live" if "FRED" in rf_source else "spot",
    }

    return {
        "rf": rf, "rf_source": rf_source, "rf_entry": rf_entry, "t": t,
        "beta_raw": beta_raw, "beta_adj": beta_adj,
        "MRP": MRP, "CRP": CRP, "rE": rE,
        "rating": rating, "rs": rs, "rs_moody": rs_moody, "rs_icr": rs_icr,
        "rD": rD, "D": D, "E": E, "V": V, "wacc": wacc,
        "checker_inputs": checker_inputs,
        "iso3": iso3,
    }


def _dcf_price(reformulated: dict, wacc: float, g: float,
               NFO: float, NCI: float, diluted_shares: float,
               base_year: int, n_years: int = 5,
               consensus_revs: list = None) -> tuple:
    """Build DCF forecast.

    consensus_revs: optional list of analyst consensus revenue values (millions) for
    years 1..len(consensus_revs).  Those years are labelled '[C]' (consensus) in
    forecast_years; remaining years fall back to historical CAGR, labelled '[H]'.
    If None or empty, all years use historical CAGR (pure '[H]' behaviour).
    """
    avgs     = reformulated["historical_avgs"]
    rev_cagr = avgs["revenue_cagr"]
    og_avg   = avgs["OG"]
    ato_avg  = avgs["ATO"]
    base_rev = reformulated["revenue"][-1]

    # Filter out zero/null consensus values so bad data gracefully falls back to CAGR
    c_revs = [r for r in (consensus_revs or []) if r and r > 0]

    forecast_years, rev_f, oi_f, noa_f, dnoa_f, fcf_f, df_f, pv_f = [], [], [], [], [], [], [], []
    rev_source = []  # "consensus" or "historical" per year — stored in detail for display

    # Q1: If latest reported NOA is anomalous vs historical ATO, normalize the starting point.
    # This prevents a spurious first-year ΔNOA reversal from dominating the valuation.
    noa_raw         = reformulated["NOA"][-1]
    noa_ato_implied = base_rev / ato_avg if ato_avg > 0 else noa_raw
    if noa_raw > 2.0 * noa_ato_implied and noa_ato_implied > 0:
        prev_NOA = noa_ato_implied   # ATO-normalised starting NOA
    else:
        prev_NOA = noa_raw

    for t_idx in range(1, n_years + 1):
        # Use analyst consensus for covered years; fall back to CAGR for the rest
        if t_idx <= len(c_revs):
            rev    = c_revs[t_idx - 1]
            source = "consensus"
            suffix = " (est.)"
        else:
            rev    = base_rev * ((1 + rev_cagr) ** t_idx)
            source = "historical"
            suffix = " (proj.)"

        yr_label = f"{base_year + t_idx}E{suffix}"
        oi       = rev * og_avg
        noa      = rev / ato_avg if ato_avg != 0 else prev_NOA
        dnoa     = noa - prev_NOA
        fcf      = oi - dnoa
        disc     = (1 + wacc) ** t_idx
        pv       = fcf / disc

        forecast_years.append(yr_label)
        rev_f.append(rev); oi_f.append(oi); noa_f.append(noa)
        dnoa_f.append(dnoa); fcf_f.append(fcf); df_f.append(disc); pv_f.append(pv)
        rev_source.append(source)
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
        revenue_source=rev_source,
        consensus_years=len(c_revs),
    )
    return price, detail


def compute_dcf(reformulated: dict, wacc: float, g: float = 0.02,
                NFO: float = 0.0, NCI: float = 0.0,
                diluted_shares: float = 1.0, base_year: int = 2024,
                consensus_revs: list = None) -> dict:
    _, detail = _dcf_price(reformulated, wacc, g, NFO, NCI, diluted_shares, base_year,
                           consensus_revs=consensus_revs)
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


def _analyst_consensus_revs(estimates: list, base_year: int, n_consensus: int = 2) -> list:
    """Return up to `n_consensus` per-year consensus revenue estimates sorted by fiscal year.

    Returns a list of floats (in millions) indexed from year 1 onwards, covering only
    future fiscal years relative to base_year. Empty list if no usable estimates.
    """
    if not estimates:
        return []
    future = sorted(
        [
            e for e in estimates
            if (e.get("estimatedRevenueAvg") or 0) > 0
            and int(str(e.get("date", "0"))[:4]) > base_year
        ],
        key=lambda x: x.get("date", ""),
    )
    return [float(e["estimatedRevenueAvg"]) for e in future[:n_consensus]]


def compute_dcf_scenarios(
    reformulated: dict, wacc_base: float,
    NFO: float, NCI: float, diluted_shares: float, base_year: int,
    estimates=None, ltm_income=None,
) -> dict:
    """Run Bear / Base / Bull DCF scenarios. Returns dict keyed by scenario name."""
    avgs      = reformulated["historical_avgs"]
    hist_cagr = avgs["revenue_cagr"]

    # Determine DCF base revenue: LTM > last full FY > 3yr trailing avg (if latest year flagged)
    excluded = reformulated.get("excluded_years", set())
    latest_yr = reformulated["years"][-1] if reformulated["years"] else None
    if ltm_income and float(ltm_income.get("revenue") or 0) > 0:
        base_rev = float(ltm_income["revenue"])
    elif latest_yr in excluded:
        valid_rev = [(y, r) for y, r in zip(reformulated["years"], reformulated["revenue"])
                     if y not in excluded]
        trailing = valid_rev[-3:] if len(valid_rev) >= 3 else valid_rev
        base_rev = sum(r for _, r in trailing) / len(trailing) if trailing else reformulated["revenue"][-1]
        print(f"  [annual_report] INFO: Latest year {latest_yr} flagged — using 3yr trailing avg revenue as DCF base ({base_rev:,.0f})")
    else:
        base_rev = reformulated["revenue"][-1]

    _MAX_HIST_CAGR = 0.12
    fwd_cagr = _analyst_fwd_cagr(estimates, base_rev)
    if fwd_cagr is not None:
        base_cagr = fwd_cagr
    else:
        base_cagr = min(hist_cagr, _MAX_HIST_CAGR)
        if hist_cagr > _MAX_HIST_CAGR:
            print(f"  [annual_report] INFO: Capped hist CAGR from {hist_cagr:.1%} to {_MAX_HIST_CAGR:.0%} (no analyst consensus to validate)")

    # Extract per-year consensus revenues for the base scenario (years 1-2).
    # Bear/bull scenarios keep CAGR-only so the consensus anchor stays in base only.
    base_consensus_revs = _analyst_consensus_revs(estimates or [], base_year)
    if base_consensus_revs:
        print(f"  [annual_report] INFO: Using analyst consensus for {len(base_consensus_revs)} DCF year(s) "
              f"({', '.join(f'{r:,.0f}' for r in base_consensus_revs)}), "
              f"falling back to CAGR ({base_cagr:.1%}) for remaining years.")
    else:
        print(f"  [annual_report] INFO: No analyst consensus revenue data — using CAGR ({base_cagr:.1%}) for all DCF years.")

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
        # Only the base scenario uses per-year consensus revs; bear/bull use CAGR throughout
        c_revs = base_consensus_revs if name == "base" else None
        price, detail = _dcf_price(mod, wacc, g, NFO, NCI, diluted_shares, base_year,
                                   consensus_revs=c_revs)
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

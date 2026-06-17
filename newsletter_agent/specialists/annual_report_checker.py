def check(wacc_inputs: dict) -> dict:
    issues = []

    rf_re = wacc_inputs["rf_re"]
    rf_rd = wacc_inputs["rf_rd"]
    if abs(rf_re - rf_rd) > 1e-6:
        issues.append(
            f"rf mismatch: rf used in rE ({rf_re:.4f}) ≠ rf used in rD ({rf_rd:.4f}). "
            f"Both must use the same country-matched historical avg. [BLOCK]"
        )

    rating_spread = wacc_inputs["rating_spread"]
    icr_spread    = wacc_inputs["icr_spread"]
    if abs(rating_spread - icr_spread) > 0.005:
        issues.append(
            f"Credit spread divergence: Moody's-implied rs={rating_spread:.4f} vs "
            f"ICR-implied rs={icr_spread:.4f} (diff={abs(rating_spread - icr_spread):.4f} > 0.5%). "
            f"Verify rating or recompute ICR. [BLOCK]"
        )

    beta_raw = wacc_inputs["beta_raw"]
    beta_adj = wacc_inputs["beta_adj"]
    expected_adj = (2 / 3) * beta_raw + (1 / 3)
    if abs(beta_adj - expected_adj) > 0.001:
        issues.append(
            f"β_adj={beta_adj:.4f} does not match Blume formula (2/3×β_raw+1/3={expected_adj:.4f}). "
            f"β_raw={beta_raw}. Always apply Blume adjustment. [BLOCK]"
        )

    if wacc_inputs.get("shares_source") != "diluted":
        issues.append(
            "Shares outstanding must be diluted (from FMP weightedAverageShsOutDil), "
            "not basic. Basic shares overstates price per share. [BLOCK]"
        )

    if wacc_inputs.get("tax_type") != "statutory":
        issues.append(
            "Tax rate must be statutory corporate rate, not effective rate. "
            "Effective rate fluctuates with one-time items. [BLOCK]"
        )

    # NCI is always subtracted in compute_dcf (EV − NFO − NCI = equity value).
    # Gate removed: firing on nci_present=False blocked companies with no minority interest.

    if wacc_inputs.get("bond_type") == "inflation_linked":
        issues.append(
            "rf source is an inflation-linked bond. Must use nominal government bond. "
            "Mixing real rf with nominal g=2% silently inflates terminal value. [BLOCK]"
        )

    # ── Output validation (post-DCF) ──
    scenarios = wacc_inputs.get("scenarios", {})
    for sc_name, sc in scenarios.items():
        if not isinstance(sc, dict):
            continue
        sc_wacc = sc.get("wacc", 0)
        sc_g = sc.get("g", 0)
        if sc_wacc <= sc_g:
            issues.append(
                f"Scenario '{sc_name}': WACC ({sc_wacc:.4f}) ≤ terminal g ({sc_g:.4f}). "
                f"Terminal value is undefined — valuation invalid. [BLOCK]"
            )
        sc_price = sc.get("price")
        if sc_price is not None and sc_price < 0:
            issues.append(
                f"Scenario '{sc_name}': negative equity value (price={sc_price:.2f}). "
                f"Debt exceeds enterprise value. [BLOCK]"
            )

    diluted_shares = wacc_inputs.get("diluted_shares", 1)
    if diluted_shares <= 0:
        issues.append(
            f"Diluted shares outstanding = {diluted_shares}. Must be > 0. [BLOCK]"
        )

    fcf_forecast = wacc_inputs.get("fcf_forecast", [])
    if fcf_forecast:
        neg_years = sum(1 for f in fcf_forecast if f < 0)
        if neg_years > 3:
            issues.append(
                f"Negative FCF in {neg_years}/5 forecast years. "
                f"Persistent negative FCF makes DCF unreliable. [BLOCK]"
            )

    return {"passed": len(issues) == 0, "issues": issues}

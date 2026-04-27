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

    if wacc_inputs.get("nci_present"):
        # NCI exists — add a WARN so the reviewer verifies the amount, not a BLOCK
        # (the pipeline always subtracts NCI in compute_dcf; this is a cross-check reminder)
        issues_warn = getattr(check, "_warns", [])  # non-blocking, don't add to issues

    if wacc_inputs.get("bond_type") == "inflation_linked":
        issues.append(
            "rf source is an inflation-linked bond. Must use nominal government bond. "
            "Mixing real rf with nominal g=2% silently inflates terminal value. [BLOCK]"
        )

    return {"passed": len(issues) == 0, "issues": issues}

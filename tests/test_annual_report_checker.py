from newsletter_agent.specialists.annual_report_checker import check


def _valid_inputs():
    return {
        "rf_re":         0.0384,
        "rf_rd":         0.0384,
        "rating_spread": 0.0125,
        "icr_spread":    0.0130,   # within 0.5% of 0.0125
        "beta_raw":      0.85,
        "beta_adj":      0.9000,   # 2/3*0.85 + 1/3
        "shares_source": "diluted",
        "tax_type":      "statutory",
        "nci_present":   True,
        "bond_type":     "nominal",
    }


def test_all_checks_pass():
    result = check(_valid_inputs())
    assert result["passed"] is True
    assert result["issues"] == []


def test_rf_mismatch_fails():
    inputs = _valid_inputs()
    inputs["rf_rd"] = 0.0432
    result = check(inputs)
    assert result["passed"] is False
    assert any("rf" in issue.lower() for issue in result["issues"])


def test_spread_divergence_fails():
    inputs = _valid_inputs()
    inputs["icr_spread"] = 0.0200   # >0.5% from 0.0125
    result = check(inputs)
    assert result["passed"] is False
    assert any("spread" in issue.lower() for issue in result["issues"])


def test_blume_not_applied_fails():
    inputs = _valid_inputs()
    inputs["beta_adj"] = inputs["beta_raw"]   # β_adj == β_raw means Blume not applied
    result = check(inputs)
    assert result["passed"] is False
    assert any("blume" in issue.lower() or "β_adj" in issue for issue in result["issues"])


def test_basic_shares_fails():
    inputs = _valid_inputs()
    inputs["shares_source"] = "basic"
    result = check(inputs)
    assert result["passed"] is False


def test_effective_tax_fails():
    inputs = _valid_inputs()
    inputs["tax_type"] = "effective"
    result = check(inputs)
    assert result["passed"] is False


def test_nci_absent_fails():
    inputs = _valid_inputs()
    inputs["nci_present"] = False
    result = check(inputs)
    assert result["passed"] is False


def test_inflation_linked_bond_fails():
    inputs = _valid_inputs()
    inputs["bond_type"] = "inflation_linked"
    result = check(inputs)
    assert result["passed"] is False
    assert any("nominal" in issue.lower() or "inflation" in issue.lower() for issue in result["issues"])

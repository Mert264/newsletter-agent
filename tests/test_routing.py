from newsletter_agent.routing import get_routing_hint


def test_eu_energy_triggers_eurostat():
    hint = get_routing_hint("Vis EU's energimix over de seneste 10 år")
    assert "eurostat" in hint.lower()
    assert "eu_energy_mix" in hint


def test_us_energy_triggers_eia():
    hint = get_routing_hint("USA's energiforbrug fordelt på brændstofstype")
    assert "eia_mix" in hint


def test_cross_region_gas_triggers_conversion():
    hint = get_routing_hint("Sammenlign EU TTF naturgas med US Henry Hub gaspriser")
    assert "EUR_MWh_to_USD_MWh" in hint
    assert "USD_MMBtu_to_USD_MWh" in hint


def test_eu_inflation_triggers_eurostat_hicp():
    hint = get_routing_hint("EU inflation og HICP siden 2022")
    assert "eu_hicp" in hint


def test_eu_unemployment_triggers_eurostat():
    hint = get_routing_hint("Eurozone ledighed fra 2020 til i dag")
    assert "eu_unemployment" in hint


def test_unrelated_brief_returns_empty():
    hint = get_routing_hint("S&P 500 og Nasdaq performance siden 2023")
    assert hint == ""


def test_eu_gdp_triggers_eurostat():
    hint = get_routing_hint("EU BNP vækst og ECB renten")
    assert "eu_gdp_growth" in hint

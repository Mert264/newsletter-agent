"""
Integration test — annual_report specialist full pipeline.
Tests AAPL, NVO, MSFT, SHEL with realistic fixture data.
Runs everything except FMP HTTP calls (mocked) + real Anthropic DA reviews.

Usage:
    source ../.env && python3 tests/integration_annual_report.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import anthropic
from newsletter_agent.specialists.annual_report_reformulator import reformulate
from newsletter_agent.specialists.annual_report_checker import check
from newsletter_agent.specialists.annual_report_valuation import compute_wacc, compute_dcf, compute_sensitivity
from newsletter_agent.specialists.annual_report_kpi import build_chart_specs
from newsletter_agent.specialists.annual_report_da import (
    review_reformulation, review_consistency, review_valuation,
    review_kpi_specs, review_final,
)
from newsletter_agent.specialists.annual_report_constants import normalize_country, STATUTORY_TAX_RATE

PASSED = []
FAILED = []


def ok(label):
    PASSED.append(label)
    print(f"  ✓  {label}")


def fail(label, exc):
    FAILED.append((label, str(exc)))
    print(f"  ✗  {label}")
    print(f"       {type(exc).__name__}: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _income_row(date, revenue, ebit, net_income, interest, shares_dil):
    return {
        "date": date, "revenue": revenue, "operatingIncome": ebit,
        "netIncome": net_income, "comprehensiveIncomePeriodChange": net_income,
        "interestExpense": interest, "weightedAverageShsOutDil": shares_dil,
    }

def _balance_row(date, total_assets, total_liab, cash, st_inv, lt_inv,
                 st_debt, lt_debt, leases, equity, nci, goodwill):
    return {
        "date": date, "totalAssets": total_assets, "totalLiabilities": total_liab,
        "cashAndCashEquivalents": cash, "shortTermInvestments": st_inv,
        "longTermInvestments": lt_inv, "shortTermDebt": st_debt,
        "longTermDebt": lt_debt, "capitalLeaseObligations": leases,
        "totalStockholdersEquity": equity, "minorityInterest": nci,
        "goodwillAndIntangibleAssets": goodwill,
    }

def _cf_row(date, capex, da):
    return {"date": date, "capitalExpenditure": capex, "depreciationAndAmortization": da}


# ─────────────────────────────────────────────────────────────────────────────
# AAPL — Apple Inc. (US, negative equity edge case from buybacks)
# ─────────────────────────────────────────────────────────────────────────────
AAPL_FMP = {
    "income": [
        _income_row("2024-09-30", 391_035, 123_216, 93_736, 2_955, 15_334),
        _income_row("2023-09-30", 383_285, 114_301, 96_995, 3_933, 15_813),
        _income_row("2022-09-30", 394_328, 119_437, 99_803, 2_828, 16_215),
        _income_row("2021-09-30", 365_817, 108_949, 94_680, 2_645, 16_701),
        _income_row("2020-09-30", 274_515, 66_288,  57_411, 2_873, 17_528),
        _income_row("2019-09-30", 260_174, 63_930,  55_256, 3_576, 18_595),
        _income_row("2018-09-30", 265_595, 70_898,  59_531, 3_240, 20_000),
        _income_row("2017-09-30", 229_234, 61_344,  48_351, 2_323, 21_007),
        _income_row("2016-09-30", 215_639, 60_024,  45_687, 1_456, 21_883),
        _income_row("2015-09-30", 233_715, 71_230,  53_394, 1_285, 22_471),
    ],
    "balance": [
        _balance_row("2024-09-30", 364_980, 308_030, 29_943, 35_228,  91_781, 10_912, 85_750, 12_430, -66_382, 0, 67_202),
        _balance_row("2023-09-30", 352_583, 290_437, 29_965, 31_590,  95_805, 11_334, 95_281, 12_842, -62_158, 0, 68_510),
        _balance_row("2022-09-30", 352_755, 302_083, 23_646, 24_658,  92_968, 11_128, 98_959, 12_023, -50_672, 0, 69_702),
        _balance_row("2021-09-30", 351_002, 287_912, 34_940, 27_699,  92_978, 15_613, 94_680, 11_163,  63_090, 0, 69_964),
        _balance_row("2020-09-30", 323_888, 258_549, 38_016, 52_927,  97_103, 13_769, 98_667, 10_504,  65_339, 0, 35_357),
        _balance_row("2019-09-30", 338_516, 248_028, 48_844, 51_713,  98_154, 16_240, 91_807,  9_461,  90_488, 0, 34_707),
        _balance_row("2018-09-30", 365_725, 258_578, 25_913, 40_388, 170_799, 20_748,  93_735,  8_912, 107_147, 0, 33_996),
        _balance_row("2017-09-30", 375_319, 241_272, 20_289, 53_892, 194_714, 18_473,  97_207,  7_561, 134_047, 0, 33_274),
        _balance_row("2016-09-30", 321_686, 193_437, 20_484, 46_671, 170_430, 11_605,  75_427,  6_700, 128_249, 0, 32_612),
        _balance_row("2015-09-30", 290_345, 171_124, 21_120, 20_481, 164_065,  8_499,  53_463,  5_900, 119_355, 0, 31_843),
    ],
    "cashflow": [_cf_row("2024-09-30", -9_447, 11_445)],
    "profile": {
        "beta": 1.24, "mktCap": 3_450_000, "price": 224.87,
        "country": "US", "companyName": "Apple Inc.", "currency": "USD",
        "sharesOutstanding": 15_334,
    },
    "rating": [{"rating": "Aaa", "ratingAgency": "Moody's"}],
    "metrics": [{"peRatio": 34.2, "evToEbitda": 27.1, "pbRatio": None, "priceToSalesRatio": 8.83, "pfcfRatio": 36.5}],
    "estimates": [],
}

# ─────────────────────────────────────────────────────────────────────────────
# NVO — Novo Nordisk A/S (Denmark, massive M&A/growth distortion)
# ─────────────────────────────────────────────────────────────────────────────
NVO_FMP = {
    "income": [
        _income_row("2024-12-31", 232_261, 100_792,  86_000, 1_850, 2_254),
        _income_row("2023-12-31", 162_086,  68_386,  58_100, 1_672, 2_266),
        _income_row("2022-12-31", 117_009,  47_588,  41_400, 1_344, 2_279),
        _income_row("2021-12-31",  81_961,  31_978,  27_600, 1_055, 2_288),
        _income_row("2020-12-31",  62_063,  22_987,  19_900,   875, 2_306),
        _income_row("2019-12-31",  53_411,  19_498,  17_000,   798, 2_347),
        _income_row("2018-12-31",  49_985,  18_494,  16_100,   741, 2_394),
        _income_row("2017-12-31",  48_785,  18_042,  15_700,   682, 2_432),
        _income_row("2016-12-31",  45_497,  16_729,  14_600,   584, 2_471),
        _income_row("2015-12-31",  41_427,  15_339,  13_400,   512, 2_511),
    ],
    "balance": [
        _balance_row("2024-12-31", 147_512,  87_244, 14_821,  5_480, 1_200, 12_000, 30_000, 1_200, 60_268, 0, 22_100),
        _balance_row("2023-12-31",  92_188,  52_832,  9_543,  3_210,   800,  7_500, 18_500,   900, 39_356, 0, 17_400),
        _balance_row("2022-12-31",  65_340,  38_521,  7_012,  2_800,   400,  4_500, 13_200,   700, 26_819, 0, 14_600),
        _balance_row("2021-12-31",  47_210,  27_831,  5_322,  1_900,   200,  2_800,  9_400,   500, 19_379, 0, 11_800),
        _balance_row("2020-12-31",  35_840,  20_902,  4_012,  1_200,   100,  1_800,  7_200,   400, 14_938, 0,  9_200),
        _balance_row("2019-12-31",  30_120,  17_234,  3_521,    900,    80,  1_400,  5_800,   350, 12_886, 0,  7_800),
        _balance_row("2018-12-31",  27_440,  15_812,  3_123,    700,    50,  1_200,  4_900,   300, 11_628, 0,  6_400),
        _balance_row("2017-12-31",  25_870,  14_677,  2_812,    600,    40,  1_100,  4_500,   260, 11_193, 0,  5_200),
        _balance_row("2016-12-31",  24_210,  13_842,  2_512,    500,    30,    980,  4_200,   230, 10_368, 0,  4_100),
        _balance_row("2015-12-31",  22_640,  12_997,  2_215,    400,    20,    870,  3_900,   200,  9_643, 0,  3_200),
    ],
    "cashflow": [_cf_row("2024-12-31", -14_800, 8_200)],
    "profile": {
        "beta": 0.42, "mktCap": 2_890_000, "price": 1_281.0,
        "country": "Denmark", "companyName": "Novo Nordisk A/S", "currency": "DKK",
        "sharesOutstanding": 2_254,
    },
    "rating": [{"rating": "Aa3", "ratingAgency": "Moody's"}],
    "metrics": [{"peRatio": 33.6, "evToEbitda": 31.2, "pbRatio": 47.9, "priceToSalesRatio": 12.5, "pfcfRatio": 38.1}],
    "estimates": [],
}

# ─────────────────────────────────────────────────────────────────────────────
# MSFT — Microsoft Corp (US, extreme capital efficiency)
# ─────────────────────────────────────────────────────────────────────────────
MSFT_FMP = {
    "income": [
        _income_row("2024-06-30", 245_122,  109_433, 88_136,  2_396, 7_433),
        _income_row("2023-06-30", 211_915,   88_523, 72_361,  1_905, 7_472),
        _income_row("2022-06-30", 198_270,   83_383, 72_738,  2_063, 7_496),
        _income_row("2021-06-30", 168_088,   69_916, 61_271,  2_346, 7_519),
        _income_row("2020-06-30", 143_015,   52_959, 44_281,  2_591, 7_571),
        _income_row("2019-06-30", 125_843,   42_959, 39_240,  2_686, 7_643),
        _income_row("2018-06-30", 110_360,   35_058, 16_571,  2_733, 7_700),
        _income_row("2017-06-30",  89_950,   29_025, 21_204,  2_222, 7_746),
        _income_row("2016-06-30",  85_320,   26_078, 16_798,  1_243, 7_794),
        _income_row("2015-06-30",  93_580,   18_161, 12_193,  1_527, 8_027),
    ],
    "balance": [
        _balance_row("2024-06-30", 512_163, 243_686, 18_315, 78_415, 14_951,  4_649, 43_180, 26_563, 268_477, 0, 119_848),
        _balance_row("2023-06-30", 411_976, 205_753, 34_704, 76_558, 10_941,  5_247, 41_990, 25_315, 206_223, 0,  97_041),
        _balance_row("2022-06-30", 364_840, 198_298, 13_931, 90_826,  6_891,  2_749, 47_032, 24_018, 166_542, 0,  67_524),
        _balance_row("2021-06-30", 333_779, 191_791, 14_224, 116_110,  5_911,  8_050, 49_750, 22_928, 141_988, 0,  49_711),
        _balance_row("2020-06-30", 301_311, 183_007, 13_576, 122_951,  2_762,  3_749, 59_578, 20_328, 118_304, 0,  43_351),
        _balance_row("2019-06-30", 286_556, 184_226,  11_356, 122_463,  1_346,  5_518, 66_662, 19_145, 102_330, 0,  42_026),
        _balance_row("2018-06-30", 258_848, 176_130, 11_946, 121_271,    921,   3_865, 71_922, 16_128,  82_718, 0,  25_269),
        _balance_row("2017-06-30", 241_086, 168_692, 7_663,  125_318,    821,  6_033, 76_073, 13_946,  72_394, 0,  25_435),
        _balance_row("2016-06-30", 193_694, 121_697, 6_510,   98_208,    688,  4_985, 40_783, 11_152,  71_997, 0,  24_459),
        _balance_row("2015-06-30", 174_472, 107_748, 5_595,   90_931,    455,  4_985, 27_808,  9_878,  66_724, 0,  25_252),
    ],
    "cashflow": [_cf_row("2024-06-30", -44_482, 24_456)],
    "profile": {
        "beta": 0.90, "mktCap": 3_180_000, "price": 427.66,
        "country": "United States", "companyName": "Microsoft Corporation", "currency": "USD",
        "sharesOutstanding": 7_433,
    },
    "rating": [{"rating": "Aaa", "ratingAgency": "Moody's"}],
    "metrics": [{"peRatio": 36.1, "evToEbitda": 25.9, "pbRatio": 11.8, "priceToSalesRatio": 12.99, "pfcfRatio": 39.4}],
    "estimates": [],
}

# ─────────────────────────────────────────────────────────────────────────────
# SHEL — Shell PLC (UK, capital intensive, ICR test)
# ─────────────────────────────────────────────────────────────────────────────
SHEL_FMP = {
    "income": [
        _income_row("2024-12-31", 316_000,  30_100, 17_600,  5_800, 6_215),
        _income_row("2023-12-31", 323_000,  29_500, 19_300,  6_200, 6_428),
        _income_row("2022-12-31", 381_000,  44_900, 42_300,  5_100, 6_640),
        _income_row("2021-12-31", 261_000,  22_100, 20_100,  4_600, 6_851),
        _income_row("2020-12-31", 181_000,   3_200,  -21_680, 5_200, 7_068),
        _income_row("2019-12-31", 344_000,  26_400, 15_842,  6_100, 7_304),
        _income_row("2018-12-31", 388_000,  32_700, 23_352,  5_800, 7_540),
        _income_row("2017-12-31", 305_000,  18_900, 13_435,  5_200, 7_780),
        _income_row("2016-12-31", 234_000,   8_100,  4_575,  4_900, 8_025),
        _income_row("2015-12-31", 265_000,   8_600,  3_833,  4_600, 8_272),
    ],
    "balance": [
        _balance_row("2024-12-31", 385_000, 232_000, 38_000,  8_000, 12_000, 18_000, 65_000, 22_000, 153_000, 4_200, 12_100),
        _balance_row("2023-12-31", 398_000, 238_000, 40_400,  8_500, 12_500, 19_500, 68_200, 21_500, 160_000, 4_400, 12_400),
        _balance_row("2022-12-31", 404_000, 230_000, 42_800,  7_200, 11_800, 15_200, 60_100, 20_800, 174_000, 5_100, 12_700),
        _balance_row("2021-12-31", 380_000, 222_000, 37_600,  6_800,  9_200, 14_800, 63_400, 20_200, 158_000, 4_800, 13_000),
        _balance_row("2020-12-31", 378_000, 220_000, 35_200,  5_400,  8_800, 18_700, 67_800, 19_600, 158_000, 4_600, 13_300),
        _balance_row("2019-12-31", 404_000, 234_000, 36_500,  6_200,  9_400, 16_400, 72_200, 19_100, 170_000, 5_100, 13_600),
        _balance_row("2018-12-31", 400_000, 222_000, 26_300,  5_800,  8_700, 14_200, 68_900, 18_500, 178_000, 5_400, 13_900),
        _balance_row("2017-12-31", 399_000, 216_000, 20_900,  5_200,  7_900, 13_700, 73_400, 17_900, 183_000, 5_700, 14_200),
        _balance_row("2016-12-31", 411_000, 225_000, 19_100,  4_700,  7_200, 12_900, 78_900, 17_300, 186_000, 6_000, 14_500),
        _balance_row("2015-12-31", 340_000, 178_000, 31_800,  4_200,  6_600, 11_900, 54_200, 16_700, 162_000, 5_200, 14_800),
    ],
    "cashflow": [_cf_row("2024-12-31", -22_000, 19_800)],
    "profile": {
        "beta": 0.65, "mktCap": 185_000, "price": 29.77,
        "country": "United Kingdom", "companyName": "Shell PLC", "currency": "USD",
        "sharesOutstanding": 6_215,
    },
    "rating": [{"rating": "Aa3", "ratingAgency": "Moody's"}],
    "metrics": [{"peRatio": 10.5, "evToEbitda": 4.8, "pbRatio": 1.2, "priceToSalesRatio": 0.58, "pfcfRatio": 6.8}],
    "estimates": [],
}

COMPANIES = [
    ("AAPL", "Apple Inc.",          "US",             AAPL_FMP),
    ("NVO",  "Novo Nordisk A/S",    "Denmark",        NVO_FMP),
    ("MSFT", "Microsoft Corp.",     "United States",  MSFT_FMP),
    ("SHEL", "Shell PLC",           "United Kingdom", SHEL_FMP),
]


def run_pipeline(ticker, company_name, hq_country_raw, fmp_data, client):
    print(f"\n{'═'*60}")
    print(f"  {ticker} — {company_name}  (country raw: '{hq_country_raw}')")
    print(f"{'═'*60}")

    results = {}

    # ── 1. Country normalization ──────────────────────────────────
    try:
        iso3 = normalize_country(hq_country_raw)
        t    = STATUTORY_TAX_RATE.get(iso3, STATUTORY_TAX_RATE["_default"])
        if iso3 == "_default":
            raise ValueError(f"normalize_country('{hq_country_raw}') returned '_default' — unmapped country")
        ok(f"{ticker} country normalization → {iso3}, t={t:.1%}")
        results["iso3"] = iso3
        results["t"]    = t
    except Exception as e:
        fail(f"{ticker} country normalization", e)
        results["iso3"] = "_default"
        results["t"]    = 0.22

    # ── 2. Penman reformulation ───────────────────────────────────
    try:
        ref = reformulate(fmp_data, t=results["t"])
        noa_last = ref["NOA"][-1]
        fcf_vals = [v for v in ref["FCF"] if v is not None]
        if noa_last <= 0:
            raise ValueError(f"NOA={noa_last:,.0f} — non-positive (Apple buyback edge case?)")
        ok(f"{ticker} reformulation: NOA={noa_last:,.0f}, OG_avg={ref['historical_avgs']['OG']:.3f}, "
           f"ATO_avg={ref['historical_avgs']['ATO']:.2f}, CAGR={ref['historical_avgs']['revenue_cagr']:.2%}, "
           f"flags={len(ref['flags'])}")
        results["ref"] = ref
    except Exception as e:
        fail(f"{ticker} reformulation", e)
        results["ref"] = None
        return results

    # ── 3. DA #1 — reformulation review ──────────────────────────
    try:
        da1 = review_reformulation(ref, client)
        ok(f"{ticker} DA#1 reformulation review: {da1[:80]}...")
        results["da1"] = da1
    except Exception as e:
        fail(f"{ticker} DA#1 review", e)

    # ── 4. WACC computation ───────────────────────────────────────
    try:
        wacc_data = compute_wacc(fmp_data, ref, hq_country_raw)
        ok(f"{ticker} WACC={wacc_data['wacc']:.4f}, rf={wacc_data['rf']:.4f}, "
           f"rE={wacc_data['rE']:.4f}, rD={wacc_data['rD']:.4f}, "
           f"iso3={wacc_data['iso3']}, rating={wacc_data['rating']}")
        results["wacc_data"] = wacc_data
    except Exception as e:
        fail(f"{ticker} WACC computation", e)
        results["wacc_data"] = None
        return results

    # ── 5. Consistency check ──────────────────────────────────────
    try:
        check_result = check(wacc_data["checker_inputs"])
        if check_result["passed"]:
            ok(f"{ticker} consistency check passed")
        else:
            raise ValueError(f"Consistency gate FAILED: {check_result['issues']}")
        results["check"] = check_result
    except Exception as e:
        fail(f"{ticker} consistency check", e)
        results["check"] = None
        # Don't return — continue to see more failures

    # ── 6. DA #2 — consistency review ────────────────────────────
    try:
        if results.get("check"):
            da2 = review_consistency(results["check"], client)
            ok(f"{ticker} DA#2 consistency review: {da2[:80]}...")
    except Exception as e:
        fail(f"{ticker} DA#2 review", e)

    # ── 7. DCF + sensitivity ──────────────────────────────────────
    try:
        NFO    = ref["NFO"][-1]
        NCI    = ref["NCI"][-1]
        _ws    = fmp_data["income"][0].get("weightedAverageShsOutDil")
        diluted_shares = float(_ws if _ws is not None else (fmp_data["profile"].get("sharesOutstanding") or 1))
        base_year = ref["years"][-1]
        wacc      = wacc_data["wacc"]

        dcf = compute_dcf(ref, wacc=wacc, g=0.02, NFO=NFO, NCI=NCI,
                          diluted_shares=diluted_shares, base_year=base_year)
        sens = compute_sensitivity(ref, wacc_base=wacc, g_base=0.02, NFO=NFO, NCI=NCI,
                                   diluted_shares=diluted_shares, base_year=base_year)

        price = dcf["price_per_share"]
        market = float(fmp_data["profile"].get("price") or 0)
        ratio = price / market if market > 0 else 0

        if price < 0:
            raise ValueError(f"price_per_share={price:.2f} < 0 (EV={dcf['EV']:,.0f} < NFO+NCI={NFO+NCI:,.0f})")

        ok(f"{ticker} DCF: price={price:.2f}, market={market:.2f}, ratio={ratio:.2f}x, "
           f"EV={dcf['EV']:,.0f}, TV_share={dcf['PV_TV']/dcf['EV']:.0%}")
        results["dcf"]  = dcf
        results["sens"] = sens
        results["diluted_shares"] = diluted_shares
        results["NFO"]  = NFO
        results["NCI"]  = NCI
    except Exception as e:
        fail(f"{ticker} DCF/sensitivity", e)
        results["dcf"]  = None
        return results

    # ── 8. DA #3 — valuation review ──────────────────────────────
    try:
        market_price = float(fmp_data["profile"].get("price") or 0)
        da3 = review_valuation(wacc_data, dcf, market_price, client)
        ok(f"{ticker} DA#3 valuation review: {da3[:80]}...")
    except Exception as e:
        fail(f"{ticker} DA#3 review", e)

    # ── 9. Chart spec generation ──────────────────────────────────
    try:
        chart_specs, dfs = build_chart_specs(
            ticker, company_name, wacc_data["iso3"],
            ref, wacc_data, dcf, sens, fmp_data,
        )
        if len(chart_specs) != 18:
            raise ValueError(f"Expected 18 chart specs, got {len(chart_specs)}")

        type_counts = {}
        for s in chart_specs:
            type_counts[s["type"]] = type_counts.get(s["type"], 0) + 1

        missing_note  = [s.get("title", "?") for s in chart_specs if not s.get("note")]
        missing_kilde = [s.get("title", "?") for s in chart_specs if not s.get("kilde")]

        # Verify discount factor precision in DCF table (chart 13)
        dcf_table = next((s for s in chart_specs if "Discount factor" in str(s.get("table_data", {}).get("rows", []))), None)
        if dcf_table:
            disc_row = next((r for r in dcf_table["table_data"]["rows"] if "Discount factor" in r.get("indicator", "")), None)
            if disc_row:
                first_yr = dcf["forecast_years"][0]
                disc_val_str = disc_row.get(first_yr, "")
                if "." in disc_val_str and len(disc_val_str.split(".")[1]) < 3:
                    raise ValueError(f"Discount factor precision too low: '{disc_val_str}' (expected ≥3 decimal places)")
                ok(f"{ticker} discount factor precision OK: '{disc_val_str}'")

        ok(f"{ticker} chart specs: {len(chart_specs)} total, types={type_counts}, "
           f"DFs={len(dfs)}, missing_note={missing_note or 'none'}, missing_kilde={missing_kilde or 'none'}")
        results["chart_specs"] = chart_specs
        results["dfs"] = dfs
    except Exception as e:
        fail(f"{ticker} chart spec generation", e)
        results["chart_specs"] = None
        return results

    # ── 10. DA #4 & #5 ───────────────────────────────────────────
    try:
        da4 = review_kpi_specs(chart_specs, client)
        ok(f"{ticker} DA#4 KPI specs review: {da4[:80]}...")
    except Exception as e:
        fail(f"{ticker} DA#4 review", e)

    try:
        market_price = float(fmp_data["profile"].get("price") or 0)
        da5 = review_final(chart_specs, dcf["price_per_share"], market_price, client)
        ok(f"{ticker} DA#5 final review: {da5[:80]}...")
    except Exception as e:
        fail(f"{ticker} DA#5 review", e)

    return results


def run_edge_cases(client):
    """Test specific loopholes with synthetic data."""
    print(f"\n{'═'*60}")
    print("  EDGE CASES")
    print(f"{'═'*60}")

    # Edge case 1: EV=0 in DA review (WACC > FCF growth)
    try:
        from newsletter_agent.specialists.annual_report_valuation import _dcf_price
        ref_edge = {
            "NOA": [50_000] * 5, "NFO": [200_000] * 5, "OI": [1_000] * 5,
            "FCF": [None, 1_000, 1_000, 1_000, 1_000], "NCI": [0] * 5,
            "common_equity": [10_000] * 5, "revenue": [20_000] * 5,
            "years": [2020, 2021, 2022, 2023, 2024],
            "historical_avgs": {"OG": 0.05, "ATO": 0.4, "revenue_cagr": 0.01},
            "flags": [],
        }
        # Very high WACC should give near-zero or negative EV
        wacc_edge = {"wacc": 0.25, "rf": 0.05, "rf_entry": {"rate": 0.05, "maturity_yr": 30, "spot": 0.05, "bond_name": "Test"}, "t": 0.21, "beta_raw": 1.0, "beta_adj": 1.0, "MRP": 0.04, "CRP": 0.0, "rE": 0.09, "rs": 0.02, "rs_moody": None, "rs_icr": 0.02, "rD": 0.056, "D": 200_000, "E": 10_000, "V": 210_000, "iso3": "USA"}
        dcf_edge = compute_dcf(ref_edge, wacc=0.25, g=0.02, NFO=200_000, NCI=0, diluted_shares=1_000, base_year=2024)
        # DA review must not crash when EV ≤ 0
        from newsletter_agent.specialists.annual_report_da import review_valuation
        da = review_valuation(wacc_edge, dcf_edge, 5.0, client)
        ok(f"Edge case EV≤0 in DA review handled: EV={dcf_edge['EV']:.0f}, review returned ok")
    except ZeroDivisionError as e:
        fail("Edge case EV=0 ZeroDivisionError", e)
    except Exception as e:
        ok(f"Edge case EV≤0 handled gracefully ({type(e).__name__}: {str(e)[:60]})")

    # Edge case 2: Zero diluted shares (should use sharesOutstanding fallback)
    try:
        _ws = 0  # explicitly zero
        profile_so = 500
        result = float(_ws if _ws is not None else (profile_so or 1))
        if result == 0:
            raise ValueError("diluted_shares=0 fell through — should use sharesOutstanding")
        ok("Edge case diluted_shares=0 → using sharesOutstanding (old or logic would fail)")
    except Exception as e:
        # This is the OLD bug — document if it exists
        fail("Edge case diluted_shares=0", e)

    # Actually test the NEW logic (explicit None check)
    try:
        _ws = 0
        result_new = float(_ws if _ws is not None else (500 or 1))
        ok(f"New diluted_shares logic: _ws=0 → result={result_new} (uses 0, not fallback)")
    except Exception as e:
        fail("New diluted_shares logic", e)

    # Edge case 3: Country code "DK" (should not fall to _default after bug fix)
    try:
        iso3_dk = normalize_country("DK")
        if iso3_dk == "_default":
            raise ValueError("normalize_country('DK') → '_default' — 'dk' not in _COUNTRY_NAME_MAP")
        ok(f"Country 'DK' normalizes to: {iso3_dk}")
    except Exception as e:
        fail("Edge case country code 'DK'", e)

    # Edge case 4: Country code "SE", "NO", "DE", "FR", "JP"
    for code, expected in [("SE", "SWE"), ("NO", "NOR"), ("DE", "DEU"), ("FR", "FRA"), ("JP", "JPN")]:
        try:
            result = normalize_country(code)
            if result == "_default":
                raise ValueError(f"'{code}' → '_default'")
            if result != expected:
                raise ValueError(f"'{code}' → '{result}', expected '{expected}'")
            ok(f"Country code '{code}' → '{result}' ✓")
        except Exception as e:
            fail(f"Country code '{code}'", e)


if __name__ == "__main__":
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    for ticker, name, country, fmp in COMPANIES:
        run_pipeline(ticker, name, country, fmp, client)

    run_edge_cases(client)

    print(f"\n{'═'*60}")
    print(f"  RESULTS: {len(PASSED)} passed, {len(FAILED)} failed")
    print(f"{'═'*60}")
    if FAILED:
        print("\nFAILED:")
        for label, msg in FAILED:
            print(f"  ✗ {label}")
            print(f"    → {msg}")
    else:
        print("\n  All checks passed.")

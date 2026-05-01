def _safe(val, default=0.0):
    return float(val) if val is not None else default


def reformulate(fmp_data: dict, t: float) -> dict:
    income   = list(reversed(fmp_data["income"]))
    balance  = list(reversed(fmp_data["balance"]))
    cf_list  = list(reversed(fmp_data.get("cashflow", [])))
    cf_by_yr = {int(c["date"][:4]): c for c in cf_list if c.get("date")}
    n = min(len(income), len(balance))

    years, revenue_l, NOA_l, NFO_l, OI_l, FCF_l = [], [], [], [], [], []
    RNOA_l, OG_l, ATO_l, FLEV_l, NBC_l, SPREAD_l, ROCE_l = [], [], [], [], [], [], []
    NCI_l, equity_l, goodwill_l, avg_NOA_l, cash_fcf_l = [], [], [], [], []

    prev_NOA = prev_NFO = prev_equity = None

    for i in range(n):
        inc, bal = income[i], balance[i]
        year    = int(inc["date"][:4])
        revenue = _safe(inc.get("revenue"))
        ebit    = _safe(inc.get("operatingIncome"))
        OI      = ebit * (1 - t)
        _comp = inc.get("comprehensiveIncomePeriodChange")
        comp_ni = _safe(_comp if _comp is not None else inc.get("netIncome"))
        interest= _safe(inc.get("interestExpense"))

        fin_assets = (_safe(bal.get("cashAndCashEquivalents"))
                      + _safe(bal.get("shortTermInvestments"))
                      + _safe(bal.get("longTermInvestments")))
        # Capital lease obligations classified as operating (ROU asset is already in op_assets)
        fin_liabs  = (_safe(bal.get("shortTermDebt"))
                      + _safe(bal.get("longTermDebt")))
        op_assets  = _safe(bal.get("totalAssets")) - fin_assets
        op_liabs   = _safe(bal.get("totalLiabilities")) - fin_liabs

        NOA       = op_assets - op_liabs
        NFO       = fin_liabs - fin_assets
        common_eq = _safe(bal.get("totalStockholdersEquity"))
        nci       = _safe(bal.get("minorityInterest"))
        goodwill  = _safe(bal.get("goodwillAndIntangibleAssets"))

        dNOA = (NOA - prev_NOA) if prev_NOA is not None else None
        FCF  = (OI - dNOA)     if dNOA is not None else None

        avg_NOA = (NOA + prev_NOA) / 2 if prev_NOA is not None else NOA
        avg_NFO = (NFO + prev_NFO) / 2 if prev_NFO is not None else NFO
        avg_eq  = (common_eq + prev_equity) / 2 if prev_equity is not None else common_eq

        RNOA   = OI / avg_NOA    if avg_NOA  != 0 else 0.0
        OG     = OI / revenue    if revenue  != 0 else 0.0
        ATO    = revenue / avg_NOA if avg_NOA != 0 else 0.0
        FLEV   = NFO / common_eq  if common_eq != 0 else 0.0
        NBC    = (interest * (1 - t)) / avg_NFO if avg_NFO != 0 else 0.0
        SPREAD = RNOA - NBC
        ROCE   = comp_ni / avg_eq if avg_eq != 0 else 0.0

        years.append(year); revenue_l.append(revenue); NOA_l.append(NOA)
        NFO_l.append(NFO); OI_l.append(OI); FCF_l.append(FCF)
        RNOA_l.append(RNOA); OG_l.append(OG); ATO_l.append(ATO)
        FLEV_l.append(FLEV); NBC_l.append(NBC); SPREAD_l.append(SPREAD)
        # Cash FCF = OCF - |CapEx| from cash flow statement (capex negative in FMP)
        cf = cf_by_yr.get(year, {})
        _ocf   = _safe(cf.get("operatingCashFlow"))
        _capex = _safe(cf.get("capitalExpenditure"))
        _cfcf  = _safe(cf.get("freeCashFlow"))
        if _cfcf != 0:
            cash_fcf = _cfcf
        elif _ocf != 0:
            cash_fcf = _ocf + _capex
        else:
            cash_fcf = None

        ROCE_l.append(ROCE); NCI_l.append(nci); equity_l.append(common_eq)
        goodwill_l.append(goodwill); avg_NOA_l.append(avg_NOA); cash_fcf_l.append(cash_fcf)

        prev_NOA, prev_NFO, prev_equity = NOA, NFO, common_eq

    flags        = []
    excluded_yrs = set()

    # Exclude years with non-positive ending NOA — RNOA/ATO are undefined when NOA ≤ 0.
    for i, noa in enumerate(NOA_l):
        if noa <= 0:
            flags.append(
                f"{years[i]}: NOA = {noa:,.0f} (negativ/nul) — "
                f"RNOA og ATO er ikke meningsfulde; året er udeladt fra gennemsnit [CALC]"
            )
            excluded_yrs.add(years[i])

    # Also exclude transition years where avg_NOA ≤ 0 even though ending NOA is positive.
    # avg_NOA straddles a negative-NOA year → ATO/RNOA still extreme (e.g. -733x for Apple 2022).
    for i, avg_noa in enumerate(avg_NOA_l):
        if avg_noa <= 0 and years[i] not in excluded_yrs:
            flags.append(
                f"{years[i]}: Gns. NOA = {avg_noa:,.0f} (negativ) — "
                f"ATO/RNOA upålidelige; overgangsår efter negativt NOA-år; udeladt fra gennemsnit [CALC]"
            )
            excluded_yrs.add(years[i])

    # Q1: Flag NOA spikes — large YoY NOA jump with proportional ATO drop signals
    # reclassification or data anomaly, not genuine operating capital growth
    for i in range(1, len(NOA_l)):
        if NOA_l[i - 1] > 0 and ATO_l[i - 1] != 0:
            noa_chg   = (NOA_l[i] - NOA_l[i - 1]) / abs(NOA_l[i - 1])
            ato_ratio = ATO_l[i] / ATO_l[i - 1]
            if noa_chg > 0.75 and ato_ratio < 0.60:
                flags.append(
                    f"{years[i]}: NOA steg {noa_chg:.0%} YoY mens ATO faldt fra "
                    f"{ATO_l[i - 1]:.2f}x til {ATO_l[i]:.2f}x — mulig omklassificering "
                    f"eller dataanomali. Udeladt fra gennemsnit; DCF anvender ATO-normaliseret startpunkt [ASSUMED]"
                )
                excluded_yrs.add(years[i])

    for i in range(1, len(OI_l)):
        if OI_l[i - 1] != 0:
            chg = abs((OI_l[i] - OI_l[i - 1]) / OI_l[i - 1])
            if chg > 0.25:
                flags.append(
                    f"{years[i]}: OI changed {chg:.0%} YoY — flagged as potential one-time item, "
                    f"excluded from historical averages [ASSUMED]"
                )
                excluded_yrs.add(years[i])

    for i in range(1, len(revenue_l)):
        if revenue_l[i - 1] != 0:
            rev_jump = (revenue_l[i] - revenue_l[i - 1]) / revenue_l[i - 1]
            if rev_jump > 0.20 and goodwill_l[i] > goodwill_l[i - 1]:
                flags.append(
                    f"{years[i]}: Revenue +{rev_jump:.0%} with goodwill increase — CAGR may be "
                    f"M&A-distorted. Organic CAGR excludes this year [ASSUMED]"
                )
                excluded_yrs.add(years[i])

    if len(OG_l) >= 5:
        og_diffs = [OG_l[i] - OG_l[i - 1] for i in range(1, len(OG_l))]
        last4    = og_diffs[-4:]
        if all(d > 0 for d in last4) or all(d < 0 for d in last4):
            flags.append(
                "OG has trended consistently for 4+ consecutive years — simple average may "
                "understate trend. DA has reviewed both simple avg [ASSUMED] and trend-extrapolated OG [EST]."
            )

    valid_idx = [i for i, y in enumerate(years) if y not in excluded_yrs and FCF_l[i] is not None]
    if not valid_idx:
        valid_idx = [i for i in range(len(years)) if FCF_l[i] is not None]
    if not valid_idx:
        valid_idx = list(range(len(years)))

    avg_OG  = sum(OG_l[i]  for i in valid_idx) / len(valid_idx)
    avg_ATO = sum(ATO_l[i] for i in valid_idx) / len(valid_idx)

    valid_rev = [(years[i], revenue_l[i]) for i in range(len(years)) if years[i] not in excluded_yrs]
    if len(valid_rev) >= 2:
        y0, r0 = valid_rev[0]
        yn, rn = valid_rev[-1]
        n_yrs  = yn - y0
        rev_cagr = ((rn / r0) ** (1 / n_yrs) - 1) if r0 != 0 and n_yrs > 0 else 0.0
    else:
        rev_cagr = 0.0

    return {
        "years":          years,
        "revenue":        revenue_l,
        "NOA":            NOA_l,
        "NFO":            NFO_l,
        "OI":             OI_l,
        "FCF":            FCF_l,
        "RNOA":           RNOA_l,
        "OG":             OG_l,
        "ATO":            ATO_l,
        "FLEV":           FLEV_l,
        "NBC":            NBC_l,
        "SPREAD":         SPREAD_l,
        "ROCE":           ROCE_l,
        "NCI":            NCI_l,
        "common_equity":  equity_l,
        "historical_avgs": {
            "OG":           avg_OG,
            "ATO":          avg_ATO,
            "revenue_cagr": rev_cagr,
        },
        "cash_fcf":    cash_fcf_l,
        "flags":       flags,
        "assumptions": [f"t={t:.1%} statutory corporate tax rate applied to OI and NBC"],
    }

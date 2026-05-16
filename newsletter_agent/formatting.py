"""Global number formatting for the newsletter agent.

All user-visible numbers use Danish style: period as thousands separator,
comma as decimal separator — e.g. 2.000.000,00.

Use:
    from newsletter_agent.formatting import fmt_da, EXCEL_NUM_FORMAT

    fmt_da(1234567.89)          → "1.234.567,89"
    fmt_da(1234567.89, 0)       → "1.234.568"
    fmt_da(3.14159, 3)          → "3,142"

EXCEL_NUM_FORMAT is the openpyxl number_format string that produces Danish-style
output when the file is opened in a Danish-locale Excel.
"""
from __future__ import annotations
from typing import Optional


EXCEL_NUM_FORMAT = "#,##0.00"


def fmt_da(val: float, decimals: Optional[int] = None) -> str:
    """Format *val* in Danish number style.

    decimals=None  → auto-select precision based on magnitude
    decimals=0     → integer (no decimal part)
    decimals=N     → fixed N decimal places

    Special values: inf → "∞", -inf → "-∞", nan → "—" (em dash, used in tables).
    Negative zero is normalised to 0 before formatting.
    """
    import math
    # Guard: IEEE special values that break f-string formatting
    if isinstance(val, float):
        if math.isnan(val):
            return "—"
        if math.isinf(val):
            return "∞" if val > 0 else "-∞"
        # Normalise -0.0 → 0.0 to avoid "-0,00"
        if val == 0.0:
            val = 0.0

    if decimals is not None:
        s = f"{val:,.{decimals}f}"          # "1,234,567.00"
        if decimals == 0:
            return s.replace(",", ".")       # "1.234.567"
        # split on the last "." — always the decimal separator in Python's format
        int_part, dec_part = s.rsplit(".", 1)
        return int_part.replace(",", ".") + "," + dec_part  # "1.234.567,00"

    # Auto-select precision by magnitude
    abs_val = abs(val)
    if abs_val >= 1000:
        return fmt_da(val, 0)
    if abs_val >= 10:
        return fmt_da(val, 2)
    if abs_val >= 0.1:
        return fmt_da(val, 3)
    return fmt_da(val, 4)

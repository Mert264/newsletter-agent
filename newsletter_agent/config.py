# newsletter_agent/config.py
import os
import threading
from dotenv import load_dotenv, find_dotenv

# Global lock to serialize yfinance downloads across parallel specialist threads.
# yfinance has internal shared session state that is NOT thread-safe when multiple
# yf.download() calls happen simultaneously — data gets cross-contaminated between tickers.
YF_LOCK = threading.Lock()

load_dotenv(find_dotenv(usecwd=False, raise_error_if_not_found=False))

BRAND = {
    "primary":        "#11716c",   # Maj Invest green
    "primary_light":  "#e6f2f1",   # tinted background for highlights
    "secondary":      "#22312d",   # dark text / title
    "accent":         "#d4843e",   # warm amber for highlights / alerts
    "grid_color":     "#ebebeb",
    "background":     "#ffffff",
    "font":           "Helvetica Neue",
    "font_fallback":  "Arial",
    "font_size_title": 13,
    "font_size_axis":  9,
    "font_size_label": 8,
    "font_size_note":  7.5,
    "figure_width_px": 1050,
    "figure_height_px": 720,
    "figure_dpi":      150,
}

API_KEYS = {
    "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
    "fred":      os.getenv("FRED_API_KEY", ""),
    "eia":       os.getenv("EIA_API_KEY", ""),
    "fmp":       os.getenv("FMP_API_KEY", ""),
}

# LLM models — orchestrator and reviewer both use Sonnet for quality
ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
REVIEWER_MODEL     = "claude-sonnet-4-6-20250514"
LLM_MODEL = ORCHESTRATOR_MODEL  # backwards-compat alias

# Default date range for data fetching
DEFAULT_PERIOD_DAYS = 730   # 2 years default — richer x-axis history

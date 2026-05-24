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
    "secondary":      "#22312d",   # dark text / title
    "grid_color":     "#e8e8e8",
    "background":     "#ffffff",
    "font":           "Arial",
    "font_size_title": 12,         # slightly larger for newsletter readability
    "font_size_axis":  9,
    "font_size_label": 8,          # inline line labels (end-of-line annotations)
    "font_size_note":  8,
    "figure_width_px": 1050,       # wider for more x-axis detail
    "figure_height_px": 720,       # taller so chart body fills more of the figure
    "figure_dpi":      150,
    # Convert px to inches at given DPI: width_in = px / dpi, height_in = height_px / dpi
}

API_KEYS = {
    "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
    "fred":      os.getenv("FRED_API_KEY", ""),
    "eia":       os.getenv("EIA_API_KEY", ""),
}

# LLM models — orchestrator uses Sonnet for reliable JSON, reviewer uses Haiku (cheaper)
ORCHESTRATOR_MODEL = "claude-sonnet-4-6"
REVIEWER_MODEL     = "claude-haiku-4-5-20251001"
LLM_MODEL = ORCHESTRATOR_MODEL  # backwards-compat alias

# Default date range for data fetching
DEFAULT_PERIOD_DAYS = 730   # 2 years default — richer x-axis history

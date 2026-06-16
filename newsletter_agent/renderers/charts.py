# newsletter_agent/renderers/charts.py
import matplotlib
matplotlib.use("Agg")  # non-interactive backend for PNG export
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from newsletter_agent.config import BRAND
from newsletter_agent.formatting import fmt_da


# Distinct colours for event markers — kept visually separate from LINE_COLORS
EVENT_COLORS = [
    "#dc2626",   # red
    "#7c3aed",   # purple
    "#f59e0b",   # amber
    "#0ea5e9",   # sky blue
    "#16a34a",   # green
]

LINE_COLORS = [
    "#11716c",   # Maj Invest teal
    "#2563eb",   # blue
    "#d4843e",   # warm amber
    "#7c3aed",   # purple
    "#e53e3e",   # red
    "#0ea5e9",   # sky blue
    "#16a34a",   # green
    "#f97316",   # orange
    "#ec4899",   # pink
    "#64748b",   # slate grey
]

FIGSIZE = (BRAND["figure_width_px"]  / BRAND["figure_dpi"],
           BRAND["figure_height_px"] / BRAND["figure_dpi"])


def _color_for(i: int) -> str:
    return LINE_COLORS[i % len(LINE_COLORS)]


def _draw_trendline(ax, x_dates, y_values, color: str, series_name: str,
                    trendline_type: str, freq: str = "M") -> None:
    """
    Overlay a trendline on a line chart series.

    trendline_type:
      "linear"  — numpy polyfit degree 1, extended 10% beyond data as dashed projection
      "ma"      — rolling mean (window=12 for monthly, 4 for quarterly, 3 otherwise)
      "poly"    — numpy polyfit degree 2, no projection

    Styling: same color as parent series, dashed, linewidth=1.0.
    The projection segment beyond data is drawn at alpha=0.4.
    Legend labels: "{series_name} (trend)" / "{series_name} (MA-N)" / "{series_name} (poly)".
    """
    import matplotlib.dates as _mdates

    s = pd.Series(y_values, index=x_dates).dropna()
    if len(s) < 4:
        return

    tl = trendline_type.lower().strip()

    if tl == "linear":
        # Convert dates to numeric for polyfit
        x_num = _mdates.date2num(s.index.to_pydatetime())
        coeffs = np.polyfit(x_num, s.values, 1)
        poly   = np.poly1d(coeffs)

        # Data portion
        ax.plot(s.index, poly(x_num),
                color=color, linewidth=1.0, linestyle="--",
                label=f"{series_name} (trend)", zorder=4)

        # No forward projection — chart must never extend beyond current date

    elif tl == "ma":
        # Window: 12 for monthly, 4 for quarterly, 3 otherwise
        if freq in ("M", "ME", "MS"):
            window = 12
        elif freq in ("Q", "QE", "QS"):
            window = 4
        else:
            window = 3
        ma = s.rolling(window=window, min_periods=max(2, window // 2)).mean().dropna()
        if ma.empty:
            return
        ax.plot(ma.index, ma.values,
                color=color, linewidth=1.0, linestyle="--",
                label=f"{series_name} (MA-{window})", zorder=4)

    elif tl == "poly":
        x_num = _mdates.date2num(s.index.to_pydatetime())
        coeffs = np.polyfit(x_num, s.values, 2)
        poly   = np.poly1d(coeffs)
        ax.plot(s.index, poly(x_num),
                color=color, linewidth=1.0, linestyle="--",
                label=f"{series_name} (poly)", zorder=4)


def _draw_event_markers(ax, spec: dict, df_index) -> list:
    """
    Draw vertical dashed event markers. Each event gets a distinct color.
    No inline labels — those are handled by the strip legend below the chart.
    Returns list of (color, label, date_str) for every event that was drawn.
    """
    events = spec.get("events", [])
    if not events:
        return []

    x_min = df_index.min()
    x_max = df_index.max()
    drawn = []

    for i, ev in enumerate(events):
        try:
            ev_date = pd.Timestamp(ev["date"])
        except Exception:
            continue
        if ev_date < x_min or ev_date > x_max:
            continue

        color    = EVENT_COLORS[i % len(EVENT_COLORS)]
        label    = ev.get("label", "")
        date_str = ev_date.strftime("%-d %b %Y")   # e.g. "2 Apr 2025"

        ax.axvline(ev_date, color=color, linewidth=1.2,
                   linestyle="--", alpha=0.80, zorder=5)
        drawn.append((color, label, date_str))

    return drawn


def _draw_event_legend_strip(fig, events_drawn: list, y_bottom: float) -> float:
    """
    Render a compact events strip between the chart body and the Note/Kilde footer.
    Each entry shows a colored dashed indicator followed by 'Label (Date)'.
    Returns the fractional height consumed so the caller can widen the bottom margin.
    """
    from matplotlib.lines import Line2D

    if not events_drawn:
        return 0.0

    handles = [
        Line2D([0], [0], color=c, linewidth=2.0, linestyle="--",
               label=f"{lbl}  ({dt})")
        for c, lbl, dt in events_drawn
    ]

    # Place legend anchored to figure coordinates, horizontally compact
    leg = fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.01, y_bottom + 0.004),
        bbox_transform=fig.transFigure,
        ncol=len(events_drawn),          # all events on one row
        fontsize=7,
        frameon=True,
        framealpha=0.95,
        edgecolor="#d1d5db",
        facecolor="#f9fafb",
        title="Events",
        title_fontsize=7,
        handlelength=2.2,
        handletextpad=0.6,
        columnspacing=1.8,
        borderpad=0.5,
    )
    leg.get_title().set_color(BRAND["secondary"])
    leg.get_title().set_fontweight("600")

    # Approximate height consumed: title row + one data row at 7pt on a 720px figure
    return 0.07


def _apply_brand(ax, fig):
    """Apply brand styling to axes."""
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [BRAND["font"], BRAND.get("font_fallback", "Arial")]
    ax.set_facecolor(BRAND["background"])
    fig.patch.set_facecolor(BRAND["background"])
    ax.grid(True, color=BRAND["grid_color"], linewidth=0.35, linestyle="-", alpha=0.7)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color("#cccccc")
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(labelsize=BRAND["font_size_axis"], colors="#555555",
                   length=0)
    ax.title.set_color(BRAND["secondary"])



def _add_footer(fig, spec: dict) -> float:
    """
    Add Note + Kilde lines at the bottom of the figure, Maj Invest newsletter style.
    Returns the bottom margin fraction needed so callers can pass it to tight_layout.
    """
    import textwrap, re
    note  = spec.get("note", "").strip()
    kilde = spec.get("kilde", "").strip()

    # Strip any embedded "Kilde: ..." tail from note to avoid duplication in footer
    note = re.sub(r"\s*Kilde:.*$", "", note, flags=re.IGNORECASE | re.DOTALL).strip()

    parts = []
    if note:
        wrapped = textwrap.fill(f"Note: {note}", width=115)
        parts.append(wrapped)
    if kilde:
        parts.append(f"Kilde: {kilde}")
    if not parts:
        return 0.0

    footer_text = "\n".join(parts)
    n_lines = footer_text.count("\n") + 1

    # Per-line fraction — kept tight so chart body fills more of the figure
    bottom_frac = 0.038 * n_lines + 0.02

    fig.text(
        0.01, 0.005,
        footer_text.replace("$", r"\$"),
        fontsize=BRAND["font_size_note"],
        color="#999999",
        va="bottom",
        ha="left",
        fontstyle="italic",
        transform=fig.transFigure,
        linespacing=1.4,
    )
    return bottom_frac


def _place_end_labels(ax, df, colors):
    """
    Place series labels at the end of each line, staggered vertically to avoid overlap.
    Labels are clamped to the visible axis range so they never escape above the title.
    """
    ylo, yhi = ax.get_ylim()

    label_positions = []  # (y_data, col_name, color)
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        raw_y = s.iloc[-1]
        # Clamp to visible axis so clipped series don't float labels above the plot
        clamped_y = max(ylo, min(yhi * 0.97, raw_y))
        label_positions.append((clamped_y, col, colors[i]))

    if not label_positions:
        return

    label_positions.sort(key=lambda x: x[0])

    min_gap = (yhi - ylo) * 0.09  # minimum 9% of axis range between labels

    adjusted = [list(p) for p in label_positions]
    for k in range(1, len(adjusted)):
        if adjusted[k][0] - adjusted[k-1][0] < min_gap:
            adjusted[k][0] = adjusted[k-1][0] + min_gap

    if len(adjusted) > 1:
        mid_actual = (label_positions[0][0] + label_positions[-1][0]) / 2
        mid_adjusted = (adjusted[0][0] + adjusted[-1][0]) / 2
        shift = mid_actual - mid_adjusted
        for item in adjusted:
            item[0] += shift

    # Final clamp after staggering — guarantee nothing escapes visible range
    margin = (yhi - ylo) * 0.03
    for item in adjusted:
        item[0] = max(ylo + margin, min(yhi - margin, item[0]))

    for y_adj, col, color in adjusted:
        x_end = df[col].dropna().index[-1]
        ax.annotate(
            col,
            xy=(x_end, y_adj),
            xytext=(6, 0),
            textcoords="offset points",
            fontsize=BRAND["font_size_label"],
            color=color,
            va="center",
            annotation_clip=False,
        )


def render_type_a(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type A — Time Series line chart.
    df: DataFrame with DatetimeIndex, one column per series.
    spec: {"title", "x_label", "y_label"}
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    colors = [_color_for(i) for i in range(len(df.columns))]
    series_specs = spec.get("series", [])
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        ax.plot(s.index, s.values, color=colors[i], linewidth=1.6)

    # Trendline overlays — drawn after all data lines so they sit on top
    freq = spec.get("freq", "M")
    global_tl = spec.get("trendline", "none")
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        tl_type = None
        if i < len(series_specs):
            tl_type = series_specs[i].get("trendline")
        if not tl_type:
            tl_type = global_tl
        if tl_type == "none":
            continue
        if tl_type == "auto":
            if len(s) >= 24:
                tl_type = "both"
            elif len(s) >= 12:
                tl_type = "linear"
            else:
                continue
        if tl_type == "both":
            _draw_trendline(ax, s.index, s.values, colors[i], col, "linear", freq=freq)
            _draw_trendline(ax, s.index, s.values, colors[i], col, "ma", freq=freq)
        else:
            _draw_trendline(ax, s.index, s.values, colors[i], col, tl_type, freq=freq)

    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"],
                 pad=8)
    ax.set_xlabel(spec.get("x_label", ""), fontsize=BRAND["font_size_axis"],
                  color=BRAND["secondary"])
    ax.set_ylabel(spec.get("y_label", ""), fontsize=BRAND["font_size_axis"],
                  color=BRAND["secondary"])

    # Annual data (e.g. World Bank) — always use year-only labels regardless of range
    if spec.get("freq") == "A":
        n_years = len(df.index)
        step = 2 if n_years > 10 else 1
        ax.xaxis.set_major_locator(mdates.YearLocator(step))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha="center",
                 fontsize=BRAND["font_size_axis"])
    elif len(df.index) >= 2:
        date_range_days = (df.index[-1] - df.index[0]).days
        if date_range_days > 3650:          # > 10 years → tick every 2 years, label year only
            ax.xaxis.set_major_locator(mdates.YearLocator(2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        elif date_range_days > 1825:        # 5–10 years → tick every year
            ax.xaxis.set_major_locator(mdates.YearLocator(1))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        elif date_range_days > 730:         # 2–5 years → tick every 6 months
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        elif date_range_days > 365:         # 1–2 years → tick every 3 months
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        elif date_range_days > 90:          # 3–12 months → tick every month
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        else:                               # < 3 months → tick every 2 weeks
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right",
                 fontsize=BRAND["font_size_axis"])

    # More y-axis ticks for larger figure
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=10, steps=[1,2,2.5,5,10]))

    _apply_brand(ax, fig)

    # Clip y-axis ONLY for absolute-price series (oil, gas, commodity prices) where a brief
    # spike can compress the rest of the chart. Never clip indexed or rate series — their
    # high values are meaningful and should be shown in full.
    y_lbl_lower = spec.get("y_label", "").lower()
    _is_absolute_price = any(u in y_lbl_lower for u in
                             ["barrel", "mwh", "mmb", "troy", "/lb", "cent/", "bushe"])
    all_vals = df.values.flatten()
    all_vals = all_vals[~np.isnan(all_vals)]
    if _is_absolute_price and len(all_vals) > 10:
        p95 = np.percentile(all_vals, 95)
        raw_ymax = ax.get_ylim()[1]
        if raw_ymax > p95 * 1.3:
            clipped_top = p95 * 1.2
            ax.set_ylim(top=clipped_top)

    # For indexed charts (base=100), enforce a minimum visible range of 60 units
    # so movements like -15% or +20% don't look flat on a compressed axis.
    y_label_lower = spec.get("y_label", "").lower()
    if "base=100" in y_label_lower or "indexed" in y_label_lower:
        ylo, yhi = ax.get_ylim()
        if yhi - ylo < 80:
            mid = (ylo + yhi) / 2
            ax.set_ylim(mid - 45, mid + 45)

    # Add y-axis padding so end-labels have room and the chart doesn't feel cramped
    ylo, yhi = ax.get_ylim()
    y_range = yhi - ylo
    ax.set_ylim(ylo - y_range * 0.04, yhi + y_range * 0.20)

    # Reference lines (e.g. 2% inflation target, zero line)
    for rl in spec.get("reference_lines", []):
        rl_y   = rl.get("y", 0)
        rl_col = rl.get("color", "#9ca3af")
        rl_lbl = rl.get("label", "")
        ax.axhline(y=rl_y, color=rl_col, linestyle="--", linewidth=0.9, alpha=0.85, zorder=1)
        if rl_lbl:
            from matplotlib.transforms import blended_transform_factory
            trans = blended_transform_factory(ax.transAxes, ax.transData)
            ax.text(1.01, rl_y, f" {rl_lbl}", transform=trans,
                    va="bottom", ha="left", fontsize=6.5, color=rl_col, alpha=0.9)

    # Event markers — dashed lines only, no inline labels
    events_drawn = _draw_event_markers(ax, spec, df.index)

    # Append exact date range to the note before rendering footer
    spec_with_dates = dict(spec)
    if len(df.index) >= 2:
        start_str = df.index[0].strftime("%-d %b %Y")
        end_str   = df.index[-1].strftime("%-d %b %Y")
        date_suffix = f" Data: {start_str} – {end_str}."
        existing_note = spec_with_dates.get("note", "").rstrip(". ")
        spec_with_dates["note"] = (existing_note + date_suffix) if existing_note else date_suffix.strip()

    # Footer (Note + Kilde) — must come before tight_layout so we know bottom margin
    bottom = _add_footer(fig, spec_with_dates)

    # Events strip legend — sits between chart area and the Note footer
    strip_h = _draw_event_legend_strip(fig, events_drawn, bottom)
    bottom += strip_h   # widen bottom margin so tight_layout doesn't overlap the strip

    # tight_layout: reserve bottom for footer+strip, right 20% for end-labels
    plt.tight_layout(rect=[0.0, bottom, 0.80, 1.0])
    _place_end_labels(ax, df, colors)

    xlo, xhi = ax.get_xlim()
    today_num = mdates.date2num(pd.Timestamp.today())
    if xhi > today_num:
        ax.set_xlim(right=today_num)

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_type_b(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type B — Bar chart. Three modes:
    - DatetimeIndex + single column: time-series bars (one bar per period).
    - DatetimeIndex + multiple columns: snapshot bars (each column = latest-row value).
    - String index: category comparison bars.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    is_timeseries = isinstance(df.index, pd.DatetimeIndex) and len(df.columns) == 1

    # User-controlled color fields from chart spec — validate hex before use
    def _safe_color(raw, fallback: str) -> str:
        """Return raw if it looks like a valid hex color, else fallback."""
        import re as _re
        if raw and _re.match(r"^#[0-9a-fA-F]{3,8}$", str(raw).strip()):
            return str(raw).strip()
        return fallback

    _bar_color       = _safe_color(spec.get("bar_color"), BRAND["primary"])
    _highlight_n     = int(spec.get("highlight_last_n", 0))           # 0 = no highlight
    _highlight_color = _safe_color(spec.get("highlight_color"), "#d4843e")

    if is_timeseries:
        col = df.columns[0]
        series = df[col].dropna()

        # Detect typical gap to decide whether to downsample
        if len(series) > 1:
            typical_gap = (series.index[-1] - series.index[0]).days / len(series)
        else:
            typical_gap = 30

        if typical_gap <= 10 and len(series) > 60:
            try:
                series = series.resample("ME").mean().dropna()
            except ValueError:
                series = series.resample("M").mean().dropna()
        elif 20 <= typical_gap <= 45 and len(series) > 120:
            try:
                series = series.resample("QE").mean().dropna()
            except ValueError:
                series = series.resample("Q").mean().dropna()

        values = series.values
        n_bars = len(values)
        x_pos  = np.arange(n_bars)

        # All bars use bar_color; optionally highlight the last N bars
        colors = [_bar_color] * n_bars
        if _highlight_n > 0:
            for j in range(max(0, n_bars - _highlight_n), n_bars):
                colors[j] = _highlight_color

        bar_width = max(0.55, min(0.88, 50.0 / max(n_bars, 1)))
        ax.bar(x_pos, values, color=colors, width=bar_width, edgecolor="white", linewidth=0.3)

        # X-axis: year labels centred under each year's group of bars (like Image #8)
        years = [d.year for d in series.index]
        year_groups: dict = {}
        for i, y in enumerate(years):
            year_groups.setdefault(y, []).append(i)

        if len(year_groups) > 1:
            year_ticks = [np.mean(idxs) for idxs in year_groups.values()]
            year_labels = [str(y) for y in year_groups.keys()]
            ax.set_xticks(year_ticks)
            ax.set_xticklabels(year_labels, rotation=0, ha="center",
                               fontsize=BRAND["font_size_axis"], color=BRAND["secondary"])
        else:
            # Single year → show monthly labels
            tick_step = max(1, n_bars // 8)
            ax.set_xticks(x_pos[::tick_step])
            ax.set_xticklabels([series.index[i].strftime("%b '%y")
                                 for i in range(0, n_bars, tick_step)],
                               rotation=45, ha="right",
                               fontsize=BRAND["font_size_axis"])

    elif isinstance(df.index, pd.DatetimeIndex) or len(df.columns) > 1:
        # Multi-column snapshot: each column → one bar from latest row
        latest = df.iloc[-1]
        labels = [c.split(" — ")[-1] for c in latest.index]
        values = list(latest.values)
        colors = [_bar_color if v >= 0 else "#dc2626" for v in values]
        bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor="white")
        y_range = max(values) - min(values) if len(values) > 1 else abs(values[0]) if values else 1
        offset = y_range * 0.02 or 0.5
        has_mixed_signs = any(v >= 0 for v in values) and any(v < 0 for v in values)
        for bar, val in zip(bars, values):
            label = ("+" if (val >= 0 and has_mixed_signs) else "") + fmt_da(val)
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (offset if val >= 0 else -offset),
                    label, ha="center", va="bottom" if val >= 0 else "top",
                    fontsize=9, fontweight="bold", color=BRAND["secondary"])

    else:
        # Category bars: string index, single column
        col = df.columns[0]
        values = list(df[col].values)
        labels = list(df.index)
        colors = [_bar_color if v >= 0 else "#dc2626" for v in values]
        bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor="white")
        y_range = max(values) - min(values) if len(values) > 1 else abs(values[0]) if values else 1
        offset = y_range * 0.02 or 0.5
        has_mixed_signs = any(v >= 0 for v in values) and any(v < 0 for v in values)
        for bar, val in zip(bars, values):
            label = ("+" if (val >= 0 and has_mixed_signs) else "") + fmt_da(val)
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (offset if val >= 0 else -offset),
                    label, ha="center", va="bottom" if val >= 0 else "top",
                    fontsize=9, fontweight="bold", color=BRAND["secondary"])

    ax.axhline(0, color="#888888", linewidth=0.7)

    # Trendline overlay for time-series bar charts (linear only)
    if is_timeseries:
        bar_series_specs = spec.get("series", [])
        tl_type = bar_series_specs[0].get("trendline") if bar_series_specs else None
        if not tl_type:
            tl_type = spec.get("trendline")
        if tl_type:
            import matplotlib.dates as _mdates_b
            col = df.columns[0]
            s_full = df[col].dropna()
            bar_color_tl = _bar_color
            # Linear only for bar charts
            x_num = _mdates_b.date2num(s_full.index.to_pydatetime())
            coeffs = np.polyfit(x_num, s_full.values, 1)
            poly_fn = np.poly1d(coeffs)
            ax.plot(s_full.index, poly_fn(x_num),
                    color=bar_color_tl, linewidth=1.2, linestyle="--",
                    alpha=0.75, label=f"{col} (trend)", zorder=5)

    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    raw_xlabel = spec.get("x_label", "")
    if raw_xlabel.strip().lower() in ("dato", "date", "år", "year", "month", "måned"):
        raw_xlabel = ""
    ax.set_xlabel(raw_xlabel, fontsize=BRAND["font_size_axis"], color=BRAND["secondary"])
    ax.set_ylabel(spec.get("y_label", ""), fontsize=BRAND["font_size_axis"],
                  color=BRAND["secondary"])
    if is_timeseries:
        ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=10, steps=[1, 2, 2.5, 5, 10]))
    _apply_brand(ax, fig)
    # After _apply_brand: for time-series bars, suppress vertical gridlines
    if is_timeseries:
        ax.xaxis.grid(False)
        ax.yaxis.grid(True, color=BRAND["grid_color"], linewidth=0.5, linestyle="-")
    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_type_c(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type C — Seasonal / historical range chart.
    df: index=day-of-year (1-365). Columns: current year, "5Y min", "5Y max".
    Falls back to a regular time-series plot if seasonal columns aren't present.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    current_col = [c for c in df.columns if "aktuelt" in c or "2026" in c or "current" in c.lower()]
    min_col = [c for c in df.columns if "min" in c.lower()]
    max_col = [c for c in df.columns if "max" in c.lower()]

    # Fallback: if seasonal structure isn't present, render as plain time-series
    if not current_col and not min_col and not max_col:
        plt.close(fig)
        return render_type_a(df, spec, output_path)

    if min_col and max_col:
        ax.fill_between(df.index, df[min_col[0]], df[max_col[0]],
                        alpha=0.2, color=BRAND["primary"], label="Historisk interval")

    if current_col:
        ax.plot(df.index, df[current_col[0]],
                color=BRAND["primary"], linewidth=2, label=current_col[0])

    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"])
    ax.set_xlabel(spec["x_label"], fontsize=BRAND["font_size_axis"])
    ax.set_ylabel(spec["y_label"], fontsize=BRAND["font_size_axis"])
    ax.legend(fontsize=7)
    _apply_brand(ax, fig)

    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_type_f(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type F — 100% Stacked bar chart (energy mix / composition over time).
    df: index = year/category labels (strings), columns = categories (fuel types, sectors, etc.)
    Values can be absolute — chart normalises each row to 100%.
    """
    n_cats = len(df.columns)
    legend_rows = max(1, int(np.ceil(n_cats / 5)))  # 5 per row → fewer rows
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    # Normalise each row to 100%
    row_totals = df.sum(axis=1).replace(0, np.nan)
    pct = df.div(row_totals, axis=0) * 100

    n_years = len(pct)
    # Only label segments when there are few enough years that bars are wide enough to read
    show_segment_labels = n_years <= 12

    # Use width=0.8 for denser bar packing — reduces gaps between year bars
    bar_width = 0.8

    bottoms = np.zeros(n_years)
    x_positions = np.arange(n_years)
    # Last-year pct values for legend annotations
    last_vals: dict[str, float] = {}
    for i, col in enumerate(pct.columns):
        vals = pct[col].fillna(0).values
        last_vals[col] = vals[-1]
        color = _color_for(i)
        bars = ax.bar(x_positions, vals, bottom=bottoms,
                      color=color, width=bar_width,
                      label=col, edgecolor="white", linewidth=0.4)
        if show_segment_labels:
            for bar, val, bot in zip(bars, vals, bottoms):
                # Only label segments large enough to fit text inside the bar
                if val >= 6:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bot + val / 2,
                            f"{val:.0f}%",
                            ha="center", va="center",
                            fontsize=7, color="white", fontweight="600")
        bottoms += vals

    ax.set_ylim(0, 105)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    ax.set_ylabel(spec.get("y_label", "Pct. af total"), fontsize=BRAND["font_size_axis"])

    # Thin x-axis ticks; horizontal labels (year labels are short, never need rotation)
    if n_years > 20:
        step = 5
    elif n_years > 10:
        step = 2
    else:
        step = 1
    tick_labels = [str(lbl) if idx % step == 0 else "" for idx, lbl in enumerate(pct.index)]
    ax.set_xticks(x_positions)
    ax.set_xticklabels(tick_labels, rotation=0, ha="center",
                       fontsize=BRAND["font_size_axis"])

    _apply_brand(ax, fig)

    # Horizontal-only gridlines at 20% intervals
    ax.xaxis.grid(False)
    ax.yaxis.grid(True, color=BRAND["grid_color"], linewidth=0.4, linestyle="-")

    # Legend: fuel/category names only — bar segments already show per-year percentages
    legend_labels = list(pct.columns)
    handles, _ = ax.get_legend_handles_labels()
    ax.legend(handles, legend_labels,
              fontsize=BRAND["font_size_label"], frameon=False,
              loc="upper center", bbox_to_anchor=(0.5, -0.12),
              ncol=min(n_cats, 5),
              borderpad=0, handlelength=1.2, handletextpad=0.4, columnspacing=1.0)

    bottom_frac = _add_footer(fig, spec)
    # Reserve: 0.12 gap below axes + legend rows height + footer
    legend_reserve = 0.12 + 0.06 * legend_rows + bottom_frac
    plt.subplots_adjust(bottom=legend_reserve)
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_type_g(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type G — Horizontal bar chart for entity/sector/country comparison.
    df: index = entity names, single value column (% or absolute).
    Bars sorted descending by value.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    col = df.columns[0]
    sorted_df = df[col].sort_values(ascending=True)  # ascending so largest is at top
    colors = [BRAND["primary"] if v >= 0 else "#dc2626" for v in sorted_df]

    bars = ax.barh(sorted_df.index, sorted_df.values,
                   color=colors, edgecolor="white", height=0.6)

    # Value labels at bar ends
    for bar, val in zip(bars, sorted_df.values):
        x_pos = val + (sorted_df.abs().max() * 0.01)
        ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", va="center", ha="left",
                fontsize=7, color=BRAND["secondary"])

    ax.axvline(0, color=BRAND["secondary"], linewidth=0.6)
    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    ax.set_xlabel(spec.get("y_label", "%"), fontsize=BRAND["font_size_axis"])
    ax.tick_params(axis="y", labelsize=BRAND["font_size_axis"])
    _apply_brand(ax, fig)
    # Extend x-axis right for value labels
    xmax = sorted_df.max()
    ax.set_xlim(right=xmax * 1.18)
    bottom_frac = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom_frac, 1.0, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def _color_for_label(label: str, palette: list = None) -> str:
    """Consistent color for a category label — hash-based fallback only."""
    p = palette or LINE_COLORS
    return p[hash(label) % len(p)]


def _build_category_colors(categories: list) -> dict:
    """Assign sequential, guaranteed-distinct colors to a list of categories.
    Sequential assignment avoids hash collisions that can make two categories share a color."""
    return {cat: LINE_COLORS[i % len(LINE_COLORS)] for i, cat in enumerate(categories)}


def _draw_single_pie(ax, series: "pd.Series", category_colors: dict = None):
    """Draw one pie onto ax. Returns (wedges, series) for legend construction.
    category_colors: optional {label: color} map for cross-year consistency."""
    colors = [
        (category_colors[lbl] if category_colors and lbl in category_colors else _color_for_label(lbl))
        for lbl in series.index
    ]
    # Always compute all percentages; show inside pie only for slices >= 5%
    total = series.sum()
    wedges, _, autotexts = ax.pie(
        series.values,
        labels=None,
        autopct=lambda p: f"{p:.0f}%" if p >= 5 else "",
        colors=colors,
        startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 1.2},
        pctdistance=0.72,
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color("white")
        at.set_fontweight("600")
    return wedges, series


def _save_single_pie_figure(series: "pd.Series", title_str: str,
                             spec: dict, output_path: str,
                             category_colors: dict = None) -> str:
    """Render and save one standalone pie figure. Returns output_path."""
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])
    wedges, series = _draw_single_pie(ax, series, category_colors)
    ax.set_title(title_str, fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    fig.patch.set_facecolor(BRAND["background"])
    # Enrich legend with percentage for every category — ensures small slices
    # (< 5%, no inside label) always have their value visible in the legend.
    total = series.sum()
    legend_labels = [
        f"{lbl}  {series[lbl] / total * 100:.1f}%"
        for lbl in series.index
    ]
    ax.legend(wedges, legend_labels, fontsize=BRAND["font_size_label"],
              loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
    bottom_frac = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom_frac, 0.78, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def _save_combined_pie_figure(wide: "pd.DataFrame", years_to_show: list,
                               spec: dict, output_path: str) -> str:
    """Render a small-multiples comparison figure: one pie per year. Returns output_path.
    Uses ALL years in years_to_show (no cap). Grid: max 4 columns, auto rows."""
    n = len(years_to_show)
    if n <= 4:
        nrows, ncols = 1, n
    else:
        ncols = 4
        nrows = (n + ncols - 1) // ncols   # ceil(n / 4)

    fig_w = max(FIGSIZE[0], FIGSIZE[0] * ncols / 2.2)
    fig_h = FIGSIZE[1] * nrows if nrows == 1 else FIGSIZE[1] * 0.9 * nrows

    fig, axes = plt.subplots(nrows, ncols, figsize=(fig_w, fig_h),
                             dpi=BRAND["figure_dpi"])
    axes_flat = np.array(axes).flatten()

    # Build a shared color map so each category gets the same color in every year panel
    all_categories = []
    for y in years_to_show:
        if y in wide.index:
            for cat in wide.loc[y].dropna().index:
                if cat not in all_categories:
                    all_categories.append(cat)
    category_colors = _build_category_colors(all_categories)

    ref_wedges = ref_series = None
    for i, (ax, year) in enumerate(zip(axes_flat, years_to_show)):
        row = wide.loc[year].dropna() if year in wide.index else pd.Series(dtype=float)
        row = row[row > 0]
        if row.empty:
            ax.set_visible(False)
            continue
        wedges, series = _draw_single_pie(ax, row, category_colors)
        ax.set_title(year, fontsize=BRAND["font_size_label"],
                     fontweight="bold", color=BRAND["secondary"])
        ref_wedges, ref_series = wedges, series

    # Hide any unused axes in the grid
    for ax in axes_flat[len(years_to_show):]:
        ax.set_visible(False)

    fig.patch.set_facecolor(BRAND["background"])
    fig.suptitle(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", color=BRAND["secondary"],
                 x=0.01, ha="left", y=1.01)

    if ref_wedges is not None:
        colors = [category_colors.get(lbl, _color_for_label(lbl)) for lbl in all_categories]
        handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
        fig.legend(handles, all_categories,
                   fontsize=BRAND["font_size_label"],
                   loc="center right", bbox_to_anchor=(1.0, 0.5), frameon=False)

    bottom_frac = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom_frac, 0.82, 0.96])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_type_p(df: pd.DataFrame, spec: dict, output_path: str) -> "str | list[str]":
    """
    Type P — Pie chart composition.
    - Wide df with multiple year rows: returns list[str] — individual year pie per entry
      (up to 10 years) plus a final combined comparison figure as the last element.
    - Wide df single row or single-column df: returns str (single pie figure path).
    Values are normalised to 100% internally by matplotlib.
    """
    # ── Normalise to wide format ──────────────────────────────────────────────
    if df.shape[1] > 1:
        wide = df
    else:
        wide = None

    # ── Multi-year: individual pies + combined comparison ─────────────────────
    if wide is not None and wide.shape[0] > 1:
        all_years = [str(y) for y in wide.index.tolist()]

        period_days = spec.get("period_days", None)
        # Short window (≤730 days / ~2 years): show only the most recent year as one pie.
        # Longer windows: show individual year pies + combined comparison grid.
        if not period_days or period_days <= 730:
            year_cap = 1
        else:
            year_cap = max(2, round(period_days / 365))
        individual_years = all_years[-year_cap:]

        # Single most-recent-year shortcut — avoids explosion of figures for snapshot briefs.
        if len(individual_years) <= 1:
            year = individual_years[0]
            row = wide.loc[year].dropna() if year in wide.index else pd.Series(dtype=float)
            row = pd.to_numeric(row, errors="coerce").dropna()
            row = row[row > 0]
            if row.empty:
                return output_path
            return _save_single_pie_figure(row, f"{spec['title']} ({year})", spec, output_path)

        base = output_path[:-4]       # strip .png

        # Build shared color map using sequential assignment — guarantees every category
        # gets a visually distinct color with no hash collisions.
        all_cats = []
        for y in individual_years:
            if y in wide.index:
                for cat in wide.loc[y].dropna().index:
                    if cat not in all_cats:
                        all_cats.append(cat)
        shared_colors = _build_category_colors(all_cats)

        paths = []
        for i, year in enumerate(individual_years):
            row = wide.loc[year].dropna() if year in wide.index else pd.Series(dtype=float)
            row = pd.to_numeric(row, errors="coerce").dropna()
            row = row[row > 0]
            year_path = f"{base}_y{i:02d}.png"
            if row.empty:
                continue
            # Keep kilde on individual pies; strip note (note appears on combined only)
            year_spec = {**spec, "note": ""}
            _save_single_pie_figure(row, f"{spec['title']} ({year})", year_spec, year_path,
                                    category_colors=shared_colors)
            paths.append(year_path)

        if not paths:
            # All years empty — fall through to single-pie empty guard below
            return output_path

        # Combined comparison figure uses the same year range as individual pies
        _save_combined_pie_figure(wide, individual_years, spec, output_path)
        paths.append(output_path)
        return paths

    # ── Single pie ────────────────────────────────────────────────────────────
    if wide is not None:
        year_label = str(wide.index[-1])
        series = wide.iloc[-1].dropna()
        title_str = f"{spec['title']} ({year_label})"
    else:
        series = df.iloc[:, 0].dropna()
        title_str = spec["title"]

    series = pd.to_numeric(series, errors="coerce").dropna()
    series = series[series > 0]
    if series.empty:
        return output_path

    return _save_single_pie_figure(series, title_str, spec, output_path)


def render_type_e(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type E — Before/after grouped bar chart.
    df: index=entity names.
    - 2 columns: grouped before/after bars.
    - 1 column: single % change bars (positive=teal, negative=muted red).
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    x = np.arange(len(df.index))
    cols = df.columns.tolist()

    if len(cols) == 1:
        # Single-column % change mode — colour by sign
        values = df[cols[0]].values
        colors = [BRAND["primary"] if v >= 0 else "#c0392b" for v in values]
        ax.bar(x, values, 0.5, color=colors, edgecolor="white")
        ax.set_xticks(x)
        ax.set_xticklabels(df.index, fontsize=BRAND["font_size_axis"])
        # Value labels above/below each bar
        for xi, v in zip(x, values):
            va = "bottom" if v >= 0 else "top"
            ax.text(xi, v, f"{v:+.1f}%", ha="center", va=va,
                    fontsize=BRAND["font_size_label"], color=BRAND["secondary"])
    else:
        width = 0.35
        ax.bar(x - width / 2, df[cols[0]], width, label=cols[0],
               color=BRAND["grid_color"], edgecolor="white")
        ax.bar(x + width / 2, df[cols[1]], width, label=cols[1],
               color=BRAND["primary"], edgecolor="white")
        ax.set_xticks(x)
        ax.set_xticklabels(df.index, fontsize=BRAND["font_size_axis"])
        ax.legend(fontsize=BRAND["font_size_label"], frameon=False, loc="upper right")

    ax.axhline(0, color=BRAND["secondary"], linewidth=0.6)
    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    ax.set_ylabel(spec.get("y_label", ""), fontsize=BRAND["font_size_axis"])
    _apply_brand(ax, fig)
    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path

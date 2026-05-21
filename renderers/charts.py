# newsletter_agent/renderers/charts.py
import matplotlib
matplotlib.use("Agg")  # non-interactive backend for PNG export
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from newsletter_agent.config import BRAND


# Distinct colours for event markers — kept visually separate from LINE_COLORS
EVENT_COLORS = [
    "#dc2626",   # red
    "#7c3aed",   # purple
    "#f59e0b",   # amber
    "#0ea5e9",   # sky blue
    "#16a34a",   # green
]

# Ordered colour palette — Maj Invest newsletter style
LINE_COLORS = [
    "#8b2635",   # burgundy/maroon (primary contrast)
    "#2d6b6b",   # dark teal
    "#c8850a",   # amber/gold
    "#2563eb",   # blue
    "#0d9488",   # Maj Invest teal
    "#7c3aed",   # purple
    "#f97316",   # orange
    "#16a34a",   # green
    "#ec4899",   # pink
    "#64748b",   # slate grey
]

FIGSIZE = (BRAND["figure_width_px"]  / BRAND["figure_dpi"],
           BRAND["figure_height_px"] / BRAND["figure_dpi"])


def _color_for(i: int) -> str:
    return LINE_COLORS[i % len(LINE_COLORS)]


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
    """Apply brand styling to axes — Maj Invest newsletter style."""
    ax.set_facecolor(BRAND["background"])
    fig.patch.set_facecolor(BRAND["background"])
    # Horizontal grid lines only, very light
    ax.grid(True, axis="y", color=BRAND["grid_color"], linewidth=0.5, linestyle="-")
    ax.grid(False, axis="x")
    ax.set_axisbelow(True)
    # Remove all spines
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(labelsize=BRAND["font_size_axis"], colors=BRAND["secondary"],
                   length=0)
    ax.title.set_color(BRAND["secondary"])



def _add_footer(fig, spec: dict) -> float:
    """
    Add Note + Kilde lines at the bottom of the figure, Maj Invest newsletter style.
    Returns the bottom margin fraction needed so callers can pass it to tight_layout.
    """
    import textwrap
    note  = spec.get("note", "").strip()
    kilde = spec.get("kilde", "").strip()

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
        footer_text,
        fontsize=7,
        color="#888888",
        va="bottom",
        ha="left",
        fontstyle="italic",
        transform=fig.transFigure,
        linespacing=1.5,
    )
    return bottom_frac


def _place_end_labels(ax, df, colors, show_end_values: bool = False):
    """
    Place series labels at the end of each line, staggered vertically to avoid overlap.
    Uses adjusted y-positions in data coordinates so labels never stack on top of each other.
    When show_end_values=True, appends the last value below the label in European notation.
    """
    label_positions = []  # (y_data, col_name, color)
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        label_positions.append((s.iloc[-1], col, colors[i]))

    if not label_positions:
        return

    # Sort by y value ascending
    label_positions.sort(key=lambda x: x[0])

    # Get axis y range to compute minimum separation
    ylo, yhi = ax.get_ylim()
    min_gap = (yhi - ylo) * 0.09  # minimum 9% of axis range between labels

    # Spread labels that are too close — push upward
    adjusted = [list(p) for p in label_positions]  # [y_adj, name, color]
    for k in range(1, len(adjusted)):
        if adjusted[k][0] - adjusted[k-1][0] < min_gap:
            adjusted[k][0] = adjusted[k-1][0] + min_gap

    # Re-centre the stack around the midpoint of actual data positions
    # so labels don't all float to the top when many are clustered
    if len(adjusted) > 1:
        mid_actual = (label_positions[0][0] + label_positions[-1][0]) / 2
        mid_adjusted = (adjusted[0][0] + adjusted[-1][0]) / 2
        shift = mid_actual - mid_adjusted
        for item in adjusted:
            item[0] += shift

    for y_adj, col, color in adjusted:
        x_end = df[col].dropna().index[-1]
        last_val = df[col].dropna().iloc[-1]
        x_offset = 8
        if show_end_values:
            # Series name line
            ax.annotate(
                col,
                xy=(x_end, y_adj),
                xytext=(x_offset, 7),
                textcoords="offset points",
                fontsize=BRAND["font_size_label"],
                fontweight="bold",
                color=color,
                va="center",
                annotation_clip=False,
            )
            # Value line — slightly larger, bold
            val_str = f"{last_val:,.0f}".replace(",", ".")
            ax.annotate(
                val_str,
                xy=(x_end, y_adj),
                xytext=(x_offset, -7),
                textcoords="offset points",
                fontsize=BRAND["font_size_label"] + 1,
                fontweight="bold",
                color=color,
                va="center",
                annotation_clip=False,
            )
        else:
            ax.annotate(
                col,
                xy=(x_end, y_adj),
                xytext=(x_offset, 0),
                textcoords="offset points",
                fontsize=BRAND["font_size_label"],
                fontweight="bold",
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

    # Per-series color override: spec may carry {"series_colors": {"Label": "#hex", ...}}
    series_colors_map = spec.get("series_colors", {})
    colors = [
        series_colors_map.get(col, _color_for(i))
        for i, col in enumerate(df.columns)
    ]
    for i, col in enumerate(df.columns):
        s = df[col].dropna()
        if s.empty:
            continue
        ax.plot(s.index, s.values, color=colors[i], linewidth=1.6)

    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"],
                 pad=10)
    ax.set_xlabel(spec.get("x_label", ""), fontsize=BRAND["font_size_axis"],
                  color=BRAND["secondary"])
    # Y-label at top-left in horizontal orientation (Maj Invest / FT style)
    ax.set_ylabel("")
    y_label_text = spec.get("y_label", "")
    if y_label_text:
        ax.text(0, 1.01, y_label_text,
                transform=ax.transAxes,
                fontsize=BRAND["font_size_axis"] - 1,
                color=BRAND["secondary"],
                va="bottom", ha="left")

    # Auto date tick density based on date range
    if len(df.index) >= 2:
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
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha="center",
             fontsize=BRAND["font_size_axis"])

    # More y-axis ticks for larger figure
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=10, steps=[1,2,2.5,5,10]))

    # European thousands notation on y-axis (e.g. "5.000" instead of "5000")
    if spec.get("y_format") == "european_thousands":
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", "."))
        )

    _apply_brand(ax, fig)

    # Clip y-axis if a spike is dominating the scale (e.g. TTF gas crisis or Iran war spike).
    # Use p95 so even short 1-2 week spikes get caught; trigger when max > p95 × 1.3.
    all_vals = df.values.flatten()
    all_vals = all_vals[~np.isnan(all_vals)]
    if len(all_vals) > 10:
        p95 = np.percentile(all_vals, 95)
        raw_ymax = ax.get_ylim()[1]
        if raw_ymax > p95 * 1.3:
            ax.set_ylim(top=p95 * 1.2)

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
    ax.set_ylim(ylo - y_range * 0.04, yhi + y_range * 0.14)

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
    _place_end_labels(ax, df, colors, show_end_values=spec.get("show_end_values", False))

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_type_b(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type B — Cross-country bar chart.
    df: DataFrame with country names as index, single value column.
    spec: {"title", "x_label", "y_label"}
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    col = df.columns[0]
    values = df[col]
    colors = [BRAND["primary"] if v >= 0 else "#dc2626" for v in values]

    bars = ax.bar(df.index, values, color=colors, width=0.6, edgecolor="white")

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (0.01 if val >= 0 else -0.03),
                f"{val:+.2f}", ha="center", va="bottom" if val >= 0 else "top",
                fontsize=7, color=BRAND["secondary"])

    ax.axhline(0, color=BRAND["secondary"], linewidth=0.6)
    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    ax.set_xlabel(spec.get("x_label", ""), fontsize=BRAND["font_size_axis"])
    ax.set_ylabel(spec.get("y_label", ""), fontsize=BRAND["font_size_axis"])
    _apply_brand(ax, fig)
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


def render_type_e(df: pd.DataFrame, spec: dict, output_path: str) -> str:
    """
    Type E — Before/after grouped bar chart.
    df: index=region names, columns=["Før krigen", "Nu"] (or similar two timepoints).
    """
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=BRAND["figure_dpi"])

    x = np.arange(len(df.index))
    width = 0.35
    cols = df.columns.tolist()

    ax.bar(x - width / 2, df[cols[0]], width, label=cols[0],
           color=BRAND["grid_color"], edgecolor="white")
    ax.bar(x + width / 2, df[cols[1]], width, label=cols[1],
           color=BRAND["primary"], edgecolor="white")

    ax.axhline(0, color=BRAND["secondary"], linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(df.index, fontsize=BRAND["font_size_axis"])
    ax.set_title(spec["title"], fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"], pad=8)
    ax.set_ylabel(spec.get("y_label", ""), fontsize=BRAND["font_size_axis"])
    ax.legend(fontsize=BRAND["font_size_label"], frameon=False,
              loc="upper right")
    _apply_brand(ax, fig)
    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path

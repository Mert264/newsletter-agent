# newsletter_agent/renderers/tables.py
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from newsletter_agent.config import BRAND
from newsletter_agent.renderers.charts import _add_footer


def _wrap_col(text: str, max_chars: int = 14) -> str:
    """Wrap a column header at max_chars so it never overflows narrow cells."""
    return "\n".join(textwrap.wrap(str(text), width=max_chars))

FIGSIZE_TABLE = (
    BRAND["figure_width_px"] / BRAND["figure_dpi"],
    BRAND["figure_height_px"] * 0.55 / BRAND["figure_dpi"],
)

def _dynamic_table_width(n_data_cols: int) -> float:
    base = BRAND["figure_width_px"] / BRAND["figure_dpi"]
    if n_data_cols >= 10:
        return base * 1.35
    if n_data_cols >= 7:
        return base * 1.15
    return base


def render_type_d(data: dict, spec: dict, output_path: str) -> str:
    """
    Type D — Snapshot / before-after table.

    data: {
      "columns": ["col1", "col2", "col3"],   # column headers (excluding indicator)
      "rows":    [{"indicator": str, col1: str, col2: str, col3: str}, ...]
    }
    spec: {"title", "note", "kilde", ...}
    """
    cols  = data["columns"]
    rows  = data["rows"]

    if not rows:
        # Nothing to show — render a placeholder
        fig, ax = plt.subplots(figsize=FIGSIZE_TABLE, dpi=BRAND["figure_dpi"])
        ax.axis("off")
        ax.text(0.5, 0.5, "No data available", ha="center", va="center",
                fontsize=11, color="#9ca3af", transform=ax.transAxes)
        ax.set_title(spec.get("title", ""), fontsize=BRAND["font_size_title"],
                     fontweight="bold", loc="left", color=BRAND["secondary"], pad=10)
        fig.patch.set_facecolor(BRAND["background"])
        bottom = _add_footer(fig, spec)
        plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])
        fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
        plt.close(fig)
        return output_path

    n_rows = len(rows)
    n_cols = len(cols) + 1   # +1 for indicator column

    # Dynamic height: taller for more rows
    row_height = 0.46         # inches per data row
    header_h   = 0.50
    fig_h      = max(2.2, header_h + n_rows * row_height + 0.6)
    fig_w = _dynamic_table_width(n_data_cols)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=BRAND["figure_dpi"])
    ax.axis("off")
    fig.patch.set_facecolor(BRAND["background"])

    # ── Column widths ─────────────────────────────────────────────────────
    # Shrink indicator column for wide tables so data columns have enough space
    n_data_cols = len(cols)
    indicator_w = 0.25 if n_data_cols >= 8 else (0.30 if n_data_cols >= 5 else 0.40)
    other_w     = (1.0 - indicator_w) / n_data_cols if n_data_cols else 1.0
    col_widths  = [indicator_w] + [other_w] * n_data_cols

    # ── Build cell text ───────────────────────────────────────────────────
    # Wrap column headers using actual column width (not a fixed 14-char cap)
    _header_max = max(12, int(other_w * 90))
    wrapped_cols = [_wrap_col(c, max_chars=_header_max) for c in cols]
    header_row = [""] + wrapped_cols
    # Make header row taller if any header wraps to 2+ lines
    max_header_lines = max((c.count("\n") + 1) for c in header_row)
    # Wrap indicator text to prevent clipping in narrow indicator column
    _ind_max_chars  = int(indicator_w * 85)   # approx chars that fit per line at current font
    _data_max_chars = int(other_w * 85)        # approx chars that fit in data columns
    def _wrap_cell(text: str, max_chars: int) -> str:
        if not text:
            return ""
        s = str(text)
        # Never break tokens with no whitespace (numbers, codes) — only wrap text with spaces
        if " " not in s:
            return s
        lines = textwrap.wrap(s, width=max(8, max_chars))
        return "\n".join(lines) if lines else s
    _bridge_pfx = ("+", "−", "±", "=")  # +, −, ±, =
    def _indent(text: str) -> str:
        return ("   " + text) if text.startswith(_bridge_pfx) else text
    cell_text  = [[_wrap_cell(_indent(r.get("indicator", "")), _ind_max_chars)]
                  + [_wrap_cell(r.get(c, ""), _data_max_chars) for c in cols]
                  for r in rows]

    # ── Cell colours ─────────────────────────────────────────────────────
    header_colors = [[BRAND["primary"]] * n_cols]

    sep_row_indices = {i for i, r in enumerate(rows)
                       if r.get("indicator", "").startswith("━")}
    change_col = cols[-1] if cols else None
    row_colors = []
    for i, r in enumerate(rows):
        if i in sep_row_indices:
            row_colors.append(["#cce8e6"] * n_cols)
            continue
        base = [BRAND["background"]] * n_cols
        if change_col:
            change = str(r.get(change_col, ""))
            if change.startswith("+"):
                base[-1] = "#d1fae5"   # light green
            elif change.startswith("-"):
                base[-1] = "#fee2e2"   # light red
        row_colors.append(base)

    # Alternating row shading (skip separator rows)
    for i in range(0, len(row_colors), 2):
        if i in sep_row_indices:
            continue
        row_colors[i] = [
            "#f3fafa" if c == BRAND["background"] else c
            for c in row_colors[i]
        ]

    all_colors = header_colors + row_colors
    all_text   = [header_row]  + cell_text

    # ── Draw table ────────────────────────────────────────────────────────
    table = ax.table(
        cellText=all_text,
        cellColours=all_colors,
        cellLoc="center",
        colWidths=col_widths,
        loc="upper center",
        bbox=[0, 0, 1, 1],
    )
    table.auto_set_font_size(False)
    base_font = 7.5 if n_data_cols >= 10 else (8 if n_data_cols >= 7 else (9 if n_data_cols >= 5 else 10))
    table.set_fontsize(base_font)

    # Expand header row height when headers wrap to multiple lines
    if max_header_lines > 1:
        for j in range(n_cols):
            table[0, j].set_height(table[0, j].get_height() * max_header_lines * 0.9)

    # Style header
    for j in range(n_cols):
        cell = table[0, j]
        cell.set_facecolor(BRAND["primary"])
        cell.set_text_props(color="white", fontweight="bold", fontsize=10)
        cell.set_edgecolor("#0a5550")

    summary_indicators = {"median", "gennemsnit", "total", "sum", "avg", "mean", "average"}
    for i in range(1, len(all_text)):
        indicator_text = str(rows[i - 1].get("indicator", "")).lower().strip()
        is_summary = indicator_text in summary_indicators
        table[i, 0].set_text_props(ha="left", fontweight="600",
                                    color=BRAND["secondary"])
        table[i, 0].PAD = 0.08
        for j in range(0, n_cols):
            cell = table[i, j]
            if j > 0:
                cell.set_text_props(color=BRAND["secondary"])
            cell.set_edgecolor("#e4eaea")
            if is_summary:
                cell.set_facecolor(BRAND.get("primary_light", "#e6f2f1"))
                cell.set_text_props(fontweight="bold", color=BRAND["primary"])

    # Style separator (section-header) rows
    for idx in sep_row_indices:
        trow = idx + 1  # +1 for header row
        for j in range(n_cols):
            cell = table[trow, j]
            cell.set_facecolor("#cce8e6")
            cell.set_edgecolor("#89c8c4")
            cell.set_height(cell.get_height() * 1.3)
        table[trow, 0].set_text_props(
            ha="left", fontweight="bold", color=BRAND["primary"],
            fontsize=base_font + 1,
        )
        table[trow, 0].PAD = 0.06

    # ── Title ─────────────────────────────────────────────────────────────
    ax.set_title(spec.get("title", ""), fontsize=BRAND["font_size_title"] + 1,
                 fontweight="bold", loc="left", color=BRAND["secondary"],
                 pad=14)

    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path

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

# Table is wider than charts to accommodate more columns
FIGSIZE_TABLE = (
    BRAND["figure_width_px"] / BRAND["figure_dpi"],
    BRAND["figure_height_px"] * 0.55 / BRAND["figure_dpi"],
)


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
    base_fig_w = BRAND["figure_width_px"] / BRAND["figure_dpi"]
    fig_w = base_fig_w  # all tables use the same width for visual consistency

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
    cell_text  = [[_wrap_cell(r.get("indicator", ""), _ind_max_chars)]
                  + [_wrap_cell(r.get(c, ""), _data_max_chars) for c in cols]
                  for r in rows]

    # ── Cell colours ─────────────────────────────────────────────────────
    header_colors = [[BRAND["primary"]] * n_cols]

    change_col = cols[-1] if cols else None
    row_colors = []
    for r in rows:
        base = [BRAND["background"]] * n_cols
        if change_col:
            change = str(r.get(change_col, ""))
            if change.startswith("+"):
                base[-1] = "#d1fae5"   # light green
            elif change.startswith("-"):
                base[-1] = "#fee2e2"   # light red
        row_colors.append(base)

    # Alternating row shading
    for i in range(0, len(row_colors), 2):
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
    table.set_fontsize(7 if n_data_cols >= 8 else (8 if n_data_cols >= 5 else 9))

    # Expand header row height when headers wrap to multiple lines
    if max_header_lines > 1:
        for j in range(n_cols):
            table[0, j].set_height(table[0, j].get_height() * max_header_lines * 0.9)

    # Style header
    for j in range(n_cols):
        cell = table[0, j]
        cell.set_facecolor(BRAND["primary"])
        cell.set_text_props(color="white", fontweight="bold", fontsize=9)
        cell.set_edgecolor("#0a5550")

    # Style data rows
    for i in range(1, len(all_text)):
        # Indicator column: left-aligned, slightly bolder
        table[i, 0].set_text_props(ha="left", fontweight="600",
                                    color=BRAND["secondary"])
        table[i, 0].PAD = 0.08
        for j in range(1, n_cols):
            cell = table[i, j]
            cell.set_text_props(color=BRAND["secondary"])
            cell.set_edgecolor("#e4eaea")
        # Row border
        table[i, 0].set_edgecolor("#e4eaea")

    # ── Title ─────────────────────────────────────────────────────────────
    ax.set_title(spec.get("title", ""), fontsize=BRAND["font_size_title"],
                 fontweight="bold", loc="left", color=BRAND["secondary"],
                 pad=10)

    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path

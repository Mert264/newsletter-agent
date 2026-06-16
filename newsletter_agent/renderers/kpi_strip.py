"""KPI strip renderer — a horizontal row of key metric cards as a single PNG."""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from newsletter_agent.config import BRAND


def render_kpi_strip(metrics: list[dict], output_path: str,
                     title: str = "Nøgletal") -> str:
    """Render a horizontal strip of KPI cards.

    Each metric dict:
        name:    str  — metric label (e.g. "BNP-vækst")
        value:   str  — formatted current value (e.g. "2.3%")
        change:  str  — period change text (e.g. "+0.4 pp")  [optional]
        direction: str — "up" | "down" | "flat"               [optional]
        note:    str  — small footnote (e.g. "Q1 2025")       [optional]
        lower_is_better: bool — inverts color logic           [optional]
    """
    n = len(metrics)
    if n == 0:
        return ""

    card_w = 2.2
    card_h = 1.4
    gap = 0.15
    title_h = 0.45
    fig_w = n * card_w + (n - 1) * gap + 0.4
    fig_h = card_h + title_h + 0.3

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=BRAND["figure_dpi"],
                     facecolor="white")

    font = BRAND.get("font", "Helvetica Neue")

    if title:
        fig.text(0.02, 0.95, title,
                 fontsize=BRAND["font_size_title"], fontweight="bold",
                 color=BRAND["secondary"], va="top",
                 fontfamily=font)

    for i, m in enumerate(metrics):
        x0 = (0.2 + i * (card_w + gap)) / fig_w
        y0 = 0.08
        w = card_w / fig_w
        h = card_h / fig_h

        ax = fig.add_axes([x0, y0, w, h])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                                    facecolor="#f8fafa", edgecolor="#e4eaea",
                                    linewidth=1.2, clip_on=False,
                                    zorder=0))

        ax.text(0.5, 0.85, m.get("name", ""),
                ha="center", va="top", fontsize=8.5,
                color="#6b7280", fontfamily=font,
                transform=ax.transAxes)

        ax.text(0.5, 0.52, m.get("value", "—"),
                ha="center", va="center", fontsize=18, fontweight="bold",
                color=BRAND["secondary"], fontfamily=font,
                transform=ax.transAxes)

        change = m.get("change", "")
        direction = m.get("direction", "flat")
        lower_better = m.get("lower_is_better", False)

        if change:
            if direction == "up":
                color = "#dc2626" if lower_better else "#16a34a"
                arrow = "▲"
            elif direction == "down":
                color = "#16a34a" if lower_better else "#dc2626"
                arrow = "▼"
            else:
                color = "#6b7280"
                arrow = "●"
            ax.text(0.42, 0.22, arrow,
                    ha="center", va="center", fontsize=8,
                    color=color, fontfamily="DejaVu Sans",
                    transform=ax.transAxes)
            ax.text(0.54, 0.22, change,
                    ha="left", va="center", fontsize=9,
                    color=color, fontfamily=font,
                    transform=ax.transAxes)

        note = m.get("note", "")
        if note:
            ax.text(0.5, 0.06, note,
                    ha="center", va="center", fontsize=6.5,
                    color="#9ca3af", fontfamily=font,
                    transform=ax.transAxes)

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return output_path

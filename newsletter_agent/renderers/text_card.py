# newsletter_agent/renderers/text_card.py
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from newsletter_agent.config import BRAND
from newsletter_agent.renderers.charts import _add_footer

_BULLET = "▸"
_LINE_HEIGHT = 0.17   # axes-fraction units per bullet line


def render_type_summary(bullets: list, spec: dict, output_path: str) -> str:
    """
    Render an analyst summary card: title + bullet points on a clean background.
    bullets: list of plain strings (no bullet symbols — added here).
    spec:    {"title", "note", "kilde"}
    """
    if not bullets:
        bullets = ["No summary available."]

    # Wrap each bullet to ~90 chars so long lines don't overflow
    wrapped: list[list[str]] = [textwrap.wrap(b, width=90) or [b] for b in bullets]
    total_lines = sum(len(w) for w in wrapped)

    fig_w = BRAND["figure_width_px"] / BRAND["figure_dpi"]
    fig_h = max(2.2, 0.55 + total_lines * _LINE_HEIGHT * fig_w + 0.5)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=BRAND["figure_dpi"])
    ax.axis("off")
    fig.patch.set_facecolor(BRAND["background"])

    # Title
    ax.set_title(
        spec.get("title", ""),
        fontsize=BRAND["font_size_title"],
        fontweight="bold",
        loc="left",
        color=BRAND["secondary"],
        pad=10,
    )

    # Thin accent line under title
    ax.axhline(y=0.97, xmin=0.0, xmax=1.0, color=BRAND["primary"], linewidth=1.5)

    # Bullet points
    y = 0.88
    for lines in wrapped:
        first = True
        for line in lines:
            prefix = f"{_BULLET}  " if first else "    "
            ax.text(
                0.02, y, prefix + line,
                transform=ax.transAxes,
                fontsize=9,
                color=BRAND["secondary"],
                va="top",
                fontfamily="monospace" if False else None,
            )
            y -= _LINE_HEIGHT
            first = False
        y -= 0.03  # extra gap between bullets

    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path

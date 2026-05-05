# newsletter_agent/renderers/text_card.py
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from newsletter_agent.config import BRAND
from newsletter_agent.renderers.charts import _add_footer

_BULLET     = "▸"
_LINE_H_IN  = 0.20   # inches per wrapped text line at 9pt
_INTER_IN   = 0.06   # extra vertical gap between bullets (inches)


def _esc(text: str) -> str:
    """Escape $ so matplotlib does not treat them as LaTeX math delimiters."""
    return text.replace("$", r"\$")


def render_type_summary(bullets: list, spec: dict, output_path: str) -> str:
    """
    Render an analyst summary card: title + bullet points on a clean background.
    bullets: list of plain strings (no bullet symbols — added here).
    spec:    {"title", "note", "kilde"}
    """
    if not bullets:
        bullets = ["No summary available."]

    # Wrap each bullet to ~65 chars so lines stay compact
    wrapped: list[list[str]] = [textwrap.wrap(b, width=65) or [b] for b in bullets]
    total_lines = sum(len(w) for w in wrapped)
    n_bullets   = len(wrapped)

    fig_w  = BRAND["figure_width_px"] / BRAND["figure_dpi"]
    # Height sized exactly to content: title area + lines + inter-bullet gaps + footer margin
    fig_h  = max(2.0, 0.50 + total_lines * _LINE_H_IN + n_bullets * _INTER_IN + 0.45)

    # Axes-fraction step sizes derived from actual figure height
    line_frac  = _LINE_H_IN / fig_h
    inter_frac = _INTER_IN  / fig_h

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=BRAND["figure_dpi"])
    ax.axis("off")
    fig.patch.set_facecolor(BRAND["background"])

    # Title
    ax.set_title(
        _esc(spec.get("title", "")),
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
                0.02, y, _esc(prefix + line),
                transform=ax.transAxes,
                fontsize=9,
                color=BRAND["secondary"],
                va="top",
            )
            y -= line_frac
            first = False
        y -= inter_frac

    bottom = _add_footer(fig, spec)
    plt.tight_layout(rect=[0.0, bottom, 1.0, 1.0])
    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight")
    plt.close(fig)
    return output_path

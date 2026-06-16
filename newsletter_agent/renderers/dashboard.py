"""Dashboard composite renderer — combines multiple figure PNGs into a single grid image."""
from __future__ import annotations
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from newsletter_agent.config import BRAND


def render_dashboard(figure_paths: list[str], output_path: str,
                     title: str = "", cols: int = 0) -> str:
    """Render a dashboard grid from a list of individual figure PNGs.

    Args:
        figure_paths: list of paths to individual PNGs (order preserved)
        output_path: path for the composite output PNG
        title: optional dashboard title at top
        cols: number of columns (0 = auto: 2 for <=6 figures, 3 for >6)

    Returns path to the saved dashboard PNG.
    """
    n = len(figure_paths)
    if n == 0:
        return ""
    if n == 1:
        import shutil
        shutil.copy2(figure_paths[0], output_path)
        return output_path

    if cols == 0:
        cols = 2 if n <= 6 else 3
    rows = math.ceil(n / cols)

    cell_w = BRAND["figure_width_px"] / BRAND["figure_dpi"]
    cell_h = BRAND["figure_height_px"] / BRAND["figure_dpi"]
    title_h = 0.6 if title else 0.0

    fig_w = cell_w * cols + 0.3 * (cols - 1)
    fig_h = cell_h * rows + 0.3 * (rows - 1) + title_h + 0.3

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=BRAND["figure_dpi"],
                     facecolor="white")

    if title:
        fig.text(0.02, 1.0 - (title_h * 0.4) / fig_h, title,
                 fontsize=16, fontweight="bold", color=BRAND["secondary"],
                 va="top", ha="left",
                 fontfamily=BRAND.get("font", "Helvetica Neue"))

    for idx, path in enumerate(figure_paths):
        row = idx // cols
        col = idx % cols

        x0 = col * (cell_w + 0.3) / fig_w
        y0 = 1.0 - (title_h + 0.15 + (row + 1) * cell_h + row * 0.3) / fig_h
        w = cell_w / fig_w
        h = cell_h / fig_h

        ax = fig.add_axes([x0, y0, w, h])
        try:
            img = mpimg.imread(path)
            ax.imshow(img)
        except Exception:
            ax.text(0.5, 0.5, "Figur ikke tilgængelig", ha="center", va="center",
                    fontsize=10, color="#999")
        ax.axis("off")

    fig.savefig(output_path, dpi=BRAND["figure_dpi"], bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return output_path

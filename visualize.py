"""
Visualize a routed PCB board using matplotlib.

Two panels: Top copper (F.Cu, layer 0) and Bottom copper (B.Cu, layer 1).
Legend is placed below both panels in multiple columns so it never overlaps the board.
"""

import logging
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)

from router.board import Grid
from router.netlist import Component, Net
from router.router import Router

NET_COLORS = [
    "#e74c3c",  # red
    "#2980b9",  # blue
    "#27ae60",  # green
    "#f39c12",  # orange
    "#8e44ad",  # purple
    "#16a085",  # teal
    "#d35400",  # burnt orange
    "#1abc9c",  # mint
    "#c0392b",  # dark red
    "#2c3e50",  # dark navy
    "#e67e22",  # carrot
    "#3498db",  # lighter blue
    "#9b59b6",  # amethyst
    "#1abc9c",  # green sea
    "#e74c3c",  # alizarin
]


def _net_color(net_id: int) -> str:
    return NET_COLORS[(net_id - 1) % len(NET_COLORS)]


def plot_board(grid: Grid, nets: list, router: Router,
               components: list = None,
               title: str = "PCB Auto-Router Result",
               save_path: str = "demo_result.png") -> None:

    routed_ids = set(router.routed.keys())
    poured_ids = set(router.pour_masks.keys())

    # --- Figure layout ---
    # Two board panels side by side, legend below in columns.
    board_ar = grid.height_mm / max(grid.width_mm, 0.01)
    panel_w = 10.0          # inches per panel
    panel_h = panel_w * board_ar
    legend_rows = max(1, len(nets) // 5)   # ~5 cols → estimate rows
    legend_h = min(3.5, 0.22 * legend_rows)  # cap legend area

    fig_w = panel_w * 2 + 1.0
    fig_h = panel_h + legend_h + 1.2   # +1.2 for title + margins

    fig, (ax0, ax1) = plt.subplots(
        1, 2,
        figsize=(fig_w, fig_h),
        gridspec_kw={"wspace": 0.08}
    )
    fig.patch.set_facecolor("#0f0f1a")
    fig.suptitle(title, color="white", fontsize=9,
                 y=1.0 - 0.3 / fig_h)   # just below top edge

    # Fraction of figure height for legend
    leg_frac = legend_h / fig_h
    plt.subplots_adjust(bottom=leg_frac + 0.04, top=1.0 - 0.6 / fig_h,
                        left=0.04, right=0.98)

    # --- Draw each layer in its own panel ---
    _draw_layer(ax0, grid, nets, router, components,
                routed_ids, poured_ids, layer=0)
    ax0.set_title("Top copper  (F.Cu)", color="#7ec8e3", fontsize=10, pad=6)

    _draw_layer(ax1, grid, nets, router, components,
                routed_ids, poured_ids, layer=1)
    ax1.set_title("Bottom copper  (B.Cu)", color="#e3b07e", fontsize=10, pad=6)

    # --- Legend below both panels ---
    legend_items = []
    for net in nets:
        if net.net_id in routed_ids:
            status = "routed"
        elif net.net_id in poured_ids:
            status = "poured"
        else:
            status = "UNROUTED"
        legend_items.append(
            mpatches.Patch(color=_net_color(net.net_id),
                           label=f"{net.name} ({status})")
        )

    ncols = min(6, max(2, len(legend_items) // 8 + 1))
    fig.legend(handles=legend_items,
               loc="lower center",
               ncol=ncols,
               bbox_to_anchor=(0.5, 0.0),
               facecolor="#2c2c4e", edgecolor="#666699",
               labelcolor="white", fontsize=7.5,
               handlelength=1.2, handleheight=0.9,
               columnspacing=1.0, borderpad=0.6)

    # --- Stats text ---
    total = len(nets)
    done = len(routed_ids) + len(poured_ids)
    via_total = sum(len(v) for v in router.vias.values())
    poured_str = f"   Poured: {len(poured_ids)}" if poured_ids else ""
    stats = (f"Nets: {done}/{total} connected{poured_str}    "
             f"Vias: {via_total}    "
             f"Grid: {grid.cols}×{grid.rows} @ {grid.resolution} mm/cell")
    fig.text(0.01, leg_frac + 0.005, stats,
             color="#f0e68c", fontsize=8,
             bbox=dict(facecolor="#1a1a2e", edgecolor="#f0e68c", alpha=0.85))

    plt.savefig(save_path, dpi=150, bbox_inches="tight",
                facecolor="#0f0f1a")
    logger.info("Saved %s", save_path)
    plt.show()


# ------------------------------------------------------------------
# Per-layer drawing
# ------------------------------------------------------------------

def _draw_layer(ax, grid: Grid, nets: list, router: Router,
                components: list, routed_ids: set, poured_ids: set,
                layer: int) -> None:
    bg = "#1a1a2e" if layer == 0 else "#1a2a1a"
    ax.set_facecolor(bg)

    # Board outline
    ax.add_patch(mpatches.Rectangle(
        (0, 0), grid.width_mm, grid.height_mm,
        linewidth=2, edgecolor="#f0e68c", facecolor="none", zorder=1
    ))

    # Component outlines (silkscreen — same on both sides)
    if components:
        for comp in components:
            ax.add_patch(mpatches.Rectangle(
                (comp.x, comp.y), comp.width, comp.height,
                linewidth=1.0, edgecolor="#f0e68c",
                facecolor="#f0e68c08", linestyle="--", zorder=2
            ))
            ax.text(comp.x + comp.width / 2,
                    comp.y + comp.height / 2,
                    comp.ref,
                    ha="center", va="center",
                    color="#f0e68c", fontsize=6,
                    alpha=0.7, zorder=3,
                    fontfamily="monospace")

    # Copper pour
    for net in nets:
        masks = router.pour_masks.get(net.net_id, {})
        if layer not in masks:
            continue
        mask = masks[layer]
        rgb = mcolors.to_rgb(_net_color(net.net_id))
        rgba = np.zeros((*mask.shape, 4), dtype=float)
        rgba[..., :3] = rgb
        rgba[..., 3] = np.where(mask, 0.30, 0.0)
        ax.imshow(rgba, origin='lower',
                  extent=[0, grid.width_mm, 0, grid.height_mm],
                  aspect='auto', interpolation='nearest', zorder=3)

    # Traces — only segments on this layer
    for net in nets:
        color = _net_color(net.net_id)
        for path in router.routed.get(net.net_id, []):
            _draw_path_layer(ax, grid, path, color, layer)

    # Vias (connect both layers — draw on both panels)
    for net in nets:
        color = _net_color(net.net_id)
        for (col, row) in router.vias.get(net.net_id, []):
            x, y = grid.grid_to_mm(col, row)
            ax.plot(x, y, "o", markersize=6,
                    markeredgecolor="white", markerfacecolor=color,
                    markeredgewidth=1.2, zorder=6)

    # Pads — show all pads on both panels (THT pads appear on both sides)
    pad_half = max(0.5, grid.resolution * 1.5) / 2
    for net in nets:
        color = _net_color(net.net_id)
        for pad in net.pads:
            if pad.layer != layer:
                continue
            ax.add_patch(mpatches.Rectangle(
                (pad.x - pad_half, pad.y - pad_half),
                pad_half * 2, pad_half * 2,
                linewidth=0.8, edgecolor="white",
                facecolor=color, zorder=7
            ))

    # Ratsnest on top layer only (avoid drawing twice)
    if layer == 0:
        for net in nets:
            if net.net_id not in routed_ids and net.net_id not in poured_ids:
                pads = net.pads
                for i in range(1, len(pads)):
                    ax.plot([pads[i - 1].x, pads[i].x],
                            [pads[i - 1].y, pads[i].y],
                            "--", color="#ff4444",
                            linewidth=0.7, alpha=0.65, zorder=2)

    ax.set_xlim(-1, grid.width_mm + 1)
    ax.set_ylim(-1, grid.height_mm + 1)
    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)", color="white", fontsize=8)
    ax.set_ylabel("Y (mm)", color="white", fontsize=8)
    ax.tick_params(colors="white", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#444466")


# ------------------------------------------------------------------
# Path drawing helpers
# ------------------------------------------------------------------

def _draw_path_layer(ax, grid: Grid, path: list,
                     color: str, target_layer: int) -> None:
    """Draw only the segments of path that are on target_layer."""
    if not path:
        return
    seg_x, seg_y = [], []
    for col, row, layer in path:
        if layer == target_layer:
            x, y = grid.grid_to_mm(col, row)
            seg_x.append(x)
            seg_y.append(y)
        else:
            _flush_seg(ax, seg_x, seg_y, color)
            seg_x, seg_y = [], []
    _flush_seg(ax, seg_x, seg_y, color)


def _flush_seg(ax, xs, ys, color):
    if len(xs) < 2:
        return
    ax.plot(xs, ys, "-", color=color, linewidth=1.8,
            solid_capstyle="round", solid_joinstyle="round", zorder=4)

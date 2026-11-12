"""Axis-level QC plot building blocks for plane-to-anatomy registration.

Each `draw_*` function draws one plane's result onto a Matplotlib axis passed
in; look settings (colormaps, colours, margins) are arguments, so figure
layout and styling stay in the notebook. Adapted from the plotting cells of
`notebooks/register_plane_to_anatomy.ipynb`.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgb
from skimage.segmentation import find_boundaries

from registration.image_utils import norm01


def draw_registration_overlay(axis, plane_result, fixed_cmap="Reds", moving_cmap="Greens", fixed_vmax=0.5, moving_alpha=0.6):
    """Draw the matched anatomy and the registered plane on top of each other.

    Zooms to the square ANTs registered in.

    Args:
        axis (matplotlib.axes.Axes): Axis to draw on.
        plane_result (dict): One plane's result (`registration`, `fixed_image`, `warped_image`, ...).
        fixed_cmap (str): Colormap of the anatomy.
        moving_cmap (str): Colormap of the registered plane.
        fixed_vmax (float): Upper colour limit of the anatomy (0-1 normalized).
        moving_alpha (float): Opacity of the registered plane.
    """
    axis.imshow(plane_result["fixed_image"], cmap=fixed_cmap, vmax=fixed_vmax)
    axis.imshow(plane_result["warped_image"], cmap=moving_cmap, alpha=moving_alpha)
    square_x0, square_y0, square_x1, square_y1 = plane_result["registration"]["fixed_region_xyxy"]
    # -0.5 aligns with pixel edges; the y axis runs top-down.
    axis.set_xlim(square_x0 - 0.5, square_x1 - 0.5)
    axis.set_ylim(square_y1 - 0.5, square_y0 - 0.5)
    axis.set_title(f"plane {plane_result['plane_index']}, z={plane_result['best_depth']}, post_ncc={plane_result['registration']['post_ncc']:.2f}")
    axis.axis("off")


def draw_depth_profile(axis, plane_result, line_color="#275d8c", best_depth_color="#c1121f"):
    """Draw the NCC match score against anatomy depth, marking the chosen depth.

    Args:
        axis (matplotlib.axes.Axes): Axis to draw on.
        plane_result (dict): One plane's result (`match`, `best_depth`, `plane_index`).
        line_color (str): Profile colour.
        best_depth_color (str): Colour of the chosen-depth marker.
    """
    depth_scores = plane_result["match"]["scores"]
    best_depth = plane_result["best_depth"]
    axis.plot(depth_scores, color=line_color, linewidth=1.5)
    axis.axvline(best_depth, color=best_depth_color, linestyle="--", linewidth=1.2)
    axis.scatter([best_depth], [depth_scores[best_depth]], color=best_depth_color, s=24, zorder=3)
    axis.set_title(f"plane {plane_result['plane_index']}: best z={best_depth}")
    axis.set_xlabel("Anatomy depth (slice index)")
    axis.spines[["top", "right"]].set_visible(False)


def roi_label_image(plane_result):
    """Rasterize a plane's warped ROIs into one label image on the anatomy slice.

    Args:
        plane_result (dict): One plane's result (`anatomy_slice`, `warped_rois`).

    Returns:
        numpy.ndarray: int32 image, ROI list position + 1 (0 = background).
    """
    labels = np.zeros(plane_result["anatomy_slice"].shape, dtype=np.int32)
    for roi_number, roi in enumerate(plane_result["warped_rois"], start=1):
        labels[roi["ypix_aligned"], roi["xpix_aligned"]] = roi_number
    return labels


def draw_roi_overlay(axis, plane_result, outline_color="#51eaea", zoom_margin_px=20):
    """Draw the warped ROI outlines on the gray matched anatomy slice.

    Args:
        axis (matplotlib.axes.Axes): Axis to draw on.
        plane_result (dict): One plane's result.
        outline_color (str): ROI outline colour.
        zoom_margin_px (int): Margin around the ROIs' bounding box, in anatomy pixels.
    """
    labels = roi_label_image(plane_result)
    overlay = np.repeat(norm01(plane_result["anatomy_slice"], 1, 99)[..., None], 3, axis=2)  # gray -> RGB
    overlay[find_boundaries(labels, mode="inner")] = to_rgb(outline_color)
    axis.imshow(overlay)
    roi_rows, roi_cols = np.nonzero(labels)
    if roi_rows.size > 0:
        axis.set_xlim(roi_cols.min() - zoom_margin_px, roi_cols.max() + zoom_margin_px)
        axis.set_ylim(roi_rows.max() + zoom_margin_px, roi_rows.min() - zoom_margin_px)
    axis.set_title(f"plane {plane_result['plane_index']}: {len(plane_result['warped_rois'])} ROIs")
    axis.axis("off")


def draw_mean_image(axis, plane_result, clip_percentiles=(2, 98)):
    """Draw the plane's suite2p mean image.

    Args:
        axis (matplotlib.axes.Axes): Axis to draw on.
        plane_result (dict): One plane's result (`reference_image`, `plane_index`).
        clip_percentiles (tuple): Display contrast clip.
    """
    axis.imshow(norm01(plane_result["reference_image"], *clip_percentiles), cmap="gray")
    axis.set_title(f"plane {plane_result['plane_index']}: suite2p mean image")
    axis.axis("off")


def draw_matched_anatomy(axis, plane_result, clip_percentiles=(2, 98)):
    """Draw the matched anatomy slice, cropped to where the registered plane has data.

    Args:
        axis (matplotlib.axes.Axes): Axis to draw on.
        plane_result (dict): One plane's result (`anatomy_slice`, `warped_image`, `best_depth`).
        clip_percentiles (tuple): Display contrast clip.
    """
    footprint_rows, footprint_cols = np.nonzero(plane_result["warped_image"])
    anatomy = plane_result["anatomy_slice"]
    if footprint_rows.size > 0:
        anatomy = anatomy[footprint_rows.min():footprint_rows.max() + 1, footprint_cols.min():footprint_cols.max() + 1]
    axis.imshow(norm01(anatomy, *clip_percentiles), cmap="gray")
    axis.set_title(f"matched anatomy z={plane_result['best_depth']}")
    axis.axis("off")


def save_figure(figure, path, dpi):
    """Save a figure (creating its folder) and close it to free memory.

    Args:
        figure (matplotlib.figure.Figure): Figure to save.
        path (Path): Output image file.
        dpi (int): Resolution; low values keep QC files small.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(figure)

"""Map registered suite2p ROIs towards the reference brain.

An ROI reaches the reference brain through three coordinate changes:

1. Functional plane -> raw anatomy: the in-plane registration
   (`registration.plane_registration.warp_roi_masks_to_anatomy`).
2. Raw anatomy -> canonical anatomy: the fixed index mapping that
   `preprocessing.spatial_preprocessing.preprocess_anatomy` applies to build
   the 8-bit anatomy NRRD (polarity X/Y flip, Z reversal, X/Y resize).
   No fitting involved -- it depends only on the polarity and the raw shape.
3. Canonical anatomy -> reference brain: the ANTs transform from anatomy ->
   reference registration (not implemented yet).

This module holds step 2; step 3 will be added here.
"""
import numpy as np

from preprocessing.spatial_preprocessing import normalize_polarity


def _rescale_pixel_coordinates(coordinates, source_size, target_size):
    """Map pixel coordinates onto a resized axis (skimage `resize` convention).

    `resize` aligns pixel centres, so a source pixel `i` maps to
    `(i + 0.5) * target_size / source_size - 0.5` on the resized axis.

    Args:
        coordinates (numpy.ndarray): Pixel coordinates along one axis.
        source_size (int): Axis length before resizing.
        target_size (int): Axis length after resizing.

    Returns:
        numpy.ndarray: Float coordinates on the resized axis.
    """
    rescaled_coordinates = (coordinates + 0.5) * target_size / source_size - 0.5
    return rescaled_coordinates


def convert_rois_to_canonical_space(warped_rois, anatomy_shape_zyx, polarity, target_xy_shape=(750, 750)):
    """Convert warped ROI coordinates into the canonical anatomy NRRD's voxels.

    Applies `preprocess_anatomy`'s steps, in its order, to coordinates instead
    of images: the polarity X/Y flip (north flips Y, south flips X), the Z
    reversal, then the X/Y rescale to `target_xy_shape`. Coordinates stay
    floats, because rescaling places pixels between voxel centres.

    Args:
        warped_rois (list): ROI dicts from
            `registration.plane_registration.warp_roi_masks_to_anatomy`, with
            `xpix_aligned`, `ypix_aligned` and `z_pix` in raw-anatomy voxels.
        anatomy_shape_zyx (tuple): `(n_slices, height, width)` of the raw
            anatomy stack the ROIs were registered to.
        polarity (str): Fish orientation, `"north"` or `"south"` (or an alias
            accepted by `normalize_polarity`); the one used for the NRRD.
        target_xy_shape (tuple): `(height, width)` of the canonical NRRD
            (`preprocess_anatomy`'s `target_xy_shape`).

    Returns:
        list: Copies of `warped_rois` with `xpix_canonical`, `ypix_canonical`,
        `zpix_canonical` (float arrays, NRRD voxel indices) and
        `med_canonical` (`[y, x]` median) added.

    Raises:
        ValueError: If `polarity` isn't north/south.
    """
    resolved_polarity = normalize_polarity(polarity)
    if resolved_polarity not in {"north", "south"}:
        raise ValueError(f"polarity must be 'north' or 'south', got {polarity!r}")
    n_slices, height, width = (int(size) for size in anatomy_shape_zyx)
    target_height, target_width = (int(size) for size in target_xy_shape)

    canonical_rois = []
    for roi in warped_rois:
        x = np.asarray(roi["xpix_aligned"], dtype=np.float64)
        y = np.asarray(roi["ypix_aligned"], dtype=np.float64)
        z = np.asarray(roi["z_pix"], dtype=np.float64)
        # 1. Polarity flip, as `apply_canonical_xy`: north flips Y, south flips X.
        if resolved_polarity == "north":
            y = (height - 1) - y
        else:
            x = (width - 1) - x
        # 2. Z reversal, as `np.flip(stack, axis=0)`.
        z = (n_slices - 1) - z
        # 3. X/Y rescale onto the canonical grid.
        x = _rescale_pixel_coordinates(x, width, target_width)
        y = _rescale_pixel_coordinates(y, height, target_height)

        canonical_roi = dict(roi)
        canonical_roi["xpix_canonical"] = x
        canonical_roi["ypix_canonical"] = y
        canonical_roi["zpix_canonical"] = z
        canonical_roi["med_canonical"] = [float(np.median(y)), float(np.median(x))] if x.size > 0 else [np.nan, np.nan]
        canonical_rois.append(canonical_roi)
    return canonical_rois

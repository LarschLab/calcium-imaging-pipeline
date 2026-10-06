"""Small, shared image-processing helpers used by the plane-to-anatomy
matching and registration steps.

Adapted from Danin Dharmaperwira's
`codex/functional-anatomy-qc` branch (`preprocessing/drift_analysis.py`,
normalized cross-correlation). Rewritten here as short, independent
functions so each step is easy to read, test, and reuse on its own.
"""

import numpy as np
import tifffile
from scipy.ndimage import gaussian_filter


def norm01(image, low_percentile=1.0, high_percentile=99.8):
    """Rescale an image to the 0-1 range, robust to rare outlier pixels.

    Uses the `low_percentile`-to-`high_percentile`
    percentile of pixel intensities as the scaling range instead of the true
    min/max, so a handful of extreme pixels (hot pixels, saturation) don't
    compress the rest of the image toward one end of the range. Falls back
    to the true min/max if the percentile range is degenerate.

    Port of Danin's `norm01` from `drift_analysis.py` (defaults 1-99.8).
    His `ddharmap-ANTs` `spatial.py` has a `norm01` with (1, 99) and a
    `_clip_norm01` with (5, 95), used for the ANTs inputs; pass those
    percentiles to reproduce them.

    Args:
        image (numpy.ndarray): Image of any numeric dtype.
        low_percentile (float): Lower percentile for normalization.
        high_percentile (float): Upper percentile for normalization.

    Returns:
        numpy.ndarray: Float32 image with values clipped to [0, 1]. An
        image with no intensity range (all pixels equal) becomes all
        zeros. An empty image is returned unchanged.
    """
    image = np.asarray(image, dtype=np.float32)
    if image.size == 0:
        return image

    low, high = np.percentile(image, (low_percentile, high_percentile))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        # Percentile range is degenerate (e.g. a mostly-uniform image);
        # fall back to the true min/max.
        low, high = float(image.min()), float(image.max())
    if high <= low:
        # No intensity range to rescale at all (e.g. a blank image); avoid
        # a divide-by-zero below and return an all-zero image instead.
        return np.zeros_like(image)

    normalized_image = np.clip((image - low) / (high - low), 0.0, 1.0).astype(np.float32)
    return normalized_image


def local_unsharp(image, sigma=1.0, amount=0.6):
    """Boost fine detail in an image using unsharp masking.

    Blurs the image, subtracts the blur from the original to isolate fine
    detail, then blends from the blurred base back toward the original by
    `amount`: `amount=0` returns the blur unchanged, `amount=1` returns the
    original image, and `amount` above 1 extrapolates past the original for
    a genuine sharpening boost. This makes small structures (cell bodies,
    tissue edges) more distinct before comparing two images, which improves
    cross-correlation matching. Port of Danin's `local_unsharp` (anchored at
    the blur, not at the original image); as in his code, normalize first:
    `local_unsharp(norm01(image))`.

    Args:
        image (numpy.ndarray): Image to sharpen, in the 0-1 range.
        sigma (float): Standard deviation of the Gaussian blur used to
            estimate the smooth, low-frequency part of the image.
        amount (float): Blend factor between the blurred base (0) and the
            original image (1); values above 1 sharpen past the original.

    Returns:
        numpy.ndarray: Sharpened image, clipped to [0, 1].
    """
    image = np.asarray(image, dtype=np.float32)
    blurred = gaussian_filter(image, sigma=sigma)
    # What the blur smoothed away: the image's fine, high-frequency detail.
    fine_detail = image - blurred
    # Blend from the blurred base toward the original (and past it, for
    # amount > 1) rather than boosting on top of the original image.
    boosted = blurred + amount * fine_detail
    sharpened_image = np.clip(boosted, 0.0, 1.0).astype(np.float32)
    return sharpened_image


def normalized_cross_correlation(image_a, image_b, denominator_epsilon=1e-8):
    """Measure how similar two same-shaped images are, ignoring brightness.

    Subtracts each image's mean before comparing, so the score reflects
    shared structure rather than overall brightness. Port of Danin's
    `corrcoef_img` (`ddharmap-ANTs` `spatial.py`).

    Args:
        image_a (numpy.ndarray): First image.
        image_b (numpy.ndarray): Second image, same shape as `image_a`.
        denominator_epsilon (float): Added to the denominator so a blank
            image (zero variance) gives 0.0 instead of dividing by zero.

    Returns:
        float: Correlation score in [-1, 1], where 1 is a perfect match.

    Raises:
        ValueError: If `image_a` and `image_b` have different shapes.
    """
    image_a = np.asarray(image_a, dtype=np.float32)
    image_b = np.asarray(image_b, dtype=np.float32)
    if image_a.shape != image_b.shape:
        raise ValueError(f"Cross-correlation images must have equal shape, got {image_a.shape} and {image_b.shape}")

    # Mean-subtract both images so the score reflects shared structure, not
    # shared brightness.
    centered_a = image_a - float(image_a.mean())
    centered_b = image_b - float(image_b.mean())
    denominator = float(np.sqrt(np.sum(centered_a * centered_a) * np.sum(centered_b * centered_b))) + denominator_epsilon
    correlation_score = float(np.sum(centered_a * centered_b) / denominator)
    return correlation_score


def read_pixel_size_um(tiff_path, micrometers_per_inch=25400.0, micrometers_per_centimeter=10000.0):
    """Read the physical pixel size, in micrometers, from a TIFF's metadata.

    Two-photon acquisition software stores pixel size as an X-resolution tag
    (pixels per unit) plus a resolution unit. This inverts that to get
    micrometers per pixel, which the matching and registration steps need to
    compare images taken at different zoom levels.

    Functionally equivalent to Lukas Breitzler's `read_pixel_size_um` in
    `2026_04_2D_functional_align_to_anatomy.ipynb

    Args:
        tiff_path (Path or str): Path to a TIFF file with resolution tags.
        micrometers_per_inch (float): Conversion factor from inches to micrometers.
        micrometers_per_centimeter (float): Conversion factor from centimeters to micrometers.

    Returns:
        float: Pixel size in micrometers.

    Raises:
        KeyError: If the TIFF has no XResolution tag.
    """
    with tifffile.TiffFile(tiff_path) as tiff_file:
        page = tiff_file.pages[0]
        # XResolution is stored as a (numerator, denominator) rational pair.
        x_resolution = page.tags["XResolution"].value
        resolution_unit = page.tags["ResolutionUnit"].value

    pixels_per_unit = x_resolution[0] / x_resolution[1]
    # Pixel size is the inverse of pixel density: units per pixel.
    pixel_size = 1 / pixels_per_unit

    if resolution_unit == 2:  # inches
        pixel_size_micrometers = pixel_size * micrometers_per_inch
        return pixel_size_micrometers
    if resolution_unit == 3:  # centimeters
        pixel_size_micrometers = pixel_size * micrometers_per_centimeter
        return pixel_size_micrometers
    return pixel_size  # already in the TIFF's native unit

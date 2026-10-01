"""Find where a functional imaging plane best matches within an anatomy
stack.

Searches an anatomy volume for the depth, scale, and X/Y position at which a
2D functional reference image (e.g. a suite2p mean image) best matches, using
normalized cross-correlation template matching. Adapted from Danin
Dharmaperwira's `codex/functional-anatomy-qc` branch
(`preprocessing/drift_analysis.py`).

Workflow (`match_plane_to_anatomy`), in order:
    1. Sharpen the reference image and every anatomy slice (same unsharp mask).
    2. Score one scale: resize the reference by that scale and slide it over
       every anatomy slice (`find_best_xy_at_each_depth`), giving a best
       score and X/Y position per depth.
    3. Search scales: repeat step 2 over a coarse grid of scales, then over
       finer grids around the best one; keep the highest-scoring scale and depth.
    4. Refine the depth to sub-slice precision with a parabola fit around the
       peak (`refine_peak_depth`).
"""

import cv2
import numpy as np
from skimage.transform import resize
from registration.image_utils import local_unsharp, norm01


def find_best_xy_at_each_depth(reference_image, anatomy_stack):
    """Find the best-matching X/Y position of an image at every anatomy depth.

    Runs an exhaustive normalized cross-correlation template match of
    `reference_image` against every anatomy Z-slice.

    Args:
        reference_image (numpy.ndarray): reference image (average) of the functional plane to place
            within the anatomy volume.
        anatomy_stack (numpy.ndarray): Anatomy volume, shaped
            (depth, height, width).

    Returns:
        tuple: `(scores, best_x, best_y)`, three arrays of length equal to
        the number of anatomy slices, giving the best-match NCC (normalized cross-correlation) score and
        the top-left X and Y pixel coordinates of that match at each depth.

    Raises:
        ValueError: If `reference_image` is larger than the anatomy slices
            in either dimension, since it can't be searched then.
    """
    template = norm01(reference_image)
    depth, height, width = anatomy_stack.shape
    if template.shape[0] > height or template.shape[1] > width:
        raise ValueError(
            f"Reference image {template.shape} is larger than anatomy slices "
            f"{(height, width)} and cannot be searched."
        )

    # -inf/-1 placeholders make it obvious downstream if a depth was never
    # scored (e.g. before its slot in the loop below is filled in).
    scores = np.full(depth, -np.inf, dtype=np.float32)
    best_x = np.full(depth, -1, dtype=np.int32)
    best_y = np.full(depth, -1, dtype=np.int32)
    for z_index, anatomy_slice in enumerate(anatomy_stack):
        normalized_slice = norm01(anatomy_slice)

        # Slide the template over every position in this slice and score
        # each one with normalized cross-correlation.
        response = cv2.matchTemplate(normalized_slice, template, cv2.TM_CCORR_NORMED)

        # minMaxLoc's third and fourth outputs (the minimum value and its
        # location) aren't needed here, so discard them.
        _, max_score, _, max_location = cv2.minMaxLoc(response)
        scores[z_index] = float(max_score)
        best_x[z_index], best_y[z_index] = int(max_location[0]), int(max_location[1])
    return scores, best_x, best_y


def refine_peak_depth(scores):
    """Estimate a best depth between slices around the strongest score.

    Fits a parabola through the score at the argmax and its two neighbors
    to refine the integer peak index to a sub-slice position.

    Args:
        scores (numpy.ndarray): Per-depth similarity scores.

    Returns:
        float: Sub-slice depth estimate of the peak. Falls back to the
        integer argmax when the peak is at an array boundary or the
        parabola fit is numerically degenerate.
    """
    # float64 keeps the parabola fit below numerically stable even when
    # `scores` came in as float32.
    values = np.asarray(scores, dtype=np.float64)
    peak = int(np.nanargmax(values))
    if peak == 0 or peak == values.size - 1:
        # No neighbor on one side, so there's nothing to fit a parabola
        # through — report the integer index as-is.
        integer_peak_depth = float(peak)
        return integer_peak_depth

    left, center, right = values[peak - 1 : peak + 2]
    # Curvature of the parabola through the three points; near zero means
    # the points are close to collinear and the fit is degenerate.
    denominator = left - 2.0 * center + right
    if not np.isfinite(denominator) or abs(denominator) < 1e-12:
        integer_peak_depth = float(peak)
        return integer_peak_depth

    # Vertex offset of that parabola from the integer peak, in slices.
    offset = 0.5 * (left - right) / denominator
    # Clip in case the fit places the vertex implausibly far from the
    # sampled points (can happen when neighboring scores are noisy).
    clipped_offset = np.clip(offset, -1.0, 1.0)
    subslice_peak_depth = float(peak + clipped_offset)
    return subslice_peak_depth


def _resized_shape(image_shape, scale):
    """Compute the pixel shape an image gets when resized by `scale`.

    Args:
        image_shape (tuple): Original `(height, width)`.
        scale (float): Scale factor applied to both dimensions.

    Returns:
        tuple: Resized `(height, width)`, rounded to whole pixels.
    """
    # max(1, ...) guards against a degenerate 0-pixel dimension at very
    # small scales.
    new_shape = tuple(max(1, int(round(dimension * scale))) for dimension in image_shape)
    return new_shape


def scale_image(image, scale):
    """Resize an image by a uniform scale factor.

    Args:
        image (numpy.ndarray): Image to resize.
        scale (float): Scale factor applied to both dimensions; a value
            close to 1.0 returns the image unchanged.

    Returns:
        numpy.ndarray: Resized float32 image.
    """
    image = np.asarray(image, dtype=np.float32)
    if np.isclose(scale, 1.0):
        return image

    resized_image = resize(image, _resized_shape(image.shape, scale), order=1, preserve_range=True, anti_aliasing=True).astype(np.float32)
    return resized_image


def _scale_candidates(center, half_window, step):
    """Create an inclusive sequence of image-scale values to test.

    Args:
        center (float): Scale value around which to search.
        half_window (float): Half-width of the search window around
            `center`.
        step (float): Spacing between candidate scale values.

    Returns:
        numpy.ndarray: Array of candidate scale values from
        `max(step, center - half_window)` to `center + half_window`
        inclusive.
    """
    # max(step, ...) keeps the window from reaching zero or negative scale.
    lower_bound = max(step, center - half_window)
    # + step * 0.25 nudges the stop value past center + half_window so
    # np.arange's exclusive upper bound doesn't drop that last candidate.
    upper_bound = center + half_window + step * 0.25
    candidate_scales = np.arange(lower_bound, upper_bound, step)
    return candidate_scales


def _evaluate(scale, reference_image, anatomy_stack):
    """Score one candidate scale, or skip it when it cannot fit.

    Args:
        scale (float): Candidate image scale to test.
        reference_image (numpy.ndarray): Functional reference image to
            resize by `scale` and place within the anatomy volume.
        anatomy_stack (numpy.ndarray): Anatomy volume, shaped
            (depth, height, width).

    Returns:
        dict or None: Match result at this scale, with keys `scale`
        (float), `best_z` (int), `score` (float), `x` (int), `y` (int),
        and `scores` (numpy.ndarray of per-depth NCC scores), or None
        if the resized reference no longer fits the anatomy slices.
    """
    resized = scale_image(reference_image, scale)
    # anatomy_stack.shape is (depth, height, width); resized is
    # (height, width), so compare index-by-index against shape[1:].
    if resized.shape[0] > anatomy_stack.shape[1] or resized.shape[1] > anatomy_stack.shape[2]:
        return None
    scores, xs, ys = find_best_xy_at_each_depth(resized, anatomy_stack)
    # nanargmax (rather than argmax) matches drift_analysis.py's search_scale
    # and stays safe if a NaN ever ends up in scores.
    best_z = int(np.nanargmax(scores))
    return {
        "scale": float(scale),
        "best_z": best_z,
        "score": float(scores[best_z]),
        "x": int(xs[best_z]),
        "y": int(ys[best_z]),
        "scores": scores,
    }


def _evaluate_scales(scales, reference_image, anatomy_stack, results_by_shape):
    """Score candidate scales, scoring each resized pixel shape only once.

    Scales closer together than one pixel's worth (e.g. steps of 0.0001 on a
    512-pixel image) resize the reference to the same shape, i.e. the same
    image, so they share one score. Each result still carries its own
    `scale`, so the outcome equals scoring every scale separately.

    Args:
        scales (numpy.ndarray): Candidate scale values.
        reference_image (numpy.ndarray): Functional reference image.
        anatomy_stack (numpy.ndarray): Anatomy volume, shaped
            (depth, height, width).
        results_by_shape (dict): Results scored so far, keyed by resized
            shape; updated in place so later passes can reuse them.

    Returns:
        list: Match results (see `_evaluate`) for the scales whose
        resized reference fits the anatomy slices.
    """
    results = []
    for scale in scales:
        resized_shape = _resized_shape(reference_image.shape, float(scale))
        if resized_shape not in results_by_shape:
            results_by_shape[resized_shape] = _evaluate(float(scale), reference_image, anatomy_stack)
        if results_by_shape[resized_shape] is not None:
            results.append({**results_by_shape[resized_shape], "scale": float(scale)})
    return results


def search_scale(reference_image, anatomy_stack, scale_start, scale_stop, scale_step, refine_windows):
    """Search over image scale, depth, and X/Y position for the best match.

    Port of Danin's `search_scale` (`drift_analysis.py`), taking any number
    of refine windows and adding `best_z_subslice`. Tries scale factors from `scale_start` to `scale_stop` in steps of
    `scale_step`, resizing `reference_image` at each candidate scale and
    scoring it against every anatomy depth with `find_best_xy_at_each_depth`.
    After this coarse pass, the search is repeated once per entry in
    `refine_windows`, each time in a narrower window around the current best
    scale, to refine the estimate.

    Args:
        reference_image (numpy.ndarray): Functional reference image to
            place within the anatomy volume.
        anatomy_stack (numpy.ndarray): Anatomy volume, shaped
            (depth, height, width).
        scale_start (float): Smallest scale factor to try in the coarse
            pass.
        scale_stop (float): Largest scale factor to try in the coarse pass.
        scale_step (float): Spacing between scale factors in the coarse
            pass.
        refine_windows (list): Sequence of `(half_window, step)` pairs. Each
            pair repeats the search in a window of that half-width and step
            size around the current best scale.

    Returns:
        dict: Best-scoring match, with keys `scale` (float), `best_z`
        (int), `best_z_subslice` (float, sub-slice depth estimate from
        `refine_peak_depth`), `score` (float), `x` (int), `y` (int), and
        `scores` (numpy.ndarray of per-depth NCC scores at the
        winning scale).

    Raises:
        RuntimeError: If no candidate scale produces an image that fits
            within the anatomy slices.
    """
    # Shared across passes, so a shape scored in one pass isn't rescored in the next.
    results_by_shape = {}
    # Coarse pass: score every scale in the requested range, skipping any
    # that don't fit.
    coarse_candidates = np.arange(scale_start, scale_stop + scale_step * 0.25, scale_step)
    evaluated = _evaluate_scales(coarse_candidates, reference_image, anatomy_stack, results_by_shape)
    if not evaluated:
        raise RuntimeError(
            f"No candidate scale between {scale_start} and {scale_stop} fits anatomy "
            f"slices {anatomy_stack.shape[1:]}."
        )
    best = max(evaluated, key=lambda result: result["score"])

    # Refine pass: repeat the search in progressively narrower windows
    # around the current best scale, keeping the improved result each time.
    for half_window, refine_step in refine_windows:
        if half_window <= 0 or refine_step <= 0:
            # A disabled/degenerate refine window; nothing to narrow.
            continue
        refined_candidates = _scale_candidates(best["scale"], half_window, refine_step)
        refined = _evaluate_scales(refined_candidates, reference_image, anatomy_stack, results_by_shape)
        if refined:
            best = max(refined, key=lambda result: result["score"])

    # Refine the winning scale's best depth
    best_z_subslice = refine_peak_depth(best["scores"])
    return {
        "scale": best["scale"],
        "best_z": best["best_z"],
        "best_z_subslice": best_z_subslice,
        "score": best["score"],
        "x": best["x"],
        "y": best["y"],
        "scores": best["scores"],
    }


def match_plane_to_anatomy(
    reference_image,
    anatomy_stack,
    scale_start=0.50,
    scale_stop=1.50,
    scale_step=0.05,
    refine_windows=((0.05, 0.01), (0.005, 0.001), (0.0005, 0.0001)),
    sharpen_sigma=1.0,
    sharpen_amount=0.6,
):
    """Match a functional plane to its best-fitting depth, scale, and position.

    Main entry point for plane-to-anatomy matching. Sharpens both
    `reference_image` and every slice of `anatomy_stack` with unsharp
    masking (using the same `sharpen_sigma`/`sharpen_amount` for both, as
    in `drift_analysis.py`), then searches over scale, depth, and X/Y
    position with `search_scale`.

    The scale defaults are Danin's production search (`ddharmap-ANTs`
    `pipeline.py`): coarse 0.50-1.50 in steps of 0.05, then three refine
    windows. Refine steps finer than one pixel of resizing share a score, so
    the finest window costs little.

    Args:
        reference_image (numpy.ndarray): Functional reference image (e.g. a
            suite2p mean image) to place within the anatomy volume.
        anatomy_stack (numpy.ndarray): Anatomy volume, shaped
            (depth, height, width).
        scale_start (float): Smallest scale factor to try in the coarse
            pass.
        scale_stop (float): Largest scale factor to try in the coarse pass.
        scale_step (float): Spacing between scale factors in the coarse
            pass.
        refine_windows (tuple): Sequence of `(half_window, step)` pairs.
            Each pair narrows the search around the current best scale,
            first coarsely then finely.
        sharpen_sigma (float): Standard deviation of the Gaussian blur used
            for unsharp masking.
        sharpen_amount (float): Blend factor between the blurred base and
            the original image for unsharp masking.

    Returns:
        dict: Best-scoring match, see `search_scale`, plus
        `params` (dict of the search settings used).
    """
    # Sharpening first makes fine structure (cell bodies, tissue edges) more
    # distinct, which improves the cross-correlation matches below.
    sharpened_reference = local_unsharp(norm01(reference_image), sigma=sharpen_sigma, amount=sharpen_amount)
    sharpened_anatomy = np.stack([local_unsharp(norm01(anatomy_slice), sigma=sharpen_sigma, amount=sharpen_amount) for anatomy_slice in anatomy_stack], axis=0)
    match = search_scale(
        sharpened_reference,
        sharpened_anatomy,
        scale_start=scale_start,
        scale_stop=scale_stop,
        scale_step=scale_step,
        refine_windows=refine_windows,
    )
    # The settings used, for the provenance record.
    match["params"] = {
        "scale_start": scale_start,
        "scale_stop": scale_stop,
        "scale_step": scale_step,
        "refine_windows": [list(window) for window in refine_windows],
        "sharpen_sigma": sharpen_sigma,
        "sharpen_amount": sharpen_amount,
    }
    return match

"""Find where a functional imaging plane best matches within an anatomy
stack.

Searches an anatomy volume for the depth, scale, and X/Y position at which a
2D functional reference image (e.g. a suite2p mean image) best matches, using
normalized cross-correlation template matching. Adapted from Danin
Dharmaperwira's `codex/functional-anatomy-qc` branch
(`preprocessing/drift_analysis.py`).

Workflow:
    1. `match_plane_to_anatomy` (main entry point) sharpens the reference
       image with `sharpen_with_unsharp_mask` (from `image_utils`) and
       every anatomy Z-slice with `sharpen_anatomy_stack`, using the same
       sigma/amount for both, then calls `find_best_scale_and_match`.
    2. `find_best_scale_and_match` tries a coarse grid of scale factors,
       resizing the reference image at each one and scoring it against
       every anatomy depth via `find_best_xy_at_each_depth`; it then
       repeats that search in progressively narrower windows around the
       best-scoring scale (using `_scale_candidates`) to refine the
       estimate.
    3. `find_best_xy_at_each_depth`, called at every candidate scale, slides
       the resized reference image over each anatomy Z-slice with
       normalized cross-correlation template matching, returning a score
       and best X/Y position per depth.
    4. `refine_peak_depth` takes the winning scale's per-depth scores and
       fits a parabola around the peak to turn the best integer depth into
       a sub-slice-precision depth estimate.
"""

import cv2
import numpy as np
from skimage.transform import resize
from registration.image_utils import normalize_to_unit_range, sharpen_with_unsharp_mask


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
        the number of anatomy slices, giving the best-match NCC score and
        the top-left X and Y pixel coordinates of that match at each depth.

    Raises:
        ValueError: If `reference_image` is larger than the anatomy slices
            in either dimension, since it can't be searched then.
    """
    template = normalize_to_unit_range(reference_image)
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
        normalized_slice = normalize_to_unit_range(anatomy_slice)

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


def _resize_by_scale(image, scale):
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

    # max(1, ...) guards against a degenerate 0-pixel dimension at very
    # small scales.
    new_shape = tuple(max(1, int(round(dimension * scale))) for dimension in image.shape)
    resized_image = resize(image, new_shape, order=1, preserve_range=True, anti_aliasing=True).astype(np.float32)
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


def _evaluate_scale(scale, reference_image, anatomy_stack):
    """Score one candidate scale, or skip it when it cannot fit.

    Args:
        scale (float): Candidate image scale to test.
        reference_image (numpy.ndarray): Functional reference image to
            resize by `scale` and place within the anatomy volume.
        anatomy_stack (numpy.ndarray): Anatomy volume, shaped
            (depth, height, width).

    Returns:
        dict or None: Match result at this scale, with keys `scale`
        (float), `best_depth` (int), `score` (float), `x` (int), `y` (int),
        and `depth_scores` (numpy.ndarray of per-depth NCC scores), or None
        if the resized reference no longer fits the anatomy slices.
    """
    resized = _resize_by_scale(reference_image, scale)
    # anatomy_stack.shape is (depth, height, width); resized is
    # (height, width), so compare index-by-index against shape[1:].
    if resized.shape[0] > anatomy_stack.shape[1] or resized.shape[1] > anatomy_stack.shape[2]:
        return None
    scores, xs, ys = find_best_xy_at_each_depth(resized, anatomy_stack)
    # nanargmax (rather than argmax) matches drift_analysis.py's search_scale
    # and stays safe if a NaN ever ends up in scores.
    best_depth = int(np.nanargmax(scores))
    return {
        "scale": float(scale),
        "best_depth": best_depth,
        "score": float(scores[best_depth]),
        "x": int(xs[best_depth]),
        "y": int(ys[best_depth]),
        "depth_scores": scores,
    }


def find_best_scale_and_match(reference_image, anatomy_stack, scale_start, scale_stop, scale_step, refine_windows):
    """Search over image scale, depth, and X/Y position for the best match.

    Tries scale factors from `scale_start` to `scale_stop` in steps of
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
        dict: Best-scoring match, with keys `scale` (float), `best_depth`
        (int), `best_depth_subslice` (float, sub-slice depth estimate from
        `refine_peak_depth`), `score` (float), `x` (int), `y` (int), and
        `depth_scores` (numpy.ndarray of per-depth NCC scores at the
        winning scale).

    Raises:
        RuntimeError: If no candidate scale produces an image that fits
            within the anatomy slices.
    """
    # Coarse pass: score every scale in the requested range, skipping any
    # that don't fit (_evaluate_scale returns None for those).
    coarse_candidates = np.arange(scale_start, scale_stop + scale_step * 0.25, scale_step)
    evaluated = [
        result
        for scale in coarse_candidates
        if (result := _evaluate_scale(float(scale), reference_image, anatomy_stack)) is not None
    ]
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
        refined = [
            result
            for scale in refined_candidates
            if (result := _evaluate_scale(float(scale), reference_image, anatomy_stack)) is not None
        ]
        if refined:
            best = max(refined, key=lambda result: result["score"])

    # Refine the winning scale's best depth
    best_depth_subslice = refine_peak_depth(best["depth_scores"])
    return {
        "scale": best["scale"],
        "best_depth": best["best_depth"],
        "best_depth_subslice": best_depth_subslice,
        "score": best["score"],
        "x": best["x"],
        "y": best["y"],
        "depth_scores": best["depth_scores"],
    }


def match_plane_to_anatomy(
    reference_image,
    anatomy_stack,
    scale_start=0.45,
    scale_stop=1.0,
    scale_step=0.05,
    refine_windows=((0.05, 0.01), (0.01, 0.002)),
    sharpen_sigma=1.0,
    sharpen_amount=0.6,
):
    """Match a functional plane to its best-fitting depth, scale, and position.

    Main entry point for plane-to-anatomy matching. Sharpens both
    `reference_image` and every slice of `anatomy_stack` with unsharp
    masking (using the same `sharpen_sigma`/`sharpen_amount` for both, as
    in `drift_analysis.py`), then searches over scale, depth, and X/Y
    position with `find_best_scale_and_match`.

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
            for unsharp masking, applied identically to the reference image
            and every anatomy slice.
        sharpen_amount (float): Blend factor between the blurred base and
            the original image for unsharp masking, applied identically to
            the reference image and every anatomy slice.

    Returns:
        dict: Best-scoring match, see `find_best_scale_and_match`.
    """
    # Sharpening first makes fine structure (cell bodies, tissue edges) more
    # distinct, which improves the cross-correlation matches below. Both
    # images get the same sigma/amount, matching drift_analysis.py's single
    # shared sharpen_sigma/sharpen_amount config used for both anatomy and
    # reference.
    sharpened_reference = sharpen_with_unsharp_mask(reference_image, sigma=sharpen_sigma, amount=sharpen_amount)
    sharpened_anatomy = np.stack([sharpen_with_unsharp_mask(anatomy_slice, sigma=sharpen_sigma, amount=sharpen_amount) for anatomy_slice in anatomy_stack], axis=0)
    return find_best_scale_and_match(
        sharpened_reference,
        sharpened_anatomy,
        scale_start=scale_start,
        scale_stop=scale_stop,
        scale_step=scale_step,
        refine_windows=refine_windows,
    )

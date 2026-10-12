# -*- coding: utf-8 -*-
r"""
Zebrafish 2p experiment: drifting gratings and looming stimuli presented in acquisition blocks.

Same block structure, Arduino triggers and output files as dots_loop_blocks.py, but the
stimuli are drawn live by PsychoPy instead of read from CSV files (no stimulus folder needed).

- Initializes the standard folder tree under:
  Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data\<experimenter>\Microscopy\<fish_ID>\...
- Runs n_pre_stim_blocks blank-screen blocks (spontaneous activity), then the stimulus blocks.
  Every block starts with a pulse on the acquisition pin (starts one 2P acquisition).
- Inside each stimulus block every condition (one per grating direction and per loom duration)
  appears the same number of times in random order, so all stimulus blocks last the same time.
- A grating trial shows the pattern still for grating_static_sec, then drifts for grating_sec.
- One loom trial is a train of looms_per_trial looms (expand, hold at full size, blank gap),
  counted as one stimulus like a dots CSV file; each loom onset is also logged.
- Dimming control (include_dimming_control): for every loom, a matched train of a disc at the
  loom's position and final size that never grows, only darkens, so the mean screen light equals
  the loom's on every frame. loom - dimming then isolates expansion from the luminance drop.
  Like the loom, every pixel is only full red or black (no grey levels, which flicker on the DLP
  projector): the disc darkens by turning more and more fine pattern elements black, as many as
  the loom has black pixels on that frame. Because only full red and black are used, the match
  does not depend on the projector gamma.
- The number of dropped frames is saved in the metadata (check it after runs with dimming).
- The aux pin is high while a stimulus (a whole grating or a whole loom/dimming train) is on screen.
- Events per trial: prestim{i}_pause, stim{i}_<name>, then grating{i}_motion (gratings) or
  loom{i}_onset{k} / dimming{i}_onset{k} (one per disc of the train), then poststim{i}_pause.
- Saves experiment log, block log, trial sequence, stimuli table, one luminance profile per
  loom/dimming condition and metadata CSVs into 01_raw/2p/metadata.

Based on dots_loop_blocks.py and loom_gratings.py (Matilde Perrino).
Created: 2026-10-07
"""

import datetime
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd
from psychopy import visual, core, monitors, gui, data
from pyfirmata import Arduino

from utils import init_experiment_tree

# ===== Run mode =====
DRY_RUN = False  # True: no Arduino (trigger pins only print), windowed on screen 0, saves under DRY_RUN_DATA_PATH

# ===== Monitor & window settings (same projector as dots_loop_blocks.py) =====
MONITOR_NAME = "DLC_Projector"
MONITOR_WIDTH_CM = 15.2
MONITOR_DISTANCE_CM = 1
PIXELS_MONITOR = [1280, 800]
STIM_SCREEN = 1
DRY_RUN_SCREEN = 0
FPS = 60
# PsychoPy rgb values run from -1 (off) to 1 (full). The projector only has a red light,
# so only the red channel matters; green and blue stay off everywhere.
BACKGROUND_RGB = (1, -1, -1)  # "red"
BLACK_RGB = (-1, -1, -1)
RED_ON_VALUE = 1              # red channel of background-red pixels
RED_OFF_VALUE = -1            # red channel of black pixels (green and blue are always off)

# ===== Stimulus drawing =====
PIXEL_SIZE_CM = MONITOR_WIDTH_CM / PIXELS_MONITOR[0]  # square pixels, as PsychoPy's cm units assume
SCREEN_HEIGHT_CM = PIXELS_MONITOR[1] * PIXEL_SIZE_CM
# The grating is a square as wide as the screen diagonal, so it covers the screen at any orientation
GRATING_SIZE_CM = math.hypot(MONITOR_WIDTH_CM, SCREEN_HEIGHT_CM)
GRATING_TEXTURE = "sin"
LOOM_POS_CM = (0, 0)
LOOM_CIRCLE_EDGES = 128  # more edges than PsychoPy's default 32 so the large loom looks round
DISC_TYPES = ("loom", "dimming")  # condition types drawn as a disc train from a per-frame profile
# Dimming pattern: one element = 2 x 2 screen pixels (0.24 mm), small enough to look uniform to
# the fish while keeping the image uploaded on each frame 4 times smaller than full resolution
DIMMING_ELEMENT_PIX = 2
DIMMING_BAYER_ORDER = 4    # 16 x 16 ordered-dither tile: elements turn black evenly spread out
DIMMING_PATTERN_SEED = 0   # fixed seed for the tie-break order -> same pattern in every run
FLIPPED_FISH_ORIENTATION = "bottom-left"
FLIP_DIRECTION_DEG = 180  # grating direction offset for a flipped fish (dots scripts flip x and y)

# ===== Arduino connection and trigger pins =====
ARDUINO_PORT = "COM3"
ACQ_TRIGGER_PIN = 11  # pulse at every block start -> starts a 2P acquisition
AUX_TRIGGER_PIN = 13  # high while a stimulus is on screen

# ===== Data roots and formats =====
DATA_PATH = Path(r"Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data")
DRY_RUN_DATA_PATH = Path.home() / "loom_gratings_dry_run"
MICROSCOPY_FOLDER = "Microscopy"
FILE_DATE_FORMAT = "%Y-%m-%d-%H%M"
FISH_BIRTH_FORMAT = "%Y-%m-%d"


def default_metadata():
    """Return the default experiment metadata shown in the first dialog.

    Returns:
        dict: Metadata with the same keys as dots_loop_blocks.py.
    """
    metadata = {
        "experiment_name": "loom_gratings_blocks",
        "experimenter": "Matilde",
        "experiment_date": data.getDateStr(format=FILE_DATE_FORMAT),
        "fish_ID": 3,
        "fish_birth": "2025-06-23",
        "fish_age_dpf": None,
        "genotype": "huc:H2B-GCamp6s",
        "size": "medium",
        "time_embedding": None,
        "fish_orientation": ["bottom-left", "top-right"],
        "respond_to_omr": False,
        "respond_to_vibrations": False,
        "respond_to_bouts": False,
        "embedding_comments": None,
        "projector_LED_current": 40,
        "general_comments": None
    }
    return metadata


def default_stimuli_params():
    """Return the default block, timing and stimulus parameters shown in the experiment dialog.

    Returns:
        dict: Experiment parameters. List-valued entries are comma-separated strings.
    """
    stimuli_params = {
        "n_pre_stim_blocks": 1,              # Blank-screen (spontaneous activity) blocks before the stimuli
        "pre_stim_resting_sec": 813.666667,  # Duration of each blank block (ignored if matched below)
        "match_pre_stim_to_block": True,     # Blank blocks last exactly as long as a stimulus block
        "pre_stim_pause_sec": 12.5,          # Blank before every stimulus (all types)
        "post_stim_pause_sec": 12.5,         # Blank after every stimulus -> always 25 s between stimuli
        "inter_block_pause_sec": 20.0,       # Pause between acquisition blocks
        "n_trials_per_block": 4,             # Trials per block (multiple of the number of conditions)
        "n_rep_stim": 6,                     # Repetitions per condition over the whole experiment
        "grating_directions_deg": "45,225",  # One condition per direction; 45/225 move along the fish axis (empty = no gratings)
        "grating_static_sec": 5.0,           # Pattern shown still before it starts drifting
        "grating_sec": 30.0,                 # Drift (motion) time after the static period
        "stripe_cm": 0.5,                    # Width of one stripe (a full cycle is two stripes)
        "grating_speed_cm_s": 1.0,
        "loom_durations_sec": "3",           # Expansion time of one loom; one condition per value (empty = no looms)
        "loom_start_radius_cm": 0.1,
        "loom_end_radius_cm": 16.0,          # 16 cm (as stim1_loom_6times_isolated.csv) covers the whole screen
        "loom_hold_sec": 1.0,                # Disc stays at full size after expanding
        "looms_per_trial": 6,                # Looms in one loom trial (a train counted as one stimulus)
        "loom_gap_sec": 1.0,                 # Blank between looms of the same train
        "include_dimming_control": True      # Add a luminance-matched dimming condition for every loom
    }
    return stimuli_params


def default_functional_params():
    """Return the default 2P functional scanning parameters (saved to metadata only).

    Returns:
        dict: Functional scanning parameters, as in dots_loop_blocks.py.
    """
    functional_params = {
        "mode": "resonant",
        "n_frames": 3,
        "n_slices": 5,
        "n_volumes": 1610,
        "step_size": 10,
        "framerate": 2,
        "AOM_mW": 32,
        "ETL_start": -20,
        "pump_speed": 0,
        "volume_flyback": 0,
        "frame_flyback": 0,
        "motion_correction": False
    }
    return functional_params


def default_anatomy_params():
    """Return the default anatomy-stack parameters asked for after the run.

    Returns:
        dict: Anatomy parameters, as in dots_loop_blocks.py.
    """
    anatomy_params = {
        "frames_per_slice_anatomy": 150,
        "step_size_um_anatomy": 2,
        "wavelenght_anatomy": 850,
        "AOM%_anatomy": 57
    }
    return anatomy_params


def show_dialog(params, title):
    """Show an editable PsychoPy dialog for a parameter dict; quit PsychoPy if cancelled.

    Args:
        params (dict): Parameters to edit; updated in place by the dialog.
        title (str): Dialog window title.

    Returns:
        None
    """
    dlg = gui.DlgFromDict(params, title=title, sortKeys=False)
    if not dlg.OK:
        core.quit()


def compute_age_dpf(fish_birth):
    """Compute fish age in days post fertilization from its birth date.

    Args:
        fish_birth (str): Birth date formatted as FISH_BIRTH_FORMAT (e.g. "2025-06-23").

    Returns:
        int: Age in days.
    """
    birth_date = datetime.datetime.strptime(fish_birth, FISH_BIRTH_FORMAT)
    age_dpf = (datetime.datetime.today() - birth_date).days
    return age_dpf


def parse_number_list(text):
    """Parse a comma-separated list of numbers, e.g. "0, 180" -> [0.0, 180.0].

    Args:
        text (str): Comma-separated numbers; an empty string gives an empty list.

    Returns:
        list of float: Parsed numbers.
    """
    numbers = [float(item) for item in str(text).split(",") if item.strip()]
    return numbers


def seconds_to_frames(duration_sec):
    """Convert a duration to a whole number of screen frames.

    Args:
        duration_sec (float): Duration in seconds.

    Returns:
        int: Number of frames at FPS.
    """
    n_frames = int(round(FPS * float(duration_sec)))
    return n_frames


def build_grating_conditions(stimuli_params, flip_coordinates):
    """Create one drifting-grating condition per requested direction.

    Args:
        stimuli_params (dict): Experiment parameters (grating_* and stripe_cm entries).
        flip_coordinates (bool): True if the fish faces FLIPPED_FISH_ORIENTATION.

    Returns:
        list of dict: Grating conditions. ``direction_deg`` is relative to the fish,
            ``screen_direction_deg`` is the orientation actually drawn.
    """
    direction_offset_deg = FLIP_DIRECTION_DEG if flip_coordinates else 0
    static_sec = float(stimuli_params["grating_static_sec"])
    motion_sec = float(stimuli_params["grating_sec"])
    grating_frames = seconds_to_frames(static_sec) + seconds_to_frames(motion_sec)
    grating_conditions = []
    for direction_deg in parse_number_list(stimuli_params["grating_directions_deg"]):
        grating_conditions.append({
            "stimulus": f"grating_{direction_deg:g}deg",
            "type": "grating",
            "duration_sec": grating_frames / FPS,
            "n_frames": grating_frames,
            "static_before_sec": static_sec,  # same field names as src/stimulus_analysis.py
            "motion_sec": motion_sec,
            "direction_deg": direction_deg,
            "screen_direction_deg": (direction_deg + direction_offset_deg) % 360,
            "stripe_cm": float(stimuli_params["stripe_cm"]),
            "speed_cm_s": float(stimuli_params["grating_speed_cm_s"]),
            "pre_pause_sec": float(stimuli_params["pre_stim_pause_sec"]),
            "post_pause_sec": float(stimuli_params["post_stim_pause_sec"]),
        })
    return grating_conditions


def compute_loom_train_frames(expand_sec, hold_sec, gap_sec, n_looms):
    """Count the frames of one loom train: each loom expands then holds, with gaps between looms.

    Args:
        expand_sec (float): Expansion time of one loom.
        hold_sec (float): Time the disc stays at full size.
        gap_sec (float): Blank time between two looms of the train.
        n_looms (int): Looms in the train.

    Returns:
        int: Number of frames from the first loom onset to the end of the last hold.
    """
    loom_frames = seconds_to_frames(expand_sec) + seconds_to_frames(hold_sec)
    # gaps only between looms, not after the last one (the post-stimulus pause follows)
    train_frames = n_looms * loom_frames + (n_looms - 1) * seconds_to_frames(gap_sec)
    return train_frames


def build_loom_conditions(stimuli_params):
    """Create one loom-train condition per requested loom expansion time.

    Args:
        stimuli_params (dict): Experiment parameters (loom_* and looms_per_trial entries).

    Returns:
        list of dict: Loom conditions; ``duration_sec`` and ``n_frames`` cover the whole train.

    Raises:
        ValueError: If looms are requested with looms_per_trial below 1.
    """
    expand_durations_sec = parse_number_list(stimuli_params["loom_durations_sec"])
    n_looms = int(stimuli_params["looms_per_trial"])
    if expand_durations_sec and n_looms < 1:
        raise ValueError(f"looms_per_trial must be at least 1 (got {n_looms}).")

    hold_sec = float(stimuli_params["loom_hold_sec"])
    gap_sec = float(stimuli_params["loom_gap_sec"])
    loom_conditions = []
    for expand_sec in expand_durations_sec:
        train_frames = compute_loom_train_frames(expand_sec, hold_sec, gap_sec, n_looms)
        loom_conditions.append({
            "stimulus": f"loom_{expand_sec:g}s",
            "type": "loom",
            "duration_sec": train_frames / FPS,
            "n_frames": train_frames,
            "expand_sec": expand_sec,
            "hold_sec": hold_sec,
            "gap_sec": gap_sec,
            "n_looms": n_looms,
            "start_radius_cm": float(stimuli_params["loom_start_radius_cm"]),
            "end_radius_cm": float(stimuli_params["loom_end_radius_cm"]),
            "pre_pause_sec": float(stimuli_params["pre_stim_pause_sec"]),
            "post_pause_sec": float(stimuli_params["post_stim_pause_sec"]),
        })
    return loom_conditions


def build_dimming_conditions(loom_conditions, stimuli_params):
    """Create one luminance-matched dimming condition per loom condition (if enabled).

    The dimming train copies the loom train (timing, pauses, position, radii); only the drawing
    differs: a disc fixed at the loom's end radius that darkens instead of expanding.

    Args:
        loom_conditions (list of dict): Loom conditions from ``build_loom_conditions``.
        stimuli_params (dict): Experiment parameters (include_dimming_control).

    Returns:
        list of dict: Dimming conditions named ``dimming_<expand>s``; empty if disabled.
    """
    if not stimuli_params["include_dimming_control"]:
        return []

    dimming_conditions = []
    for loom_condition in loom_conditions:
        dimming_condition = dict(loom_condition)  # same train, pauses and radii as the loom
        dimming_condition.update({
            "stimulus": f"dimming_{loom_condition['expand_sec']:g}s",
            "type": "dimming",
            "disc_radius_cm": loom_condition["end_radius_cm"],
            "dimming_element_pix": DIMMING_ELEMENT_PIX,
            "dimming_pattern_seed": DIMMING_PATTERN_SEED,
        })
        dimming_conditions.append(dimming_condition)
    return dimming_conditions


def compute_loom_radii_cm(condition):
    """Compute the loom radius on every frame of one loom: linear expansion, then hold.

    Args:
        condition (dict): Loom or dimming condition (start_radius_cm, end_radius_cm, expand_sec, hold_sec).

    Returns:
        ndarray: Radius in cm per frame (expansion frames followed by hold frames).
    """
    # linspace puts the last expansion frame exactly at the end radius
    expand_radii = np.linspace(condition["start_radius_cm"], condition["end_radius_cm"],
                               seconds_to_frames(condition["expand_sec"]))
    hold_radii = np.full(seconds_to_frames(condition["hold_sec"]), condition["end_radius_cm"])
    radii_cm = np.concatenate([expand_radii, hold_radii])
    return radii_cm


def compute_grid_distances_cm(element_pix):
    """Compute the distance of every screen grid element centre to the loom centre.

    Args:
        element_pix (int): Element size in screen pixels (1 = every pixel); must divide the screen size.

    Returns:
        ndarray: Distances in cm, shape (rows, columns), row 0 = top of the screen.

    Raises:
        ValueError: If element_pix does not divide the screen width and height.
    """
    width_pix, height_pix = PIXELS_MONITOR
    if width_pix % element_pix or height_pix % element_pix:
        raise ValueError(f"Element size {element_pix} px must divide the screen size {PIXELS_MONITOR}.")
    element_cm = element_pix * PIXEL_SIZE_CM
    # element centres in cm, origin at the screen centre like PsychoPy's cm units
    x_cm = (np.arange(width_pix // element_pix) + 0.5) * element_cm - MONITOR_WIDTH_CM / 2
    y_cm = SCREEN_HEIGHT_CM / 2 - (np.arange(height_pix // element_pix) + 0.5) * element_cm
    distances_cm = np.hypot(x_cm[np.newaxis, :] - LOOM_POS_CM[0], y_cm[:, np.newaxis] - LOOM_POS_CM[1])
    return distances_cm


def compute_screen_dark_fraction(radii_cm, sorted_distances_cm):
    """Compute the fraction of screen pixels covered by a disc of each radius at the loom centre.

    Parts of the disc outside the screen do not count, so a disc larger than the screen gives 1.

    Args:
        radii_cm (ndarray): Disc radii in cm.
        sorted_distances_cm (ndarray): Sorted per-pixel distances from ``compute_grid_distances_cm(1)``.

    Returns:
        ndarray: Covered fraction of the screen (0 to 1) per radius.
    """
    covered_pixels = np.searchsorted(sorted_distances_cm, radii_cm, side="right")
    dark_fraction = covered_pixels / len(sorted_distances_cm)
    return dark_fraction


def build_bayer_matrix(order):
    """Build a Bayer ordered-dither matrix: thresholds that spread dark elements evenly.

    Args:
        order (int): Recursion depth; the matrix is 2 ** order square.

    Returns:
        ndarray: Integer thresholds 0 .. 4 ** order - 1.
    """
    bayer = np.zeros((1, 1), dtype=int)
    for _ in range(order):
        # each step splits every cell into 2 x 2, filled in the standard order 0, 2 / 3, 1
        bayer = np.block([[4 * bayer, 4 * bayer + 2], [4 * bayer + 3, 4 * bayer + 1]])
    return bayer


def compute_dimming_ranks(element_distances_cm, disc_radius_cm, seed):
    """Give every disc element its rank in the darkening order (rank < n black -> element is black).

    Elements are ordered by a tiled Bayer threshold, so dark elements stay evenly spread at every
    level; equal thresholds in different tiles are ordered randomly (fixed seed). Elements outside
    the disc are never black.

    Args:
        element_distances_cm (ndarray): Output of ``compute_grid_distances_cm(DIMMING_ELEMENT_PIX)``.
        disc_radius_cm (float): Dimming disc radius.
        seed (int): Seed of the tie-break order.

    Returns:
        tuple: (ranks, int32 array shaped like element_distances_cm; number of disc elements).
    """
    n_rows, n_cols = element_distances_cm.shape
    tile = build_bayer_matrix(DIMMING_BAYER_ORDER)
    tile_size = tile.shape[0]
    n_tiles_down, n_tiles_across = -(-n_rows // tile_size), -(-n_cols // tile_size)  # ceiling division
    bayer_level = np.tile(tile, (n_tiles_down, n_tiles_across))[:n_rows, :n_cols]
    tie_break = np.random.default_rng(seed).random(element_distances_cm.shape)

    order = np.lexsort((tie_break.ravel(), bayer_level.ravel()))  # sort by Bayer level, then tie-break
    inside_disc = (element_distances_cm <= disc_radius_cm).ravel()
    disc_order = order[inside_disc[order]]  # disc elements only, in darkening order
    ranks = np.full(element_distances_cm.size, np.iinfo(np.int32).max, dtype=np.int32)
    ranks[disc_order] = np.arange(len(disc_order), dtype=np.int32)
    return ranks.reshape(element_distances_cm.shape), len(disc_order)


def build_loom_profile(loom_radii_cm, loom_dark_fraction):
    """Build the per-frame profile of one loom episode.

    Args:
        loom_radii_cm (ndarray): Loom radius per frame.
        loom_dark_fraction (ndarray): Screen fraction the loom makes black per frame.

    Returns:
        DataFrame: frame, radius_cm, dark_fraction and mean_light_rel (1 = background, 0 = black).
    """
    profile = pd.DataFrame({"frame": np.arange(len(loom_radii_cm)),
                            "radius_cm": loom_radii_cm,
                            "dark_fraction": loom_dark_fraction,
                            "mean_light_rel": 1 - loom_dark_fraction})
    return profile


def build_dimming_profile(loom_dark_fraction, n_screen_elements, n_disc_elements):
    """Build the per-frame profile of one dimming episode: how many elements are black.

    On every frame the dimming makes black the same share of the screen as the loom.

    Args:
        loom_dark_fraction (ndarray): Screen fraction the matched loom makes black per frame.
        n_screen_elements (int): Pattern elements on the whole screen.
        n_disc_elements (int): Pattern elements inside the dimming disc.

    Returns:
        DataFrame: frame, n_black_elements, dark_fraction, mean_light_rel and loom_dark_fraction.

    Raises:
        ValueError: If the dimming disc does not cover any screen element.
    """
    if n_disc_elements == 0:
        raise ValueError("The dimming disc does not cover any screen pixel; check loom_end_radius_cm.")
    n_black = np.minimum(np.round(loom_dark_fraction * n_screen_elements).astype(int), n_disc_elements)
    dark_fraction = n_black / n_screen_elements
    profile = pd.DataFrame({"frame": np.arange(len(n_black)),
                            "n_black_elements": n_black,
                            "dark_fraction": dark_fraction,
                            "mean_light_rel": 1 - dark_fraction,
                            "loom_dark_fraction": loom_dark_fraction})
    return profile


def build_disc_profiles(conditions):
    """Build the drawing profiles of all loom and dimming conditions (done once, before the run).

    Args:
        conditions (list of dict): All stimulus conditions.

    Returns:
        tuple: (dict stimulus name -> profile DataFrame for every loom/dimming condition;
            dict stimulus name -> rank array for every dimming condition).

    Raises:
        ValueError: If the loom centre is not vertically centred (the dimming pattern assumes it).
    """
    if LOOM_POS_CM[1] != 0:
        # with a centred disc the pattern is symmetric, so PsychoPy's image row order cannot matter
        raise ValueError("The dimming pattern assumes LOOM_POS_CM has y = 0.")
    sorted_pixel_distances_cm = np.sort(compute_grid_distances_cm(1), axis=None)
    element_distances_cm = compute_grid_distances_cm(DIMMING_ELEMENT_PIX)

    disc_profiles, dimming_ranks = {}, {}
    for condition in conditions:
        if condition["type"] not in DISC_TYPES:
            continue
        stimulus_name = condition["stimulus"]
        loom_radii_cm = compute_loom_radii_cm(condition)
        loom_dark_fraction = compute_screen_dark_fraction(loom_radii_cm, sorted_pixel_distances_cm)
        if condition["type"] == "loom":
            disc_profiles[stimulus_name] = build_loom_profile(loom_radii_cm, loom_dark_fraction)
            continue
        ranks, n_disc_elements = compute_dimming_ranks(element_distances_cm, condition["disc_radius_cm"],
                                                       condition["dimming_pattern_seed"])
        dimming_ranks[stimulus_name] = ranks
        disc_profiles[stimulus_name] = build_dimming_profile(loom_dark_fraction, element_distances_cm.size,
                                                             n_disc_elements)
    return disc_profiles, dimming_ranks


def build_block_sequence(conditions, n_rep_stim, n_trials_per_block):
    """Split the trials into blocks where each condition appears equally often, shuffled.

    Balancing within blocks keeps every stimulus block the same duration even though
    gratings and looms have different lengths.

    Args:
        conditions (list of dict): Stimulus conditions.
        n_rep_stim (int): Repetitions of each condition over the whole experiment.
        n_trials_per_block (int): Trials in one acquisition block.

    Returns:
        list of list of dict: One shuffled list of conditions per stimulus block.

    Raises:
        ValueError: If there are no conditions or the trials cannot be split into balanced blocks.
    """
    n_conditions = len(conditions)
    if n_conditions == 0:
        raise ValueError("No stimulus conditions: set grating_directions_deg and/or loom_durations_sec.")
    if n_trials_per_block % n_conditions != 0:
        raise ValueError(f"n_trials_per_block ({n_trials_per_block}) must be a multiple of the "
                         f"number of conditions ({n_conditions}) so blocks are balanced.")
    reps_per_block = n_trials_per_block // n_conditions
    if n_rep_stim % reps_per_block != 0:
        raise ValueError(f"n_rep_stim ({n_rep_stim}) must be a multiple of the repetitions per "
                         f"block ({reps_per_block} = n_trials_per_block / n_conditions).")

    n_blocks = n_rep_stim // reps_per_block
    block_sequence = []
    for _ in range(n_blocks):
        block_trials = random.sample(conditions * reps_per_block, k=n_trials_per_block)
        block_sequence.append(block_trials)
    return block_sequence


def compute_trial_frames(condition):
    """Count the frames of one trial: pre-stimulus pause, stimulus, post-stimulus pause.

    Args:
        condition (dict): Stimulus condition with pre_pause_sec, n_frames and post_pause_sec.

    Returns:
        int: Number of frames in the trial.
    """
    trial_frames = (seconds_to_frames(condition["pre_pause_sec"]) + condition["n_frames"]
                    + seconds_to_frames(condition["post_pause_sec"]))
    return trial_frames


def compute_block_duration_sec(block_trials):
    """Compute how long one stimulus block lasts.

    Args:
        block_trials (list of dict): Conditions presented in the block.

    Returns:
        float: Block duration in seconds, from whole frame counts.
    """
    block_frames = sum(compute_trial_frames(condition) for condition in block_trials)
    block_duration_sec = block_frames / FPS
    return block_duration_sec


def print_block_summary(stimuli_params, functional_params, block_sequence):
    """Print the planned block layout and the imaging volumes one block needs.

    Args:
        stimuli_params (dict): Experiment parameters incl. stimulus_block_duration_sec.
        functional_params (dict): Functional scanning parameters (framerate, n_volumes).
        block_sequence (list of list of dict): Stimulus blocks.

    Returns:
        None
    """
    block_duration_sec = stimuli_params["stimulus_block_duration_sec"]
    volumes_per_block = block_duration_sec * float(functional_params["framerate"])
    print(f"{stimuli_params['n_pre_stim_blocks']} pre-stim block(s) x "
          f"{float(stimuli_params['pre_stim_resting_sec']):.1f} s")
    print(f"{len(block_sequence)} stimulus block(s) x {block_duration_sec:.1f} s "
          f"({len(block_sequence[0])} trials each)")
    print(f"Volumes per block at {functional_params['framerate']} vol/s: {volumes_per_block:.0f} "
          f"(n_volumes is set to {functional_params['n_volumes']})")


class PrintingPin:
    """Stand-in for a pyfirmata output pin in DRY_RUN mode: prints instead of writing."""

    def __init__(self, pin_number):
        """Store the pin number used in the printed messages.

        Args:
            pin_number (int): Arduino digital pin number.
        """
        self.pin_number = pin_number

    def write(self, value):
        """Print the value that would be written to the pin.

        Args:
            value (int): 0 or 1.

        Returns:
            None
        """
        print(f"[dry run] pin {self.pin_number} -> {value}")


def connect_trigger_pins():
    """Connect to the Arduino and set both trigger pins low.

    Returns:
        tuple: (acquisition pin, aux pin); PrintingPin objects in DRY_RUN mode.
    """
    if DRY_RUN:
        pin_acq, pin_aux = PrintingPin(ACQ_TRIGGER_PIN), PrintingPin(AUX_TRIGGER_PIN)
    else:
        board = Arduino(ARDUINO_PORT)
        pin_acq = board.get_pin(f"d:{ACQ_TRIGGER_PIN}:o")
        pin_aux = board.get_pin(f"d:{AUX_TRIGGER_PIN}:o")
    pin_acq.write(0)
    pin_aux.write(0)
    return pin_acq, pin_aux


def pulse_pin(pin):
    """Send a short 1 -> 0 trigger pulse on a pin.

    Args:
        pin (object): Pin with a ``write`` method.

    Returns:
        None
    """
    pin.write(1)
    pin.write(0)


def create_window():
    """Open the PsychoPy window on the projector (or windowed on the main screen in DRY_RUN).

    Returns:
        visual.Window: Stimulus window with a BACKGROUND_RGB background.
    """
    monitor = monitors.Monitor(MONITOR_NAME, width=MONITOR_WIDTH_CM)
    monitor.setSizePix(PIXELS_MONITOR)
    monitor.setDistance(MONITOR_DISTANCE_CM)
    win = visual.Window(size=PIXELS_MONITOR, color=BACKGROUND_RGB, colorSpace="rgb", units="pix",
                        monitor=monitor, screen=DRY_RUN_SCREEN if DRY_RUN else STIM_SCREEN,
                        fullscr=not DRY_RUN)
    win.recordFrameIntervals = True  # lets win.nDroppedFrames count frames that came too late
    return win


def build_dimming_frame(ranks, n_black):
    """Build the full-screen dimming image: red background with the first n_black elements black.

    Args:
        ranks (ndarray): Element darkening ranks, from ``compute_dimming_ranks``.
        n_black (int): Number of black elements on this frame.

    Returns:
        ndarray: float32 image (rows, columns, 3) in PsychoPy's -1..1 rgb, only full red or black.
    """
    frame_rgb = np.full(ranks.shape + (3,), RED_OFF_VALUE, dtype=np.float32)  # green and blue off
    frame_rgb[..., 0] = np.where(ranks < n_black, RED_OFF_VALUE, RED_ON_VALUE)
    return frame_rgb


def create_stimuli(win, disc_profiles, dimming_ranks):
    """Create the reusable grating, loom disc and dimming image stimuli.

    Args:
        win (visual.Window): Stimulus window.
        disc_profiles (dict): Stimulus name -> per-frame profile, from ``build_disc_profiles``.
        dimming_ranks (dict): Stimulus name -> element ranks, from ``build_disc_profiles``.

    Returns:
        dict: grating, loom disc, full-screen dimming image and the profiles/ranks used to draw them.
    """
    grating = visual.GratingStim(win=win, tex=GRATING_TEXTURE, units="cm", size=GRATING_SIZE_CM)
    disc = visual.Circle(win=win, units="cm", pos=LOOM_POS_CM, edges=LOOM_CIRCLE_EDGES, colorSpace="rgb",
                         fillColor=BLACK_RGB, lineColor=BLACK_RGB)
    n_rows, n_cols = PIXELS_MONITOR[1] // DIMMING_ELEMENT_PIX, PIXELS_MONITOR[0] // DIMMING_ELEMENT_PIX
    empty_ranks = np.full((n_rows, n_cols), np.iinfo(np.int32).max, dtype=np.int32)
    # interpolate=False keeps every element a sharp block of full red or black screen pixels
    dimming_image = visual.ImageStim(win=win, image=build_dimming_frame(empty_ranks, 0), units="pix",
                                     size=PIXELS_MONITOR, interpolate=False, colorSpace="rgb")
    stimuli = {"grating": grating, "disc": disc, "dimming_image": dimming_image,
               "disc_profiles": disc_profiles, "dimming_ranks": dimming_ranks}
    return stimuli


def present_blank(win, duration_sec):
    """Show the empty background for a given time.

    Args:
        win (visual.Window): Stimulus window.
        duration_sec (float): Duration in seconds.

    Returns:
        None
    """
    for _ in range(seconds_to_frames(duration_sec)):
        win.flip()


def present_grating(win, grating, condition, logger, trial_idx):
    """Show the grating still for static_before_sec, then drift it for motion_sec.

    Args:
        win (visual.Window): Stimulus window.
        grating (visual.GratingStim): Grating stimulus.
        condition (dict): Grating condition (stripe_cm, speed_cm_s, screen_direction_deg,
            static_before_sec, motion_sec).
        logger (ExperimentLogger): Event logger; gets a ``grating{trial_idx}_motion`` event.
        trial_idx (int): Global trial index, used in the motion event name.

    Returns:
        None
    """
    cycles_per_cm = 1 / (2 * condition["stripe_cm"])  # one cycle = one dark + one light stripe
    phase_step = condition["speed_cm_s"] * cycles_per_cm / FPS  # cycles moved per frame
    grating.sf = cycles_per_cm
    grating.ori = condition["screen_direction_deg"]
    grating.phase = 0
    for _ in range(seconds_to_frames(condition["static_before_sec"])):
        grating.draw()
        win.flip()

    logger.log(f"grating{trial_idx}_motion")
    for frame in range(seconds_to_frames(condition["motion_sec"])):
        # starts at phase 0 like the static pattern (no jump); same drift sign as loom_gratings.py
        grating.phase = -(frame * phase_step) % 1
        grating.draw()
        win.flip()


def present_loom_episode(win, disc, profile):
    """Draw one loom frame by frame: a black disc with the profile's radius.

    Args:
        win (visual.Window): Stimulus window.
        disc (visual.Circle): Black loom disc.
        profile (DataFrame): Loom profile with radius_cm per frame.

    Returns:
        None
    """
    for radius_cm in profile["radius_cm"].to_numpy():
        disc.radius = radius_cm
        disc.draw()
        win.flip()


def present_dimming_episode(win, dimming_image, ranks, profile):
    """Draw one dimming episode frame by frame: more pattern elements turn black each frame.

    Args:
        win (visual.Window): Stimulus window.
        dimming_image (visual.ImageStim): Full-screen dimming image.
        ranks (ndarray): Element darkening ranks of this condition.
        profile (DataFrame): Dimming profile with n_black_elements per frame.

    Returns:
        None
    """
    shown_n_black = None
    for n_black in profile["n_black_elements"].to_numpy():
        if n_black != shown_n_black:  # upload a new image only when more elements turn black
            dimming_image.image = build_dimming_frame(ranks, n_black)
            shown_n_black = n_black
        dimming_image.draw()
        win.flip()


def present_disc_episode(win, stimuli, condition):
    """Draw one episode of a loom or dimming train with the drawing function for its type.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        condition (dict): Loom or dimming condition.

    Returns:
        None
    """
    stimulus_name = condition["stimulus"]
    profile = stimuli["disc_profiles"][stimulus_name]
    if condition["type"] == "loom":
        present_loom_episode(win, stimuli["disc"], profile)
    else:
        present_dimming_episode(win, stimuli["dimming_image"], stimuli["dimming_ranks"][stimulus_name], profile)


def present_disc_train(win, stimuli, condition, logger, trial_idx):
    """Present the n_looms episodes of one loom or dimming trial, separated by blank gaps.

    Looms and dimming use this same function, so their timing is identical.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        condition (dict): Loom or dimming condition (type, n_looms, gap_sec).
        logger (ExperimentLogger): Event logger; gets one ``<type>{trial_idx}_onset{i}`` event per episode.
        trial_idx (int): Global trial index, used in the onset event names.

    Returns:
        None
    """
    for episode_idx in range(condition["n_looms"]):
        if episode_idx > 0:
            present_blank(win, condition["gap_sec"])
        logger.log(f"{condition['type']}{trial_idx}_onset{episode_idx}")
        present_disc_episode(win, stimuli, condition)


def present_stimulus(win, stimuli, condition, logger, trial_idx):
    """Present one stimulus condition with the drawing function for its type.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        condition (dict): Grating, loom or dimming condition.
        logger (ExperimentLogger): Event logger (motion and onset events).
        trial_idx (int): Global trial index.

    Returns:
        None

    Raises:
        ValueError: If the condition type is unknown.
    """
    if condition["type"] == "grating":
        present_grating(win, stimuli["grating"], condition, logger, trial_idx)
    elif condition["type"] in DISC_TYPES:
        present_disc_train(win, stimuli, condition, logger, trial_idx)
    else:
        raise ValueError(f"Unknown stimulus type: {condition['type']}")


class ExperimentLogger:
    """Event logs with experiment-wide and per-block timestamps, as in dots_loop_blocks.py.

    Every event is stored as ``B{block_num}_<event>`` in the experiment log (time since the
    experiment started) and, unless exp_only, in the block log (time since the block started).
    """

    def __init__(self):
        """Start the experiment clock with no block running yet."""
        self.exp_event_log = []
        self.block_event_log = []
        self.trial_sequence = []
        self.exp_clock = core.Clock()
        self.block_clock = core.Clock()
        self.block_num = -1  # becomes 0 when the first block starts

    def new_block(self):
        """Advance the block counter and restart the block clock.

        Returns:
            None
        """
        self.block_num += 1
        self.block_clock = core.Clock()

    def log(self, event, exp_only=False):
        """Log an event of the current block.

        Args:
            event (str): Event name without the ``B{n}_`` prefix.
            exp_only (bool): If True, only add it to the experiment log.

        Returns:
            None
        """
        event_name = f"B{self.block_num}_{event}"
        self.exp_event_log.append({"event": event_name, "timestamp": self.exp_clock.getTime()})
        if not exp_only:
            self.block_event_log.append({"event": event_name, "timestamp": self.block_clock.getTime()})


def begin_block(win, logger, pin_acq, inter_block_pause_sec):
    """End the running block (if any) with an inter-block pause, then start a new acquisition block.

    Args:
        win (visual.Window): Stimulus window.
        logger (ExperimentLogger): Event logger.
        pin_acq (object): Acquisition trigger pin.
        inter_block_pause_sec (float): Blank pause between blocks.

    Returns:
        None
    """
    if logger.block_num >= 0:
        logger.log("end")
        logger.log("interblock_pause", exp_only=True)
        print("inter_block_pause_sec")
        present_blank(win, inter_block_pause_sec)
    logger.new_block()
    pulse_pin(pin_acq)
    logger.log("start")
    print(f"Block {logger.block_num} started and trigger sent")


def run_trial(win, stimuli, pin_aux, logger, condition):
    """Run one trial: pre-stimulus pause, stimulus with aux pin high, post-stimulus pause.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        pin_aux (object): Aux trigger pin.
        logger (ExperimentLogger): Event logger; the trial is added to its trial_sequence.
        condition (dict): Condition to present, incl. its pre_pause_sec and post_pause_sec.

    Returns:
        None
    """
    trial_idx = len(logger.trial_sequence)  # global trial index, as in dots_loop_blocks.py
    stimulus_name = condition["stimulus"]
    logger.trial_sequence.append({"block": logger.block_num, "stimulus": stimulus_name})

    logger.log(f"prestim{trial_idx}_pause")
    present_blank(win, condition["pre_pause_sec"])

    pin_aux.write(1)
    print(stimulus_name, "started")
    logger.log(f"stim{trial_idx}_{stimulus_name}")
    present_stimulus(win, stimuli, condition, logger, trial_idx)
    pin_aux.write(0)

    logger.log(f"poststim{trial_idx}_pause")
    present_blank(win, condition["post_pause_sec"])


def run_experiment(win, stimuli, pins, logger, block_sequence, stimuli_params):
    """Run the blank pre-stim blocks followed by the stimulus blocks.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        pins (tuple): (acquisition pin, aux pin).
        logger (ExperimentLogger): Event logger.
        block_sequence (list of list of dict): Conditions of each stimulus block.
        stimuli_params (dict): Experiment parameters.

    Returns:
        None
    """
    pin_acq, pin_aux = pins
    inter_block_pause_sec = stimuli_params["inter_block_pause_sec"]

    for _ in range(int(stimuli_params["n_pre_stim_blocks"])):
        begin_block(win, logger, pin_acq, inter_block_pause_sec)
        print("Pre-stim resting (blank screen)")
        present_blank(win, stimuli_params["pre_stim_resting_sec"])

    for block_trials in block_sequence:
        begin_block(win, logger, pin_acq, inter_block_pause_sec)
        for condition in block_trials:
            run_trial(win, stimuli, pin_aux, logger, condition)


def save_run_outputs(meta_dir, file_prefix, logger, conditions):
    """Save the event logs, trial sequence and stimuli table as CSVs.

    Args:
        meta_dir (Path): Experiment metadata folder.
        file_prefix (str): ``{date}_f{fish_ID}`` prefix of every output file.
        logger (ExperimentLogger): Event logger after the run.
        conditions (list of dict): Stimulus conditions (one row each in the stimuli table).

    Returns:
        None
    """
    pd.DataFrame(logger.exp_event_log).to_csv(meta_dir / f"{file_prefix}_experiment_log.csv", index=False)
    pd.DataFrame(logger.block_event_log).to_csv(meta_dir / f"{file_prefix}_block_log.csv", index=False)
    df_trial_sequence = pd.DataFrame(logger.trial_sequence, columns=["block", "stimulus"])
    df_trial_sequence.to_csv(meta_dir / f"{file_prefix}_trial_sequence.csv", index=False)
    pd.DataFrame(conditions).to_csv(meta_dir / f"{file_prefix}_stimuli_table.csv", index=False)


def save_disc_profiles(meta_dir, file_prefix, disc_profiles, dimming_ranks):
    """Save the per-frame profile of every loom/dimming condition and each dimming pattern.

    Args:
        meta_dir (Path): Experiment metadata folder.
        file_prefix (str): ``{date}_f{fish_ID}`` prefix of every output file.
        disc_profiles (dict): Stimulus name -> profile DataFrame (exact luminance time course).
        dimming_ranks (dict): Stimulus name -> element ranks (which elements turn black, in order).

    Returns:
        None
    """
    for stimulus_name, profile in disc_profiles.items():
        profile.to_csv(meta_dir / f"{file_prefix}_{stimulus_name}_profile.csv", index=False)
    for stimulus_name, ranks in dimming_ranks.items():
        np.save(meta_dir / f"{file_prefix}_{stimulus_name}_pattern_ranks.npy", ranks)


def save_metadata(meta_dir, file_prefix, param_dicts):
    """Save parameter dicts as one parameter/value metadata CSV (rewritten on each call).

    Args:
        meta_dir (Path): Experiment metadata folder.
        file_prefix (str): ``{date}_f{fish_ID}`` prefix of every output file.
        param_dicts (list of dict): Dicts whose items become the CSV rows, in order.

    Returns:
        None
    """
    all_data = [item for params in param_dicts for item in params.items()]
    exp_metadata = pd.DataFrame(all_data, columns=["parameter", "value"])
    exp_metadata.to_csv(meta_dir / f"{file_prefix}_metadata.csv", index=False)


def collect_parameters():
    """Ask for metadata and parameters, then build the conditions and the block sequence.

    Returns:
        tuple: (metadata, stimuli_params, functional_params, conditions, block_sequence,
            disc_profiles, dimming_ranks).
    """
    metadata = default_metadata()
    functional_params = default_functional_params()
    stimuli_params = default_stimuli_params()

    show_dialog(metadata, "Metadata")
    if isinstance(metadata["fish_orientation"], list):  # dropdown left at its default value
        metadata["fish_orientation"] = metadata["fish_orientation"][0]
    flip_coordinates = metadata["fish_orientation"].lower() == FLIPPED_FISH_ORIENTATION
    show_dialog(functional_params, "Functional Scanning Parameters")
    show_dialog(stimuli_params, "Experiment Parameters")

    metadata["fish_age_dpf"] = compute_age_dpf(metadata["fish_birth"])
    metadata["stimulus_script"] = Path(__file__).name

    loom_conditions = build_loom_conditions(stimuli_params)
    conditions = (build_grating_conditions(stimuli_params, flip_coordinates) + loom_conditions
                  + build_dimming_conditions(loom_conditions, stimuli_params))
    block_sequence = build_block_sequence(conditions, int(stimuli_params["n_rep_stim"]),
                                          int(stimuli_params["n_trials_per_block"]))
    stimuli_params["stimulus_block_duration_sec"] = compute_block_duration_sec(block_sequence[0])
    if stimuli_params["match_pre_stim_to_block"]:
        stimuli_params["pre_stim_resting_sec"] = stimuli_params["stimulus_block_duration_sec"]
    disc_profiles, dimming_ranks = build_disc_profiles(conditions)  # computed now so trials have no setup delay
    return metadata, stimuli_params, functional_params, conditions, block_sequence, disc_profiles, dimming_ranks


def collect_post_run_metadata(metadata):
    """Ask for the fish status and anatomy-stack parameters after the run.

    Args:
        metadata (dict): Experiment metadata; updated in place with ``fish_died`` and dialog edits.

    Returns:
        dict: Anatomy parameters.
    """
    metadata["fish_died"] = False
    anatomy_params = default_anatomy_params()
    show_dialog(metadata, "Metadata")
    show_dialog(anatomy_params, "Anatomy")
    return anatomy_params


def main():
    """Run the full experiment: dialogs, folder tree, blocks, and saving of logs and metadata.

    Returns:
        None
    """
    (metadata, stimuli_params, functional_params, conditions, block_sequence,
     disc_profiles, dimming_ranks) = collect_parameters()
    print_block_summary(stimuli_params, functional_params, block_sequence)

    data_path = DRY_RUN_DATA_PATH if DRY_RUN else DATA_PATH
    data_root = data_path / str(metadata["experimenter"]) / MICROSCOPY_FOLDER
    paths = init_experiment_tree(data_root, str(metadata["fish_ID"]))
    meta_dir = paths["raw_2p_metadata"]  # where we save logs and parameter CSVs

    win = create_window()
    stimuli = create_stimuli(win, disc_profiles, dimming_ranks)
    pin_acq, pin_aux = connect_trigger_pins()
    logger = ExperimentLogger()

    try:
        run_experiment(win, stimuli, (pin_acq, pin_aux), logger, block_sequence, stimuli_params)
    except KeyboardInterrupt:
        print("\nManual interruption detected. Finalizing and saving logs...")
    finally:
        pin_aux.write(0)  # in case the run was interrupted during a stimulus
        if logger.block_num >= 0:
            logger.log("end")
        print("Experiment ended")
        metadata["n_dropped_frames"] = win.nDroppedFrames  # > 0 means some frames came late
        print(f"Dropped frames: {metadata['n_dropped_frames']}")
        win.close()

        file_prefix = f"{datetime.datetime.now().strftime(FILE_DATE_FORMAT)}_f{metadata['fish_ID']}"
        save_run_outputs(meta_dir, file_prefix, logger, conditions)
        save_disc_profiles(meta_dir, file_prefix, disc_profiles, dimming_ranks)
        save_metadata(meta_dir, file_prefix, [metadata, stimuli_params, functional_params])

        anatomy_params = collect_post_run_metadata(metadata)
        save_metadata(meta_dir, file_prefix, [metadata, stimuli_params, functional_params, anatomy_params])


if __name__ == "__main__":
    main()

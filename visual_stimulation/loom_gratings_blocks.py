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
- The aux pin is high while a stimulus is on screen.
- Saves experiment log, block log, trial sequence, stimuli table and metadata CSVs into
  01_raw/2p/metadata.

Based on dots_loop_blocks.py and loom_gratings.py (Matilde Perrino).
Created: 2026-10-07
"""

import datetime
import math
import random
from pathlib import Path

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
BACKGROUND_COLOR = "red"
STIMULUS_COLOR = "black"

# ===== Stimulus drawing =====
SCREEN_HEIGHT_CM = MONITOR_WIDTH_CM * PIXELS_MONITOR[1] / PIXELS_MONITOR[0]
# The grating is a square as wide as the screen diagonal, so it covers the screen at any orientation
GRATING_SIZE_CM = math.hypot(MONITOR_WIDTH_CM, SCREEN_HEIGHT_CM)
GRATING_TEXTURE = "sin"
LOOM_POS_CM = (0, 0)
LOOM_CIRCLE_EDGES = 128  # more edges than PsychoPy's default 32 so the large loom looks round
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
        "pre_stim_pause_sec": 12.5,          # Pause before stimulus
        "post_stim_pause_sec": 12.5,         # Pause after stimulus
        "inter_block_pause_sec": 20.0,       # Pause between acquisition blocks
        "n_trials_per_block": 6,             # Trials per block (multiple of the number of conditions)
        "n_rep_stim": 6,                     # Repetitions per condition over the whole experiment
        "grating_directions_deg": "0,180",   # One grating condition per direction (empty = no gratings)
        "grating_sec": 30.0,
        "stripe_cm": 0.5,                    # Width of one stripe (a full cycle is two stripes)
        "grating_speed_cm_s": 1.0,
        "loom_durations_sec": "3",           # One loom condition per duration (empty = no looms)
        "loom_start_radius_cm": 0.5,
        "loom_end_radius_cm": 3.5
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
    grating_conditions = []
    for direction_deg in parse_number_list(stimuli_params["grating_directions_deg"]):
        grating_conditions.append({
            "stimulus": f"grating_{direction_deg:g}deg",
            "type": "grating",
            "duration_sec": float(stimuli_params["grating_sec"]),
            "n_frames": seconds_to_frames(stimuli_params["grating_sec"]),
            "direction_deg": direction_deg,
            "screen_direction_deg": (direction_deg + direction_offset_deg) % 360,
            "stripe_cm": float(stimuli_params["stripe_cm"]),
            "speed_cm_s": float(stimuli_params["grating_speed_cm_s"]),
        })
    return grating_conditions


def build_loom_conditions(stimuli_params):
    """Create one looming-disc condition per requested loom duration.

    Args:
        stimuli_params (dict): Experiment parameters (loom_* entries).

    Returns:
        list of dict: Loom conditions.
    """
    loom_conditions = []
    for loom_sec in parse_number_list(stimuli_params["loom_durations_sec"]):
        loom_conditions.append({
            "stimulus": f"loom_{loom_sec:g}s",
            "type": "loom",
            "duration_sec": loom_sec,
            "n_frames": seconds_to_frames(loom_sec),
            "start_radius_cm": float(stimuli_params["loom_start_radius_cm"]),
            "end_radius_cm": float(stimuli_params["loom_end_radius_cm"]),
        })
    return loom_conditions


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


def compute_block_duration_sec(block_trials, stimuli_params):
    """Compute how long one stimulus block lasts (pre-pause + stimulus + post-pause per trial).

    Args:
        block_trials (list of dict): Conditions presented in the block.
        stimuli_params (dict): Experiment parameters (pause durations).

    Returns:
        float: Block duration in seconds, from whole frame counts.
    """
    pause_frames = (seconds_to_frames(stimuli_params["pre_stim_pause_sec"])
                    + seconds_to_frames(stimuli_params["post_stim_pause_sec"]))
    block_frames = sum(pause_frames + condition["n_frames"] for condition in block_trials)
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
        visual.Window: Stimulus window with a BACKGROUND_COLOR background.
    """
    monitor = monitors.Monitor(MONITOR_NAME, width=MONITOR_WIDTH_CM)
    monitor.setSizePix(PIXELS_MONITOR)
    monitor.setDistance(MONITOR_DISTANCE_CM)
    win = visual.Window(size=PIXELS_MONITOR, color=BACKGROUND_COLOR, units="pix", monitor=monitor,
                        screen=DRY_RUN_SCREEN if DRY_RUN else STIM_SCREEN, fullscr=not DRY_RUN)
    return win


def create_stimuli(win):
    """Create the reusable grating and looming-disc stimuli.

    Args:
        win (visual.Window): Stimulus window.

    Returns:
        dict: ``{"grating": GratingStim, "loom": Circle}``, keyed by condition type.
    """
    grating = visual.GratingStim(win=win, tex=GRATING_TEXTURE, units="cm", size=GRATING_SIZE_CM)
    loom_circle = visual.Circle(win=win, units="cm", pos=LOOM_POS_CM, edges=LOOM_CIRCLE_EDGES,
                                fillColor=STIMULUS_COLOR, lineColor=STIMULUS_COLOR)
    stimuli = {"grating": grating, "loom": loom_circle}
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


def present_grating(win, grating, condition):
    """Draw a drifting grating frame by frame for the condition's duration.

    Args:
        win (visual.Window): Stimulus window.
        grating (visual.GratingStim): Grating stimulus.
        condition (dict): Grating condition (stripe_cm, speed_cm_s, screen_direction_deg, n_frames).

    Returns:
        None
    """
    cycles_per_cm = 1 / (2 * condition["stripe_cm"])  # one cycle = one dark + one light stripe
    phase_step = condition["speed_cm_s"] * cycles_per_cm / FPS  # cycles moved per frame
    grating.sf = cycles_per_cm
    grating.ori = condition["screen_direction_deg"]
    for frame in range(condition["n_frames"]):
        grating.phase = -(frame * phase_step) % 1  # same drift sign as loom_gratings.py; wrap to [0, 1)
        grating.draw()
        win.flip()


def present_loom(win, loom_circle, condition):
    """Draw a disc whose radius grows linearly from start to end radius.

    Args:
        win (visual.Window): Stimulus window.
        loom_circle (visual.Circle): Looming disc.
        condition (dict): Loom condition (start_radius_cm, end_radius_cm, n_frames).

    Returns:
        None
    """
    n_frames = condition["n_frames"]
    # cm per frame, chosen so the last frame is drawn exactly at the end radius
    radius_step = (condition["end_radius_cm"] - condition["start_radius_cm"]) / max(n_frames - 1, 1)
    for frame in range(n_frames):
        loom_circle.radius = condition["start_radius_cm"] + frame * radius_step
        loom_circle.draw()
        win.flip()


def present_stimulus(win, stimuli, condition):
    """Present one stimulus condition with the drawing function for its type.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        condition (dict): Grating or loom condition.

    Returns:
        None

    Raises:
        ValueError: If the condition type is unknown.
    """
    if condition["type"] == "grating":
        present_grating(win, stimuli["grating"], condition)
    elif condition["type"] == "loom":
        present_loom(win, stimuli["loom"], condition)
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


def run_trial(win, stimuli, pin_aux, logger, condition, stimuli_params):
    """Run one trial: pre-stimulus pause, stimulus with aux pin high, post-stimulus pause.

    Args:
        win (visual.Window): Stimulus window.
        stimuli (dict): Stimuli from ``create_stimuli``.
        pin_aux (object): Aux trigger pin.
        logger (ExperimentLogger): Event logger; the trial is added to its trial_sequence.
        condition (dict): Condition to present.
        stimuli_params (dict): Experiment parameters (pause durations).

    Returns:
        None
    """
    trial_idx = len(logger.trial_sequence)  # global trial index, as in dots_loop_blocks.py
    stimulus_name = condition["stimulus"]
    logger.trial_sequence.append({"block": logger.block_num, "stimulus": stimulus_name})

    logger.log(f"prestim{trial_idx}_pause")
    present_blank(win, stimuli_params["pre_stim_pause_sec"])

    pin_aux.write(1)
    print(stimulus_name, "started")
    logger.log(f"stim{trial_idx}_{stimulus_name}")
    present_stimulus(win, stimuli, condition)
    pin_aux.write(0)

    logger.log(f"poststim{trial_idx}_pause")
    present_blank(win, stimuli_params["post_stim_pause_sec"])


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
            run_trial(win, stimuli, pin_aux, logger, condition, stimuli_params)


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
        tuple: (metadata, stimuli_params, functional_params, conditions, block_sequence).
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

    conditions = build_grating_conditions(stimuli_params, flip_coordinates) + build_loom_conditions(stimuli_params)
    block_sequence = build_block_sequence(conditions, int(stimuli_params["n_rep_stim"]),
                                          int(stimuli_params["n_trials_per_block"]))
    stimuli_params["stimulus_block_duration_sec"] = compute_block_duration_sec(block_sequence[0], stimuli_params)
    if stimuli_params["match_pre_stim_to_block"]:
        stimuli_params["pre_stim_resting_sec"] = stimuli_params["stimulus_block_duration_sec"]
    return metadata, stimuli_params, functional_params, conditions, block_sequence


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
    metadata, stimuli_params, functional_params, conditions, block_sequence = collect_parameters()
    print_block_summary(stimuli_params, functional_params, block_sequence)

    data_path = DRY_RUN_DATA_PATH if DRY_RUN else DATA_PATH
    data_root = data_path / str(metadata["experimenter"]) / MICROSCOPY_FOLDER
    paths = init_experiment_tree(data_root, str(metadata["fish_ID"]))
    meta_dir = paths["raw_2p_metadata"]  # where we save logs and parameter CSVs

    win = create_window()
    stimuli = create_stimuli(win)
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
        win.close()

        file_prefix = f"{datetime.datetime.now().strftime(FILE_DATE_FORMAT)}_f{metadata['fish_ID']}"
        save_run_outputs(meta_dir, file_prefix, logger, conditions)
        save_metadata(meta_dir, file_prefix, [metadata, stimuli_params, functional_params])

        anatomy_params = collect_post_run_metadata(metadata)
        save_metadata(meta_dir, file_prefix, [metadata, stimuli_params, functional_params, anatomy_params])


if __name__ == "__main__":
    main()

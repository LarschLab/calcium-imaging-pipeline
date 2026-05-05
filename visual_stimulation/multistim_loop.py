# -*- coding: utf-8 -*-
"""
Zebrafish 2p experiment: dots mvoing on a screen + folder structure bootstrap.

- Initializes a standard folder tree under:
  Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data\<experimenter>\<fish_ID>\...

- Runs PsychoPy stimulus presentation and logs events.
- Saves logs and all parameter CSVs into 01_raw/2p/metadata.

@author: Matilde Perrino and Lukas Breitzler
Created: 2025-02-17
Updated: 2026-03-23
"""


# Imports and Setup
from psychopy import visual, core, event, monitors, tools, gui, data, prefs
import tkinter as tk
from tkinter import filedialog
from pyfirmata import Arduino
import pandas as pd
import datetime
from pathlib import Path
from utils import init_experiment_tree
import re
import random

prefs.hardware['videoLib'] = ['ffpyplayer']
# ===== GUI: Select stimuli folder =====
root_tk = tk.Tk()
root_tk.withdraw()
stimuli_path_str = filedialog.askdirectory(title="Select the folder containing the stimulus CSV/MP4 files")
if not stimuli_path_str:
    core.quit()
stimuli_path = Path(stimuli_path_str)

# ===== Monitor & window settings =====
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('DLC_Projector', width=15.2)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)
monitor.setDistance(1)
FPS = 60
RANDOMIZE_STIMULI = False  # set to False to keep sorted order


# ===== Base data root =====
data_path = Path(r'Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data')

# ===== Metadata & params =====
metadata = {
    "experiment_name": "social_buffering",
    "experimenter": "Lukas",
    "experiment_date": data.getDateStr(format="%Y-%m-%d-%H%M"),
    "fish_ID": "L732_f02",
    "fish_birth": "2026-04-07",
    "fish_age_dpf": 15,
    "genotype": "huc:H2B-GCamp6s",
    "size": "small",
    "time_embedding": None,
    "fish_orientation": ["bottom-left", "top-right"],
    "respond_to_omr": True,
    "respond_to_vibrations": True,
    "respond_to_bouts": True,
    "embedding_comments": None,
    "projector_LED_current": 40,
    "general_comments": None
}

stimuli_params = {
    "pre_stim_resting_sec": 0,
    "pre_stim_pause_sec": 0,
    "post_stim_pause_sec": 10,
    "inter_block_pause_sec": 5,
    "n_trials_per_block": 30,
    "n_rep_stim": 1,
    "max_n_dots": 5
}

functional_params = {
    'mode': 'resonant',
    'n_frames': 5, # or 5
    'n_slices': 2, # or 3
    'n_volumes': 180, # or 120
    'step_size': 10,
    'framerate': 3,
    'AOM_mW': 22,
    'ETL_start': -20,
    'pump_speed': 0,
    'volume_flyback': 0,
    'frame_flyback': 0,
    'motion_correction': False
}

# ===== Dialogs =====
dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
if not dlg.OK:
    core.quit()

if isinstance(metadata['fish_orientation'], list):
    metadata['fish_orientation'] = metadata['fish_orientation'][0]

flip_coordinates = metadata["fish_orientation"].lower() == "bottom-left"

dlg = gui.DlgFromDict(functional_params, title="Functional Scanning Parameters", sortKeys=False)
if not dlg.OK:
    core.quit()

dlg = gui.DlgFromDict(stimuli_params, title="Experiment Parameters", sortKeys=False)
if not dlg.OK:
    core.quit()

# ===== Derived values =====
fish_birth = datetime.datetime.strptime(metadata['fish_birth'], "%Y-%m-%d")
today = datetime.datetime.today()
metadata['fish_age_dpf'] = (today - fish_birth).days
metadata['path_to_stimuli'] = str(stimuli_path)

# ===== Folder structure =====
data_root = data_path / str(metadata["experimenter"])
exp_name = str(metadata["fish_ID"])
paths = init_experiment_tree(data_root, exp_name)
meta_dir = paths["raw_2p_metadata"]

# ===== Load stimuli (CSV + MP4) =====
all_stimuli_files_sorted = []
for file_path in stimuli_path.glob("*"):
    if file_path.suffix.lower() in [".csv", ".mp4"]:
        all_stimuli_files_sorted.append(file_path)

if RANDOMIZE_STIMULI:
    random.shuffle(all_stimuli_files_sorted)
else:
    all_stimuli_files_sorted.sort(
        key=lambda x: int(re.search(r'\d+', x.stem).group())
        if re.search(r'\d+', x.stem) else float('inf')
    )

print(all_stimuli_files_sorted)

stimuli = {}
for file_path in all_stimuli_files_sorted:
    if file_path.suffix.lower() == ".csv":
        stimuli[file_path] = pd.read_csv(file_path)
    else:
        stimuli[file_path] = None

conditions = [{"stimulus": key} for key in stimuli.keys()]
trials = data.TrialHandler(
    nReps=stimuli_params["n_rep_stim"],
    method="sequential",
    trialList=conditions,
    name="trials"
)

trial_sequence = []

# ===== PsychoPy window =====
win = visual.Window(size=PIXELS_MONITOR, color="red", units="pix", monitor=monitor, screen=1, fullscr=True)

dots = [
    visual.Circle(win=win, radius=0.2, fillColor="black", pos=[0, 0], units="cm")
    for _ in range(stimuli_params["max_n_dots"])
]

# ===== Arduino =====
board = Arduino("COM3")
pin_acq = board.get_pin('d:11:o')
pin_aux = board.get_pin('d:13:o')
pin_acq.write(0)
pin_aux.write(0)

# ===== Logging =====
exp_event_log = []
block_event_log = []
block_num = 0
exp_clock = core.Clock()
block_clock = core.Clock()

# ===== Start =====
pin_acq.write(1); pin_acq.write(0)
exp_event_log.append({'event': f'B{block_num}_start', 'timestamp': exp_clock.getTime()})
block_event_log.append({'event': f'B{block_num}_start', 'timestamp': block_clock.getTime()})
print("Experiment started")

try:
    # Resting
    for _ in range(int(FPS * stimuli_params['pre_stim_resting_sec'])):
        win.flip()

    for idx, trial in enumerate(trials):

        stimulus_key = trial["stimulus"]
        trial_sequence.append(stimulus_key)

        is_csv = stimulus_key.suffix.lower() == ".csv"

        # Pre-stim pause
        for _ in range(int(FPS * stimuli_params['pre_stim_pause_sec'])):
            win.flip()

        # Trigger acquisition
        pin_acq.write(1); pin_acq.write(0)

        # Stimulus start
        pin_aux.write(1); pin_aux.write(0)
        print(stimulus_key, 'started')

        if is_csv:
            df = stimuli[stimulus_key]
            n_dots = len(df.columns) // 3
            n_frames_trial = len(df)

            for frame in range(n_frames_trial):
                for dot_idx in range(n_dots):
                    x = df[f'dot{dot_idx}_x'][frame]
                    y = df[f'dot{dot_idx}_y'][frame]
                    radius = df[f'dot{dot_idx}_radius'][frame]

                    if radius == 0.1:
                        pin_aux.write(1)
                        pin_aux.write(0)

                    if flip_coordinates:
                        x, y = -x, -y

                    dots[dot_idx].radius = radius
                    dots[dot_idx].pos = (x, y)
                    dots[dot_idx].draw()

                win.flip()

        else:
            movie = visual.MovieStim(
                win,
                filename=str(stimulus_key),
                units="pix",
                loop=False
            )

            print("Video duration (s):", movie.duration)

            while not movie.isFinished:
                movie.draw()
                win.flip()

        pin_aux.write(1); pin_aux.write(0)

        # Post-stim pause
        for _ in range(int(FPS * stimuli_params['post_stim_pause_sec'])):
            win.flip()

except KeyboardInterrupt:
    print("Interrupted")

finally:
    # End experiment
    exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
    block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})
    print("Experiment ended")
    win.close()  # Close the PsychoPy window

    # Save logs and trial sequence
    current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")

    df_experiment_log = pd.DataFrame(exp_event_log)
    exp_log_filename = f"{current_date}_f{metadata['fish_ID']}_experiment_log.csv"
    df_experiment_log.to_csv(meta_dir / exp_log_filename, index=False)

    df_block_log = pd.DataFrame(block_event_log)
    block_log_filename = f"{current_date}_f{metadata['fish_ID']}_block_log.csv"
    df_block_log.to_csv(meta_dir / block_log_filename, index=False)

    df_trial_sequence = pd.DataFrame(trial_sequence, columns=["stimulus"])
    trial_sequence_filename = f"{current_date}_f{metadata['fish_ID']}_trial_sequence.csv"
    df_trial_sequence.to_csv(meta_dir / trial_sequence_filename, index=False)

    # First metadata dump (metadata + stimuli + functional)
    metadata_list = list(metadata.items())
    stimuli_params_list = list(stimuli_params.items())
    functional_list = list(functional_params.items())
    all_data = metadata_list + stimuli_params_list + functional_list
    exp_metadata = pd.DataFrame(all_data, columns=["parameter", "value"])

    metadata_filename = f"{current_date}_f{metadata['fish_ID']}_metadata.csv"
    exp_metadata.to_csv(meta_dir / metadata_filename, index=False)

    # Post-run dialogs for anatomy + fish status (kept as in your script)
    metadata['fish_died'] = False
    anatomy_params = {'frames_per_slice_anatomy': 150,
                      'step_size_um_anatomy' : 2,
                      'wavelenght_anatomy' : 850,
                      'AOM%_anatomy' : 57
    }
    dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
    if not dlg.OK:
        core.quit()

    dlg = gui.DlgFromDict(anatomy_params, title="Anatomy", sortKeys=False)
    if not dlg.OK:
        core.quit()

    # Overwrite/update metadata CSV with anatomy appended
    metadata_list = list(metadata.items())
    stimuli_params_list = list(stimuli_params.items())
    functional_list = list(functional_params.items())
    anatomy_list = list(anatomy_params.items())
    all_data = metadata_list + stimuli_params_list + functional_list + anatomy_list
    exp_metadata = pd.DataFrame(all_data, columns=["parameter", "value"])
    exp_metadata.to_csv(meta_dir / metadata_filename, index=False)
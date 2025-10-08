# -*- coding: utf-8 -*-
"""
Description:
    This script displays visual stimuli (moving dots) in bouts for an experiment on juvenile zebrafish (17–20 dpf).
    Zebrafish see moving dots while we record calcium activity using 2-photon imaging.

    Workflow:
      1) Blank screen (spontaneous activity)
      2) Stimulus cycles (pause → stimulus from CSV → pause)

    Events are logged; Arduino triggers for synchronization.

@author: Matilde Perrino
Created on: 2025-02-17
"""

# Imports and Setup
from psychopy import visual, core, event, monitors, tools, gui, data
import tkinter as tk
from tkinter import filedialog
from pyfirmata import Arduino
import pandas as pd
import datetime
from pathlib import Path
from utils import init_experiment_tree  # <-- folder tree helper

# ===== GUI: Select stimuli folder =====
root = tk.Tk()
root.withdraw()
stimuli_path_str = filedialog.askdirectory(title="Select the folder containing the stimulus CSV files")
if not stimuli_path_str:
    core.quit()
stimuli_path = Path(stimuli_path_str)

# ===== Monitor and window settings =====
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('DLC_Projector', width=15.2)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter
monitor.setDistance(1)
FPS = 60

# ===== Base data root (07_Data) =====
# Will create: Z:\...\07_Data\<experimenter>\<fish_ID>\...
data_path = Path(r'Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data')

# ===== Metadata & params =====
metadata = {
    "experiment_name": "groupsize_thalamus_exp02",
    "experimenter": "Matilde",
    "experiment_date": data.getDateStr(format="%Y-%m-%d-%H%M"),
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
    "projector_power": 40,
    "general_comments": None
}

stimuli_params = {
    "pre_stim_resting_sec": 813.666667,  # ~12.91 min blank
    "pre_stim_pause_sec": 12.5,
    "post_stim_pause_sec": 12.5,
    "inter_block_pause_sec": 20,
    "n_trials_per_block": 16,
    "n_rep_stim": 4,
    "dot_radius_cm": 0.2,
    "max_n_dots": 6
}

functional_params = {
    'mode': 'linear',
    'n_frames': 3,
    'n_slices': 5,
    'n_volumes': 1610,  # 8100
    'step_size': 10,
    'framerate': 2,
    'AOM_mW': 32,
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

# Derived values
fish_birth = datetime.datetime.strptime(metadata['fish_birth'], "%Y-%m-%d")
today = datetime.datetime.today()
metadata['fish_age_dpf'] = (today - fish_birth).days
metadata['path_to_stimuli'] = str(stimuli_path)

# ===== Build experiment folder structure (utils) =====
data_root = data_path / str(metadata["experimenter"])
exp_name = str(metadata["fish_ID"])  # or f"L500_f{int(metadata['fish_ID']):02d}"
paths = init_experiment_tree(data_root, exp_name)
meta_dir = paths["raw_2p_metadata"]  # all logs/CSV parameters go here

# ===== Load stimuli CSVs =====
stimuli = {}
for file_path in stimuli_path.glob("*.csv"):
    df = pd.read_csv(file_path)
    key = file_path.stem.split("_")[0]
    stimuli[key] = df

conditions = [{"stimulus": key} for key in stimuli.keys()]
trials = data.TrialHandler(nReps=stimuli_params["n_rep_stim"], method="random",
                           trialList=conditions, name="trials")
trial_sequence = []

# ===== PsychoPy window =====
win = visual.Window(size=PIXELS_MONITOR, color="red", units="pix", monitor=monitor, screen=1, fullscr=True)
dots = [
    visual.Circle(win=win, radius=stimuli_params["dot_radius_cm"],
                  fillColor="black", pos=[0, 0], units="cm")
    for _ in range(stimuli_params["max_n_dots"])
]

# ===== Arduino connection and trigger pins =====
board = Arduino("COM3")
ACQ_TRIGGER_PIN = 11
AUX_TRIGGER_PIN = 13
pin_acq = board.get_pin(f'd:{ACQ_TRIGGER_PIN}:o')
pin_aux = board.get_pin(f'd:{AUX_TRIGGER_PIN}:o')
pin_acq.write(0)
pin_aux.write(0)

# ===== Logging / clocks =====
exp_event_log = []
block_event_log = []
block_num = 0
exp_clock = core.Clock()
block_clock = core.Clock()

try:
    # Start experiment: trigger recording block and log event
    pin_acq.write(1); pin_acq.write(0)
    exp_event_log.append({'event': f'B{block_num}_start', 'timestamp': exp_clock.getTime()})
    block_event_log.append({'event': f'B{block_num}_start', 'timestamp': block_clock.getTime()})
    print("Experiment started and trigger sent")

    # Spontaneous activity (blank screen)
    for _ in range(int(round(FPS * float(stimuli_params['pre_stim_resting_sec']), 1))):
        win.flip()

    for idx, trial in enumerate(trials):
        stimulus_key = trial["stimulus"]
        df = stimuli[stimulus_key]
        n_frames_trial = len(df)
        n_dots = len(df.columns) // 3
        trial_sequence.append(stimulus_key)

        # If the block is complete, finish the block, pause, and start a new one
        if idx % stimuli_params["n_trials_per_block"] == 0:
            exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
            block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})

            # optional inter-block pause for acquisition blocks
            exp_event_log.append({'event': f'B{block_num}_interblock_pause', 'timestamp': exp_clock.getTime()})
            for _ in range(int(FPS * stimuli_params['inter_block_pause_sec'])):
                win.flip()

            block_num += 1
            block_clock = core.Clock()
            pin_acq.write(1); pin_acq.write(0)
            exp_event_log.append({'event': f'B{block_num}_start', 'timestamp': exp_clock.getTime()})
            block_event_log.append({'event': f'B{block_num}_start', 'timestamp': block_clock.getTime()})

        # Pre-stimulus pause
        exp_event_log.append({'event': f'B{block_num}_prestim{idx}_pause', 'timestamp': exp_clock.getTime()})
        block_event_log.append({'event': f'B{block_num}_prestim{idx}_pause', 'timestamp': block_clock.getTime()})
        for _ in range(int(round(FPS * float(stimuli_params['pre_stim_pause_sec']), 1))):
            win.flip()

        # Stimulus presentation
        pin_aux.write(1)
        print(stimulus_key, 'started')
        exp_event_log.append({'event': f'B{block_num}_stim{idx}_{stimulus_key}', 'timestamp': exp_clock.getTime()})
        block_event_log.append({'event': f'B{block_num}_stim{idx}_{stimulus_key}', 'timestamp': block_clock.getTime()})

        for frame in range(n_frames_trial):
            for dot_idx in range(n_dots):
                x = df[f'dot{dot_idx}_x'][frame]
                y = df[f'dot{dot_idx}_y'][frame]
                radius = df[f'dot{dot_idx}_radius'][frame]
                if flip_coordinates:
                    x, y = -x, -y
                dots[dot_idx].radius = radius
                dots[dot_idx].pos = (x, y)
                dots[dot_idx].draw()
            win.flip()
        pin_aux.write(0)

        # Post-stimulus pause
        exp_event_log.append({'event': f'B{block_num}_poststim{idx}_pause', 'timestamp': exp_clock.getTime()})
        block_event_log.append({'event': f'B{block_num}_poststim{idx}_pause', 'timestamp': block_clock.getTime()})
        for _ in range(int(round(FPS * float(stimuli_params['post_stim_pause_sec']), 1))):
            win.flip()

except KeyboardInterrupt:
    print("\nManual interruption detected. Finalizing and saving logs...")

finally:
    # End experiment
    exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
    block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})
    print("Experiment ended")
    win.close()

    # Save logs and trial sequence (to 01_raw/2p/metadata)
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

    # Post-run dialogs for anatomy + fish status
    metadata['fish_died'] = False
    anatomy_params = {
        'frames_per_slice_anatomy': 90,
        'step_size_um_anatomy': 2,
        'wavelenght_anatomy': 850,
        'AOM_anatomy': 57
    }
    dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
    if not dlg.OK:
        core.quit()
    dlg = gui.DlgFromDict(anatomy_params, title="Anatomy", sortKeys=False)
    if not dlg.OK:
        core.quit()

    # Overwrite/update metadata CSV with anatomy appended (same path)
    metadata_list = list(metadata.items())
    stimuli_params_list = list(stimuli_params.items())
    functional_list = list(functional_params.items())
    anatomy_list = list(anatomy_params.items())
    all_data = metadata_list + stimuli_params_list + functional_list + anatomy_list
    exp_metadata = pd.DataFrame(all_data, columns=["parameter", "value"])
    exp_metadata.to_csv(meta_dir / metadata_filename, index=False)

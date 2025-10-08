# -*- coding: utf-8 -*-
"""
Zebrafish 2p experiment: dots mvoing on a screen + folder structure bootstrap.

- Initializes a standard folder tree under:
  Z:\FAC\FBM\CIG\jlarsch\default\D2c\07_Data\<experimenter>\<fish_ID>\...

- Runs PsychoPy stimulus presentation and logs events.
- Saves logs and all parameter CSVs into 01_raw/2p/metadata.

@author: Matilde Perrino
Created: 2025-02-17
Updated: 2025-10-07
"""

# Imports and Setup
from psychopy import visual, core, event, monitors, tools, gui, data
import tkinter as tk
from tkinter import filedialog
from pyfirmata import Arduino
import pandas as pd
import datetime
from pathlib import Path
from utils import init_experiment_tree

# ===== GUI: Select stimuli folder =====
root_tk = tk.Tk()
root_tk.withdraw() # Hide the small Tkinter window
stimuli_path_str = filedialog.askdirectory(title="Select the folder containing the stimulus CSV files")
if not stimuli_path_str:
    core.quit()
stimuli_path = Path(stimuli_path_str)


# ===== Monitor & window settings =====
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('DLC_Projector', width=15.2)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter
monitor.setDistance(1)
FPS = 60

# ===== Base data root =====
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
    "projector_LED_current": 40,
    "general_comments": None
}

stimuli_params = {
    "pre_stim_resting_sec": 813.666667,#813.666667, # around 12.91 minutes blank screen
    "pre_stim_pause_sec": 12.5,           # Pause before stimulus
    "post_stim_pause_sec": 12.5,          # Pause after stimulus
    "inter_block_pause_sec": 20,        # Pause between acquisition blocks
    "n_trials_per_block": 16,           # Trials per block
    "n_rep_stim": 4,                   # Repetitions per stimulus
    "max_n_dots": 6
}

functional_params = {'mode': 'resonant',
                     'n_frames': 3,
                     'n_slices' : 5,
                     'n_volumes' : 1610, #8100
                     'step_size' : 10,
                     'framerate' :2,
                     'AOM_mW' : 32,
                     'ETL_start' : -20,
                     'pump_speed': 0,
                     'volume_flyback' : 0,
                     'frame_flyback' : 0,
                     'motion_correction' : False
}


# ===== Dialogs =====
dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
if not dlg.OK:
    core.quit()

# Extract the selected value from dropdown
if isinstance(metadata['fish_orientation'], list):
    metadata['fish_orientation'] = metadata['fish_orientation'][0]

# Flip coordinates if fish is facing bottom-left
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

# ===== Build experiment folder structure =====
data_root = data_path / str(metadata["experimenter"])
exp_name = str(metadata["fish_ID"])  # if you want L500_f01: exp_name = f"L500_f{int(metadata['fish_ID']):02d}"
paths = init_experiment_tree(data_root, exp_name)
meta_dir = paths["raw_2p_metadata"]       # where we save logs and parameter CSVs

# ===== Load stimuli CSVs =====
stimuli = {}
for file_path in stimuli_path.glob("*.csv"):
    df = pd.read_csv(file_path)
    key = file_path.stem.split("_")[0]
    stimuli[key] = df

# Assume all CSVs have the same number of frames
conditions = [{"stimulus": key} for key in stimuli.keys()]
trials = data.TrialHandler(nReps=stimuli_params["n_rep_stim"], method="random", trialList=conditions, name="trials")
trial_sequence = []

# ===== PsychoPy window =====
win = visual.Window(size=PIXELS_MONITOR, color="red", units="pix", monitor=monitor, screen=1, fullscr=True)


dots = [visual.Circle(win=win, radius=0.2, fillColor="black", pos=[0, 0], units="cm")
        for _ in range(stimuli_params["max_n_dots"])]

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

# ===== Start experiment block =====
pin_acq.write(1); pin_acq.write(0)
exp_event_log.append({'event': f'B{block_num}_start', 'timestamp': exp_clock.getTime()})
block_event_log.append({'event': f'B{block_num}_start', 'timestamp': block_clock.getTime()})
print("Experiment started and trigger sent")

try:
    # # Spontaneous activity (blank screen)
    for frame in range(int(round(FPS * float(stimuli_params['pre_stim_resting_sec']), 1))):
        win.flip()

    for idx, trial in enumerate(trials):
        stimulus_key = trial["stimulus"]
        df = stimuli[stimulus_key]
        n_dots = len(df.columns) // 3
        n_frames_trial = len(df)
        trial_sequence.append(stimulus_key)

        # If the block is complete, finish the block, pause, and start a new one
        if idx % stimuli_params["n_trials_per_block"] == 0:

            exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
            block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})

            exp_event_log.append({'event': f'B{block_num}_interblock_pause', 'timestamp': exp_clock.getTime()})
            print('inter_block_pause_sec')
            for _ in range(FPS * stimuli_params['inter_block_pause_sec']):
                win.flip()

            block_num += 1
            block_clock = core.Clock()
            pin_acq.write(1)
            pin_acq.write(0)
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
                pos = (x, y)
                dots[dot_idx].radius = radius
                dots[dot_idx].pos = pos
                dots[dot_idx].draw()
            win.flip()
        pin_aux.write(0)

        # Post-stimulus pause
        exp_event_log.append({'event': f'B{block_num}_poststim{idx}_pause', 'timestamp': exp_clock.getTime()})
        block_event_log.append({'event': f'B{block_num}_poststim{idx}_pause', 'timestamp': block_clock.getTime()})
        for _ in range(int(round(FPS * float(stimuli_params['pre_stim_pause_sec']), 1))):
            win.flip()

except KeyboardInterrupt:
    print("\nManual interruption detected. Finalizing and saving logs...")

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

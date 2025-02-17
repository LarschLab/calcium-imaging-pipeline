# -*- coding: utf-8 -*-
"""
Description:
    This script displays visual stimuli (moving dots) in bouts for an experiment on juvenile zebrafish (17–20 dpf).
    Zebrafish see one or two moving dots while we record calcium activity in the thalamus using 2-photon imaging.

    The experiment workflow is as follows:
      1. A spontaneous activity period is shown on a blank screen (e.g., 15 minutes).
      2. A series of stimulus cycles are run (each cycle displaying moving dots defined by a CSV file):
           - A brief pause before the stimulus.
           - The moving dot(s) are displayed (the positions are read from CSV files).
           - A pause follows the stimulus.
      3. Every acquisition block (e.g., every 16 trials) the Arduino is triggered to trigger a recording block.

    Event timestamps are logged and saved for subsequent analysis. The Arduino is used to send trigger signals
    that synchronize the visual stimuli with the 2-photon imaging acquisition.

@author: Matilde Perrino
Created on: 2025-02-17
"""

# Imports and Setup
from psychopy import visual, core, event, monitors, tools, gui, data
#from pyfirmata import Arduino
import pandas as pd
import datetime
from pathlib import Path

# Monitor and window settings
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('DLC_Projector', width=13.5)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter
FPS = 60

# Data and Stimuli Paths
data_path = Path(r'C:\Users\zebrafish\code\2p_visual_stimulation\data')
stimuli_path = Path(r'C:\Users\zebrafish\code\2p_visual_stimulation\stimuli\LR_thalamus_bout_exp01')

metadata = {
    "experiment_name": "LR_thalamus_bout",
    "experimenter": "Matilde",
    "experiment_date": data.getDateStr(format="%Y-%m-%d-%H%M"),
    "fish_ID": 1,
    "fish_birth": "07/02/2025",
    "fish_age": None,
    "genotype": "huc-GCamp6s",
    "size": "medium",
    "time_embedding": None,
    "respond_to_omr": False,
    "respond_to_vibrations": False,
    "embedding_comments": None,
    "general_comments": None
}

params = {
    "pre_stim_resting_sec": 900,      # 15 minutes blank screen
    "pre_stim_pause_sec": 10,         # Pause before stimulus
    "post_stim_pause_sec": 10,        # Pause after stimulus
    "inter_block_pause_sec": 20,      # Pause between acquisition blocks
    "n_trials_per_block": 16,         # Trials per block
    "n_rep_trial": 8,                 # Repetitions per stimulus
    "dot_size_cm": 0.2,
    "max_n_dots": 2
}

# Get metadata and parameters via GUI
dlg = gui.DlgFromDict(metadata, title="Metadata", sortKeys=False)
if not dlg.OK:
    core.quit()

dlg = gui.DlgFromDict(params, title="Experiment Parameters", sortKeys=False)
if not dlg.OK:
    core.quit()

# Create directory for saving experiment data
exp_dir = data_path / metadata["experiment_date"][:10] / f'fish_{metadata["fish_ID"]}'
exp_dir.mkdir(exist_ok=True, parents=True)

# Load stimuli CSV files
stimuli = {}
for file_path in stimuli_path.glob("*.csv"):
    df = pd.read_csv(file_path)
    key = file_path.stem.split("_")[0]
    stimuli[key] = df

# Assume all CSVs have the same number of frames
n_frames_trial = len(df)
conditions = [{"stimulus": key} for key in stimuli.keys()]
trials = data.TrialHandler(nReps=params["n_rep_trial"], method="random", trialList=conditions, name="trials")
trial_sequence = []

# Set up PsychoPy window and dot stimuli
win = visual.Window(color="red", units="pix", monitor=monitor, screen=1, fullscr=True)
dots = [visual.Circle(win=win, size=params["dot_size_cm"],
                      fillColor="black", pos=[0, 0], units="cm")
        for _ in range(params["max_n_dots"])]

# Arduino connection and trigger pins
board = Arduino("COM3")
ACQ_TRIGGER_PIN = 11
AUX_TRIGGER_PIN = 13
pin_acq = board.get_pin(f'd:{ACQ_TRIGGER_PIN}:o')
pin_aux = board.get_pin(f'd:{AUX_TRIGGER_PIN}:o')

# Event logging and clocks
exp_event_log = []
block_event_log = []
block_num = 0

exp_clock = core.Clock()
block_clock = core.Clock()

# Start experiment: trigger recording block and log event
pin_acq.write(1)
pin_acq.write(0)
exp_event_log.append({'event': f'B{block_num}_start', 'timestamp': exp_clock.getTime()})
block_event_log.append({'event': f'B{block_num}_start', 'timestamp': block_clock.getTime()})
print("Experiment started and trigger sent")

# Spontaneous activity (blank screen)
for frame in range(FPS * params['pre_stim_resting_sec']):
    win.flip()

exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})

for idx, trial in enumerate(trials):
    stimulus_key = trial["stimulus"]
    df = stimuli[stimulus_key]
    n_dots = len(df.columns) // 2
    trial_sequence.append(stimulus_key)

    # If the block is complete, finish the block, pause, and start a new one
    if idx % params["n_trials_per_block"] == 0:
        exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
        block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})
        exp_event_log.append({'event': f'B{block_num}_interblock_pause', 'timestamp': exp_clock.getTime()})

        for _ in range(FPS * params['inter_block_pause_sec']):
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
    for _ in range(FPS * params['pre_stim_pause_sec']):
        win.flip()

    # Stimulus presentation
    pin_aux.write(1)
    exp_event_log.append({'event': f'B{block_num}_stim{idx}_{stimulus_key}', 'timestamp': exp_clock.getTime()})
    block_event_log.append({'event': f'B{block_num}_stim{idx}_{stimulus_key}', 'timestamp': block_clock.getTime()})
    for frame in range(n_frames_trial):
        for dot_idx in range(n_dots):
            pos = df[f'dot{dot_idx}_x'][frame], df[f'dot{dot_idx}_y'][frame]
            dots[dot_idx].pos = pos
            dots[dot_idx].draw()
        win.flip()
    pin_aux.write(0)

    # Post-stimulus pause
    exp_event_log.append({'event': f'B{block_num}_poststim{idx}_pause', 'timestamp': exp_clock.getTime()})
    block_event_log.append({'event': f'B{block_num}_poststim{idx}_pause', 'timestamp': block_clock.getTime()})
    for frame in range(FPS * params['post_stim_pause_sec']):
        win.flip()

# End experiment
exp_event_log.append({'event': f'B{block_num}_end', 'timestamp': exp_clock.getTime()})
block_event_log.append({'event': f'B{block_num}_end', 'timestamp': block_clock.getTime()})
print("Experiment ended")
win.close()  # Close the PsychoPy window

# Save logs and trial sequence
current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")

df_experiment_log = pd.DataFrame(exp_event_log)
exp_log_filename = current_date + f'_fish{metadata["fish_ID"]}_experiment_log.csv'
df_experiment_log.to_csv(exp_dir / exp_log_filename, index=False)

df_block_log = pd.DataFrame(block_event_log)
block_log_filename = f"{current_date}_fish{metadata['fish_ID']}_block_log.csv"
df_block_log.to_csv(exp_dir / block_log_filename, index=False)

df_trial_sequence = pd.DataFrame(trial_sequence, columns=["stimulus"])
trial_sequence_filename = f"{current_date}_fish{metadata['fish_ID']}_trial_sequence.csv"
df_trial_sequence.to_csv(exp_dir / trial_sequence_filename, index=False)

metadata_df = pd.DataFrame([metadata])
params_df = pd.DataFrame([params])
exp_metadata = pd.concat([metadata_df, params_df], axis=1)
metadata_filename = f"{current_date}_fish{metadata['fish_ID']}_metadata.csv"
exp_metadata.to_csv(exp_dir / metadata_filename, index=False)
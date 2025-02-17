# -*- coding: utf-8 -*-
"""
Description: This script controls a visual stimulation experiment designed to study the
sensory responses of zebrafish larvae. It utilizes PsychoPy to present visual stimuli and
PyFirmata to synchronize the experiment with 2-photon (2P) imaging acquisition via an
Arduino board.

The experiment consists of a series of visual stimuli, including:
1. **Grating Stimulus**: A moving grating pattern is presented for a specified duration
   (e.g. 20 seconds). The grating moves at a constant speed, assessing the subject's visual
   response to structured motion.
2. **Looming Stimulus**: A circle expands in size from a small radius (0.5 cm) to a
   larger radius (3.5 cm) over a brief period (e.g. 3 seconds), simulating an approaching
   object. This stimulus tests the fish's response to looming objects.
3. **Inter-Stimulus Pause**: A 60-second pause between each stimulus cycle, allowing
   the subject to reset before the next stimulus is presented.

The experiment begins with a spontaneous activity period (e.g. 10 minutes), during which the
subject is shown a blank screen. This is followed by a series of stimulus cycles (gratings +
looming + pause), repeating for a total of e.g. 20 cycles. After the final cycle, a blank screen
is shown for e.g. 5 minutes to conclude the experiment.

The Arduino is used to trigger the start of the 2P imaging acquisition and synchronize
it with the stimuli. Key events such as stimulus start, cycle transitions, and experiment
start/end are logged with timestamps. These event logs are saved to a CSV file for
subsequent analysis.

@author: Matilde Perrino
Created on 2025-02-16
"""
from psychopy import visual, core, event, monitors, tools, gui, data
from pyfirmata import Arduino
import pandas as pd
import datetime
from pathlib import Path

#Set monitor properties
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('Dell', width=13.5)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor) #pixels per centimeter
FPS = 60  # Frame rate (frames per second)

#Set data path
data_path = Path(r'C:\Users\zebrafish\code\2p\data')  # Define the path to save the log
stimuli_path = Path(r'C:\Users\zebrafish\code\2p_visual_stimulation\stimuli\LR_thalamus_bout_exp01')

#Metadata dictionary
metadata_dict = {
                "experiment_name": "LR_thalamus_bout",
                "experimenter": "Matilde",
                "experiment_date": data.getDateStr(format="%Y-%m-%d-%H%M"),
                "fish_ID": 1,
                "fish_birth": '17/01/2025',
                "fish_age": None,
                "genotype": 'huc-GCamp6s',
                "size": 'medium',
                "time_embedding": None,
                "respond_to_omr": False,
                "respond_to_vibrations":False,
                "embedding_comments": None,
                "general_comments": None}

experiment_params = {
    "pre_stim_resting_sec" : 900, #15 min
    "inter_stim_pause_sec" : 20,
    "inter_acq_block_pause_sec": 20,
    "n_cycles" : 9,  # Number of stimulus cycles
    "n_trial_per_acq_cycle" : 16,
    "dot_size_cm" : 0.2, #2 mm
    "max_n_dots" : 2
    }

#open GUI for metadata
dlg = gui.DlgFromDict(metadata_dict, title="Experiment metadata", sortKeys=False)

if not dlg.OK:
    core.quit()

exp_path = data_path / metadata_dict['experiment_date'][:10] / f'fish_{metadata_dict["fish_ID"]}'
exp_path.mkdir(exist_ok=True, parents=True)

#Import stimuli
stimuli_dict = {}

for file_path in stimuli_path.glob('*.csv'):  # Use glob to match CSV files
    df = pd.read_csv(file_path)
    stimuli_dict[file_path.stem.split('_')[0]] = df

n_frames_trial = len(df)
conditions = [{'stimulus' : key} for key in stimuli_dict.keys()]
trials = data.TrialHandler(nReps=experiment_params['n_cycles'], method='random', trialList=conditions, name='trials')

# Initialize the window for visual stimulus
win = visual.Window(
    color='red',  # background color (black)
    units="pix",  # pixel units for easier handling of size and position
    monitor=monitor,
    screen=1,
    fullscr=True
)

circle = visual.Circle(
    win=win,
    units='cm',
    size=experiment_params['dot_size_cm'],
    fillColor="red",  # circle color
    lineColor="red") # circle outline color (optional)

dots = [visual.Circle(win, size=experiment_params['dot_size_cm'], fillColor='black', pos=[0, 0], units='cm') for _ in range(experiment_params['max_n_dots'])]

# Initialize Arduino connection
BOARD = Arduino('COM3')  # Set the Arduino board COM port
ACQ_TRIGGER_PIN = 11  # Pin number to start acquisition stimulus
AUX_TRIGGER_PIN = 13 # Pin number to log stimuli timestamps
pin_acq = BOARD.get_pin(f'd:{ACQ_TRIGGER_PIN}:o')  # Output pin to control stimulus trigger
pin_aux = BOARD.get_pin(f'd:{AUX_TRIGGER_PIN}:o')

# Time and event logging
event_log = []  # List to store event logs
timer = core.Clock()  # Timer to track time during the experiment

# Log the start of the experiment
event_log.append({'event': 'trigger_start_exp', 'timestamp': timer.getTime()})
pin_acq.write(1)  # Send a trigger signal to Arduino to mark the start
pin_acq.write(0)
print("Experiment started and trigger sent")

# # # Start the spontaneous activity blank screen
for frame in range(FPS * experiment_params['pre_stim_resting_sec']):
    win.flip()  # Update the window

for i, trial in enumerate(trials):
    df = stimuli_dict[trial]
    n_dots = len(df.columns)//2

    if i % 16 == 0: #16 is the number of trials of each block of recording
        for frame in range(FPS *experiment_params['inter_acq_block_pause_sec']):
            win.flip()
        pin_acq.write(1)
        pin_acq.write(0)

    for frame in range(FPS * experiment_params['inter_stim_pause_sec']/2):
        win.flip()

    event_log.append({'event': trial, 'timestamp': timer.getTime()})
    pin_aux.write(1)
    for frame in n_frames_trial:
        for i in range(n_dots):
            value = df[f'dot{i}_x'][frame], df[f'dot{i}_y'][frame]
            dots[i].pos = value
            dots[i].draw()
        win.flip()
    event_log.append({'event': trial + '_end', 'timestamp': timer.getTime()})
    pin_aux.write(0)

    #event_log.append({'event': 'inter_trial_pause', 'timestamp': timer.getTime()})
    for frame in range(FPS * experiment_params['inter_stim_pause_sec']/2):
        win.flip()

# Log the end of the experiment
event_log.append({'fish_ID': metadata_dict["fish_ID"],'event': 'end_exp', 'timestamp': timer.getTime()})
print("Experiment ended")
win.close()  # Close the PsychoPy window

# Save the event log to a CSV file
current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
df_timestamps = pd.DataFrame(event_log)
timestamps_filename = current_date + f'_fish{metadata_dict["fish_ID"]}_timestamps.csv'
df_timestamps.to_csv(exp_path / timestamps_filename, index=None)

#Save experiment metadata
metadata_filename = current_date + f'_fish{metadata_dict["fish_ID"]}_metadata.csv'
metadata_df = pd.DataFrame([metadata_dict])
exp_param_df = pd.DataFrame([experiment_params])

exp_data_df = pd.concat([metadata_df, exp_param_df], axis=1)
#exp_data_df.to_csv(exp_path / metadata_filename, index=False)
"""
@author: Matilde Perrino
Created on 2024-12-20
"""

from psychopy import visual, core, event, monitors, tools
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

# Path of stimuli and to save the log
STIMULI_PATH = Path(r'C:\Users\zebrafish\code\2p_visual_stimulation\stimuli\group_10dots.csv')  # Define the path to save the stimuli
CSV_PATH = Path(r'C:\Users\zebrafish\code\2p_visual_stimulation\data')  # Define the path to save the log

# Experiment time parameters
BACKGROUND_sec = 3
STIMULUS_sec = 3
N_CYCLES = 10
N_DOTS = 10
SIZE = 0.3

# Initialize the window for visual stimulus
win = visual.Window(
    color=(-1, -1, -1),  # background color (black)
    units="pix",  # pixel units for easier handling of size and position
    monitor=monitor,
    screen=1,
    fullscr=True
)

circle = visual.Circle(
    win=win,
    units='cm',
    size=6,
    fillColor="red",  # circle color
    lineColor="red") # circle outline color (optional)

group_dots = [visual.Circle(win, size=SIZE, fillColor='red', pos=[0, 0], units='cm') for _ in range(N_DOTS)]
dots_positions_df = pd.read_csv(STIMULI_PATH)

# Initialize Arduino connection
BOARD = Arduino('COM3')  # Set the Arduino board COM port
TRIGGER_PIN = 12  # Pin number to trigger stimulus
pin = BOARD.get_pin(f'd:{TRIGGER_PIN}:o')  # Output pin to control stimulus trigger

# Time and event logging
event_log = []  # List to store event logs
timer = core.Clock()  # Timer to track time during the experiment
pin.write(1)  # Send a trigger signal to Arduino to mark the start

# Log the start of the experiment
event_log.append({'event': 'trigger_start_exp', 'timestamp': timer.getTime()})
print("Experiment started and trigger sent")
pin.write(0)

for cycle in range(N_CYCLES):
    print(f"Starting stimulus cycle {cycle + 1}...")
    print(f"BACKGROUND")
    event_log.append({'event': f'background_{cycle}', 'timestamp': timer.getTime()})

    for frame in range(FPS * BACKGROUND_sec):
        win.flip()

    print(f"CIRCLE")
    pin.write(1)
    event_log.append({'event': f'dots_{cycle}', 'timestamp': timer.getTime()})

    for frame in range(FPS * STIMULUS_sec):
        for i in range(N_DOTS):
            value = dots_positions_df[f'dot{i}_x'][frame], dots_positions_df[f'dot{i}_y'][frame]
            group_dots[i].pos = value
            group_dots[i].draw()
        win.flip()
    pin.write(0)

# Log the end of the experiment
pin.write(1)
event_log.append({'event': 'end_exp', 'timestamp': timer.getTime()})
pin.write(0)  # Send a trigger signal to Arduino to mark the end
print("Experiment ended")
win.close()  # Close the PsychoPy window

# Save the event log to a CSV file
df_timestamps = pd.DataFrame(event_log)
current_date = datetime.datetime.now()
filename = current_date.strftime("%Y-%m-%d-%H%M") + f'_synchro_DynamicDots.csv'
df_timestamps.to_csv(CSV_PATH / filename, index=None)
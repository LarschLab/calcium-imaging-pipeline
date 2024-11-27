# -*- coding: utf-8 -*-
"""
Description: This script controls a visual stimulation experiment designed to study the
sensory responses of zebrafish larvae. It utilizes PsychoPy to present visual stimuli and
PyFirmata to synchronize the experiment with 2-photon (2P) imaging acquisition via an
Arduino board.

The experiment consists of a series of visual stimuli, including:
1. **Grating Stimulus**: A moving grating pattern is presented for a specified duration
   (20 seconds). The grating moves at a constant speed, assessing the subject's visual
   response to structured motion.
2. **Looming Stimulus**: A circle expands in size from a small radius (0.5 cm) to a
   larger radius (3.5 cm) over a brief period (3 seconds), simulating an approaching
   object. This stimulus tests the fish's response to looming objects.
3. **Inter-Stimulus Pause**: A 60-second pause between each stimulus cycle, allowing
   the subject to reset before the next stimulus is presented.

The experiment begins with a spontaneous activity period (10 minutes), during which the
subject is shown a blank screen. This is followed by a series of stimulus cycles (gratings +
looming + pause), repeating for a total of 20 cycles. After the final cycle, a blank screen
is shown for 5 minutes to conclude the experiment.

The Arduino is used to trigger the start of the 2P imaging acquisition and synchronize
it with the stimuli. Key events such as stimulus start, cycle transitions, and experiment
start/end are logged with timestamps. These event logs are saved to a CSV file for
subsequent analysis.

@author: Matilde Perrino
Created on 2024-11-11
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

#TODO distance between table and bottom of petri dish has to be 24.3 cm
FISH_ID = 4 #exerimental subject

# Experiment time parameters
SPONTANEOUS_ACTIVITY_SEC = 600 #10 min
GRATING_DURATION_SEC = 20  # Total duration for which the grating will be displayed, in seconds
LOOM_DURATION_SEC = 3  # Duration of the stimulus (seconds)
INTER_STIMULUS_SEC = 60 # Duration of inter stimulu pause (seconds)
N_CYCLES = 20  # Number of stimulus cycles
END_EXP_SEC = 60 # 5 min final blank screen

# Set properties for the grating stimulus
SIZE_STRIPE_CM = 0.5  # Size of one grating stripe in centimeters
SPEED_CM_SEC = 1  # Speed of the grating in cm per second

# Parameters for the looming circle effect
START_RADIUS_CM = 0.5  # Minimum radius in cm
END_RADIUS_CM = 3.5  # Maximum radius in cm
RADIUS_STEP = ((END_RADIUS_CM - START_RADIUS_CM) *
               PIXEL_CM_RATIO / (LOOM_DURATION_SEC * FPS))  # Radius change per frame

# Initialize the window for visual stimulus
win = visual.Window(
    color=(-1, -1, -1),  # background color (black)
    units="pix",  # pixel units for easier handling of size and position
    monitor=monitor,
    screen=1,
    fullscr=True
)

# Create the grating stimulus
grating = visual.GratingStim(
    win=win,  # Reference to the window where it will be drawn
    tex="sin",  # Use a sinewave texture for the grating pattern
    units='cm',  # Specify the size units as centimeters for easier scaling
    ori=0,  # Orientation of the grating in degrees (90 means vertical)
    sf=SIZE_STRIPE_CM*2,  #How many cycles per unit (cm). e.g. if SIZE_STRIPE_CM == 0.5, then a cycle is 1 cm
    phase=0  # Initial phase of the sinewave (start position of the grating)
)

# Initialize a black circle for the looming effect
looming_circle = visual.Circle(
    win=win,
    fillColor="white",  # circle color
    lineColor="white"  # circle outline color (optional)
)

# Initialize Arduino connection
BOARD = Arduino('COM3')  # Set the Arduino board COM port
TRIGGER_PIN = 12  # Pin number to trigger stimulus
pin = BOARD.get_pin(f'd:{TRIGGER_PIN}:o')  # Output pin to control stimulus trigger

# Time and event logging
event_log = []  # List to store event logs
CSV_PATH = Path(r'C:\Users\zebrafish\code\2p\data')  # Define the path to save the log
timer = core.Clock()  # Timer to track time during the experiment

# Log the start of the experiment
event_log.append({'fish_ID': FISH_ID,'event': 'trigger_start_exp', 'timestamp': timer.getTime()})
pin.write(1)  # Send a trigger signal to Arduino to mark the start
print("Experiment started and trigger sent")

# # # Start the spontaneous activity blank screen
for frame in range(FPS * SPONTANEOUS_ACTIVITY_SEC):
    remaining_time = SPONTANEOUS_ACTIVITY_SEC - timer.getTime()
    win.flip()  # Update the window

# Start the stimuli cycles
for cycle in range(N_CYCLES):
    print(f"Starting stimulus cycle {cycle + 1}...")
    event_log.append({'fish_ID': FISH_ID, 'event': f'gratings_{cycle}', 'timestamp': timer.getTime()})
    print(f"Starting gratings")
    for frame in range(GRATING_DURATION_SEC * FPS):  # Loop through each frame in the total duration
        # Update the grating's phase (position of the pattern) based on the speed
        # The phase is incremented by the speed of the grating per frame (frame * SPEED_CM_SEC/FPS)
        # and wrapped around (using modulus 1) to prevent it from exceeding the range [0, 1]
        grating.phase = - (frame * SPEED_CM_SEC / FPS) % 1
        grating.draw()
        win.flip()

    # Log the start of the stimulus cycle
    event_log.append({'fish_ID': FISH_ID,'event': f'loom_{cycle}', 'timestamp': timer.getTime()})
    #pin.write(1)  # Trigger stimulus on Arduino
    looming_circle.radius = START_RADIUS_CM
    print(f"Starting looming")
    # Create the looming effect by increasing the circle's radius
    for frame in range(FPS * LOOM_DURATION_SEC):
        looming_circle.radius += RADIUS_STEP  # Increase radius per frame
        looming_circle.draw()  # Draw the circle on the screen
        win.flip()  # Update the window with the drawn circle

    # Log the inter-stimulus delay
    #pin.write(0)  # Turn off stimulus on Arduino
    event_log.append({'fish_ID': FISH_ID,'event': f'interstim_pause_{cycle}', 'timestamp': timer.getTime()})
    print(f"Starting pause")
    for frame in range(FPS * INTER_STIMULUS_SEC):
        win.flip()  # Update the window

for frame in range(FPS * END_EXP_SEC):
    win.flip()  # Update the window

# Log the end of the experiment
event_log.append({'fish_ID': FISH_ID,'event': 'end_exp', 'timestamp': timer.getTime()})
print("Experiment ended")
win.close()  # Close the PsychoPy window

# Save the event log to a CSV file
df_timestamps = pd.DataFrame(event_log)
current_date = datetime.datetime.now()
filename = current_date.strftime("%Y-%m-%d-%H%M") + f'_fish{FISH_ID}.csv'
df_timestamps.to_csv(CSV_PATH / filename, index=None)
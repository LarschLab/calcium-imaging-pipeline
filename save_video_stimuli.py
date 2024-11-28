import time

from psychopy import visual, core, event, monitors, tools, filters
from pathlib import Path
import numpy as np

#Set monitor properties
PIXELS_MONITOR = [1920, 1080]
monitor = monitors.Monitor('Dell', width=57)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor) #pixels per centimeter
FPS = 60  # Frame rate (frames per second)

# Experiment time parameters
SPONTANEOUS_ACTIVITY_SEC = 5.66 #10 min
GRATING_DURATION_SEC = 20  # Total duration for which the grating will be displayed, in seconds
LOOM_DURATION_SEC = 3  # Duration of the stimulus (seconds)
INTER_STIMULUS_SEC = 10 # Duration of inter stimulus pause (seconds)
N_CYCLES = 1  # Number of stimulus cycles

# Set properties for the grating stimulus
SIZE_STRIPE_CM = 0.5  # Size of one grating stripe in centimeters
SPEED_CM_SEC = 1  # Speed of the grating in cm per second

# Parameters for the looming circle effect
START_RADIUS_CM = 0.5  # Minimum radius in cm
END_RADIUS_CM = 3.5  # Maximum radius in cm
RADIUS_STEP = ((END_RADIUS_CM - START_RADIUS_CM) *
               PIXEL_CM_RATIO / (LOOM_DURATION_SEC * FPS))  # Radius change per frame

grating_res = 800  # Resolution of the grating texture

# Create a sinewave grating
grating = filters.makeGrating(res=grating_res, cycles=1.0)

# Initialize a 'black' texture (all channels set to black)
red_grating = np.ones((grating_res, grating_res, 3)) * -1.0  # Black background (all channels -1)

# Replace the red channel with the grating pattern (this is the R channel in RGB)
red_grating[..., 0] = grating  # Modify the red channel (R is channel 0)


# Initialize the window for visual stimulus
win = visual.Window(
    color=(-1, -1, -1),  # background color (black)
    units="pix",  # pixel units for easier handling of size and position
    monitor=monitor,
    screen=1,
    fullscr=False,
    colorSpace='rgb',
    size=(grating_res, grating_res))

# Create the grating stimulus
grating = visual.GratingStim(
    win=win,  # Reference to the window where it will be drawn
    tex=red_grating,  # Use a sinewave texture for the grating pattern
    units='cm',  # Specify the size units as centimeters for easier scaling
    ori=90,  # Orientation of the grating in degrees (90 means vertical)
    sf=SIZE_STRIPE_CM*2,  #How many cycles per unit (cm). e.g. if SIZE_STRIPE_CM == 0.5, then a cycle is 1 cm
    phase=0,  # Initial phase of the sinewave (start position of the grating)
)

# Initialize a black circle for the looming effect
looming_circle = visual.Circle(
    win=win,
    fillColor="red",  # circle color
    lineColor="red"  # circle outline color (optional)
)
timer = core.Clock()
# # # Start the spontaneous activity blank screen
while timer.getTime() <= SPONTANEOUS_ACTIVITY_SEC:
    win.flip()  # Update the window
    win.getMovieFrame(buffer='front')

# Start the stimuli cycles
for cycle in range(N_CYCLES):
    for frame in range(GRATING_DURATION_SEC * FPS):  # Loop through each frame in the total duration
        # Update the grating's phase (position of the pattern) based on the speed
        # The phase is incremented by the speed of the grating per frame (frame * SPEED_CM_SEC/FPS)
        # and wrapped around (using modulus 1) to prevent it from exceeding the range [0, 1]
        grating.phase = - (frame * SPEED_CM_SEC / FPS) % 1
        grating.draw()
        win.flip()
        win.getMovieFrame(buffer='front')

    looming_circle.radius = START_RADIUS_CM
    # Create the looming effect by increasing the circle's radius
    for frame in range(FPS * LOOM_DURATION_SEC):
        looming_circle.radius += RADIUS_STEP  # Increase radius per frame
        looming_circle.draw()  # Draw the circle on the screen
        win.flip()  # Update the window with the drawn circle
        win.getMovieFrame(buffer='front')

    # Log the inter-stimulus delay
    for frame in range(FPS * INTER_STIMULUS_SEC):
        win.flip()  # Update the window
        win.getMovieFrame(buffer='front')

video_path = Path(r'C:\Users\zebrafish\code\2p_visual_stimulation\video_stimuli')
win.close()
win.saveMovieFrames('stimuli_2p_gratings_loom.mp4', fps=180, codec='mpeg4')
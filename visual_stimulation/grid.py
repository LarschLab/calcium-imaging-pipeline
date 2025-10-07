# -*- coding: utf-8 -*-
"""
Description: This script project a grid on a screen. It is used to test projector focus and setup aligment.

@author: Matilde Perrino
Created on 2024-11-11
"""

from psychopy import visual, core, event, monitors, tools

# Set monitor properties
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('Dell', width=14.5)#13.7
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter

# Initialize the window for visual stimulus
win = visual.Window(
    color="white",  # background color (white)
    units="pix",  # pixel units for easier handling of size and position
    monitor=monitor,
    screen=1,
    fullscr=True
)

# Grid parameters
rows = 5      # Number of horizontal divisions
cols = 6      # Number of vertical divisions
spacing = 150  # Spacing between lines

# Create the grid using rectangles (acting as the lines)
rectangles = []

# Create vertical rectangles (acting as vertical lines)
for col in range(cols):
    x_pos = (col - (cols // 2)) * spacing  # Calculate x position for each vertical rectangle
    rect = visual.Rect(win, width=5, height=800, fillColor="black", lineColor="black", pos=(x_pos, 0))
    rectangles.append(rect)

# Create horizontal rectangles (acting as horizontal lines)
for row in range(rows):
    y_pos = (row - (rows // 2)) * spacing  # Calculate y position for each horizontal rectangle
    rect = visual.Rect(win, width=800, height=5, fillColor="black", lineColor="black", pos=(0, y_pos))
    rectangles.append(rect)

cross_vert = visual.Rect(
    win=win,
    units='pix',
    width=5,  # thickness of the vertical line
    height=0.3*PIXEL_CM_RATIO,  # length of the vertical line (longer)
    fillColor="red",
    lineColor="red"
)

cross_horiz = visual.Rect(
    win=win,
    units='pix',
    width=0.8*PIXEL_CM_RATIO,  # length of the horizontal line (shorter)
    height=5,  # thickness of the horizontal line
    fillColor="red",
    lineColor="red"
)

center = visual.Rect(
    win=win,
    units='cm',
    width=0.4,
    height=0.4,
    fillColor="red",  # circle color
    lineColor="red") # circle outline color (optional)

# circle = visual.Circle(
#     win=win,
#     units='cm',
#     size=2,
#     fillColor="red",  # circle color
#     lineColor="red") # circle outline color (optional)

# Draw and display the grid
# for rect in rectangles:
#     rect.draw()

center.draw()
cross_vert.draw()
cross_horiz.draw()
win.flip()

# Wait for a keypress to close
event.waitKeys()

win.close()
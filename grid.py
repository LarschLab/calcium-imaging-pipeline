# -*- coding: utf-8 -*-
"""
Description: This script project a grid on a screen. It is used to test projector focus and setup aligment.

@author: Matilde Perrino
Created on 2024-11-11
"""

from psychopy import visual, core, event, monitors, tools

# Set monitor properties
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('Dell', width=13.7)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter

# Initialize the window for visual stimulus
win = visual.Window(
    color=(-1, -1, -1),  # background color (white)
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

center = visual.Rect(
    win=win,
    units='pix',
    width=3*PIXEL_CM_RATIO,
    height=3*PIXEL_CM_RATIO,
    fillColor="red",  # circle color
    lineColor="red") # circle outline color (optional)

# Draw and display the grid
for rect in rectangles:
    rect.draw()

center.draw()
win.flip()

# Wait for a keypress to close
event.waitKeys()

win.close()
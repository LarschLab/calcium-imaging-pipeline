# -*- coding: utf-8 -*-
"""
Description:This script centers the fish position with respect to the projector
            at the beginning of every experiment by displaying a cross at the
            center of the screen for alignment.

@author: Matilde Perrino
Created on 2024-11-11
"""

from psychopy import visual, core, event, monitors, tools

#Set projector screen properties
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('Dell', width=13.7)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor) #pixels per centimeter

# Initialize the window for visual stimulus
win = visual.Window(
    color=(-1, -1, -1),  # background color (black)
    units="pix",  # pixel units for easier handling of size and position
    monitor=monitor,
    screen=1,
    fullscr=True
)

# Parameters for the cross
line_length = 100  # Length of each arm of the cross
line_width = 3    # Width (thickness) of the lines
line_color = "white"  # Color of the lines

# Create the vertical rectangle (part of the cross)
vertical_rect = visual.Rect(win, width=line_width, height=line_length, fillColor=line_color, lineColor=line_color, pos=(0, 0))

# Create the horizontal rectangle (part of the cross)
horizontal_rect = visual.Rect(win, width=line_length, height=line_width, fillColor=line_color, lineColor=line_color, pos=(0, 0))

# Draw the cross (both vertical and horizontal rectangles)
vertical_rect.draw()
horizontal_rect.draw()

win.flip()

# Wait for a keypress to close
event.waitKeys()

win.close()
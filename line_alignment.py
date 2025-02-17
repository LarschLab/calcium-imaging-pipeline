# -*- coding: utf-8 -*-
"""
Description:
    Draws a 1 cm line from the center of the screen, pointing at -45°
    (with 0° defined as up).

@author: Matilde Perrino
Created on: 2025-02-17
"""

from psychopy import visual, core, event, monitors, tools
import math

# Set projector screen properties
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('Dell', width=13.7)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter

# Initialize window (units in pixels)
win = visual.Window(color=(-1, -1, -1), units="pix", monitor=monitor, screen=1, fullscr=True)

# Define line parameters
line_length_cm = 1
line_length_pix = line_length_cm * PIXEL_CM_RATIO
angle_deg = -45  # -45° from the top (0°)

# Calculate endpoint (0° = upward; using sin for x and cos for y)
dx = line_length_pix * math.sin(math.radians(angle_deg))
dy = line_length_pix * math.cos(math.radians(angle_deg))

# Draw the line from the center (0,0) to (dx,dy)
line = visual.Line(win, start=(0, 0), end=(dx, dy), lineColor="white", lineWidth=3)
line.draw()

win.flip()

# Wait for a keypress before closing
event.waitKeys()
win.close()
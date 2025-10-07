# -*- coding: utf-8 -*-
"""
Description:
    Draws a 1 cm line from the center of the screen, pointing at -45°
    (with 0° defined as up), and adds a shorter perpendicular line crossing it
    at the center. A dot is added to either the top-right or bottom-left of the line,
    as selected via GUI.

@author: Matilde Perrino
Created on: 2025-02-17
"""

from psychopy import visual, core, event, monitors, tools, gui
import math

# Set projector screen properties
PIXELS_MONITOR = [1280, 800]
monitor = monitors.Monitor('DLP', width=14.5)
monitor.setSizePix(PIXELS_MONITOR)
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)  # pixels per centimeter

# GUI
dlg = gui.Dlg(title="Dot Position Selector")
dlg.addField("Dot position:", choices=["top-right", "bottom-left"])
if not dlg.show():
    core.quit()
dot_position = dlg.data[0]  # "top-right" or "bottom-left"

# Initialize window (units in pixels)
win = visual.Window(color=(-1, -1, -1), units="pix", monitor=monitor, screen=1, fullscr=True)

# Define line parameters
line_length_cm = 0.6
line_length_pix = line_length_cm * PIXEL_CM_RATIO
angle_deg = -45  # -45° from the top (0°)

# Line vector
dx = line_length_pix * math.sin(math.radians(angle_deg))
dy = line_length_pix * math.cos(math.radians(angle_deg))

# Draw main line (centered)
line = visual.Line(win, start=(dx, dy), end=(-dx, -dy), lineColor="white", lineWidth=3)
line.draw()

# Define and draw the perpendicular line
perpendicular_length_cm = 0.2  # shorter perpendicular line
perpendicular_length_pix = perpendicular_length_cm * PIXEL_CM_RATIO

# Calculate perpendicular direction (90° from the original line)
dx_perp = perpendicular_length_pix * math.cos(math.radians(angle_deg - 90))
dy_perp = perpendicular_length_pix * math.sin(math.radians(angle_deg - 90))

# Draw the perpendicular line (centered at (0, 0))
perpendicular_line = visual.Line(win, start=(dx_perp,dy_perp), end=(-dx_perp, -dy_perp),
                                 lineColor="white", lineWidth=3)
perpendicular_line.draw()

# Define and draw dot for orientation
distance_point = 0.1 * PIXEL_CM_RATIO
dot_size = 0.1 * PIXEL_CM_RATIO
# Determine dot position based on user choice
if dot_position == "top-right":
    dot_pos = [dx - distance_point, dy + distance_point]
else:  # bottom-left
    dot_pos = [-dx + distance_point, -dy - distance_point]

dot = visual.Circle(win=win, size=dot_size, fillColor="white", pos=dot_pos)
dot.draw()


# Show both lines
win.flip()

# Wait for a keypress before closing
event.waitKeys()
win.close()

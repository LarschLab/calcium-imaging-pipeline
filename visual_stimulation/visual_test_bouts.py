# -*- coding: utf-8 -*-
"""
Description:
    Quick test to check if the fish responds to visual stimuli and shows calcium activity
    before starting a 2p experiment. Loads 3 stimuli, repeats each a few times, with
    user-defined pre/post-stimulus pause, dot size, and fish orientation.

@author: Matilde Perrino
Created on: 2025-07-11
"""

from psychopy import visual, core, monitors, tools, gui
import pandas as pd
from pathlib import Path

# Ask user for parameters
dlg = gui.Dlg(title="Stimulus Test Setup")
dlg.addField("Pre-stimulus pause (sec):", 5.0)
dlg.addField("Post-stimulus pause (sec):", 5.0)
dlg.addField("Repetitions per stimulus:", 2)
dlg.addField("Dot radius (cm):", 0.2)
dlg.addField("Max number of dots:", 2)
dlg.addField("Fish orientation:", choices=["bottom-left", "top-right"])
if not dlg.show():
    core.quit()

pre_pause = float(dlg.data[0])
post_pause = float(dlg.data[1])
n_reps = int(dlg.data[2])
dot_radius_cm = float(dlg.data[3])
max_dots = int(dlg.data[4])
fish_orientation = dlg.data[5]
flip_coordinates = (fish_orientation == "bottom-left")

# Load first 3 stimuli CSVs
stimuli_dir = Path(r"Z:\FAC\FBM\CIG\jlarsch\default\D2c\Matilde\2p\stimuli_bout_2p")
stimuli_files = sorted(stimuli_dir.glob("*.csv"))[:3]
stimuli = {f.stem: pd.read_csv(f) for f in stimuli_files}

# Monitor and window setup
monitor = monitors.Monitor('DLC_Projector', width=14.5)
monitor.setSizePix([1280, 800])
PIXEL_CM_RATIO = tools.monitorunittools.cm2pix(1, monitor)
FPS = 60
win = visual.Window(units="pix", fullscr=True, color="red", monitor=monitor, screen=1)

# Create reusable dot objects
dots = [visual.Circle(win, radius=dot_radius_cm, fillColor="black", units="cm") for _ in range(max_dots)]

# Run all stimuli for the specified number of repetitions
for rep in range(n_reps):
    for name, df in stimuli.items():
        n_dots = len(df.columns) // 2
        n_frames = len(df)

        # Pre-stimulus pause
        for _ in range(int(pre_pause * FPS)):
            win.flip()

        # Stimulus presentation
        print(f"Showing {name.split('_')[0]}")
        for frame in range(n_frames):
            for d in range(n_dots):
                x = df[f'dot{d}_x'][frame]
                y = df[f'dot{d}_y'][frame]
                if flip_coordinates:
                    x, y = -x, -y
                dots[d].pos = (x, y)
                dots[d].draw()
            win.flip()

        # Post-stimulus pause
        for _ in range(int(post_pause * FPS)):
            win.flip()

# Close window when done
win.close()
core.quit()

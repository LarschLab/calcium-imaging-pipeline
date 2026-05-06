# -*- coding: utf-8 -*-
"""
Description:
    Quick test to check if the fish responds to visual stimuli and shows calcium activity
    before starting a 2p experiment. Loads 3 stimuli, repeats each a few times, with
    user-defined pre/post-stimulus pause, dot size, and fish orientation.

@author: Matilde Perrino
Created on: 2025-07-11
"""

from __future__ import annotations

import argparse
from pathlib import Path


FISH_ORIENTATION_CHOICES = ("bottom-left", "top-right")
STIMULI_DIR = Path(r"Z:\FAC\FBM\CIG\jlarsch\default\D2c\Matilde\2p\stimuli_bout_2p")
PIXELS_MONITOR = [1280, 800]
MONITOR_NAME = "DLC_Projector"
MONITOR_WIDTH_CM = 15.2
MONITOR_DISTANCE_CM = 1
SCREEN = 1
WINDOW_COLOR = "red"
FPS = 60


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run quick pre-experiment visual test bouts.")
    parser.add_argument(
        "--fish-orientation",
        choices=FISH_ORIENTATION_CHOICES,
        default=None,
        help="Fish orientation to use. If omitted, the PsychoPy setup dialog asks for it.",
    )
    return parser.parse_args(argv)


def prompt_test_params(fish_orientation: str | None) -> dict[str, object]:
    from psychopy import core, gui

    dlg = gui.Dlg(title="Stimulus Test Setup")
    dlg.addField("Pre-stimulus pause (sec):", 5.0)
    dlg.addField("Post-stimulus pause (sec):", 5.0)
    dlg.addField("Repetitions per stimulus:", 2)
    dlg.addField("Dot radius (cm):", 0.2)
    dlg.addField("Max number of dots:", 2)
    if fish_orientation is None:
        dlg.addField("Fish orientation:", choices=list(FISH_ORIENTATION_CHOICES))
    if not dlg.show():
        core.quit()

    return {
        "pre_pause": float(dlg.data[0]),
        "post_pause": float(dlg.data[1]),
        "n_reps": int(dlg.data[2]),
        "dot_radius_cm": float(dlg.data[3]),
        "max_dots": int(dlg.data[4]),
        "fish_orientation": fish_orientation or str(dlg.data[5]),
    }


def run_visual_test_bouts(
    pre_pause: float,
    post_pause: float,
    n_reps: int,
    dot_radius_cm: float,
    max_dots: int,
    fish_orientation: str,
) -> None:
    import pandas as pd
    from psychopy import core, monitors, tools, visual

    flip_coordinates = fish_orientation == "bottom-left"
    stimuli_files = sorted(STIMULI_DIR.glob("*.csv"))[:3]
    stimuli = {f.stem: pd.read_csv(f) for f in stimuli_files}

    monitor = monitors.Monitor(MONITOR_NAME, width=MONITOR_WIDTH_CM)
    monitor.setSizePix(PIXELS_MONITOR)
    monitor.setDistance(MONITOR_DISTANCE_CM)
    tools.monitorunittools.cm2pix(1, monitor)

    win = visual.Window(
        size=PIXELS_MONITOR,
        units="pix",
        fullscr=True,
        color=WINDOW_COLOR,
        monitor=monitor,
        screen=SCREEN,
    )
    try:
        dots = [visual.Circle(win, radius=dot_radius_cm, fillColor="black", units="cm") for _ in range(max_dots)]

        for _ in range(n_reps):
            for name, df in stimuli.items():
                n_dots = len(df.columns) // 2
                n_frames = len(df)

                for _ in range(int(pre_pause * FPS)):
                    win.flip()

                print(f"Showing {name.split('_')[0]}")
                for frame in range(n_frames):
                    for d in range(n_dots):
                        x = df[f"dot{d}_x"][frame]
                        y = df[f"dot{d}_y"][frame]
                        if flip_coordinates:
                            x, y = -x, -y
                        dots[d].pos = (x, y)
                        dots[d].draw()
                    win.flip()

                for _ in range(int(post_pause * FPS)):
                    win.flip()
    finally:
        win.close()
    core.quit()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    params = prompt_test_params(args.fish_orientation)
    run_visual_test_bouts(**params)


if __name__ == "__main__":
    main()

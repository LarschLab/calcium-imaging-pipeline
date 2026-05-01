# -*- coding: utf-8 -*-
"""
Draw a fish-orientation alignment marker on the projector.

The module is import-safe for GUI integration. Running it directly keeps the
original standalone behavior: prompt for the dot position, show the projector
window, and close after a keypress.
"""

from __future__ import annotations

import math
from typing import Any


PIXELS_MONITOR = [1280, 800]
MONITOR_NAME = "DLC_Projector"
MONITOR_WIDTH_CM = 15.2
MONITOR_DISTANCE_CM = 1
SCREEN = 1
WINDOW_COLOR = "red"
LINE_LENGTH_CM = 0.6
PERPENDICULAR_LENGTH_CM = 0.2
DOT_DISTANCE_CM = 0.1
DOT_SIZE_CM = 0.1
ANGLE_DEG = -45
DOT_POSITION_CHOICES = ("bottom-left", "top-right")


def compute_alignment_geometry(dot_position: str, pixel_cm_ratio: float) -> dict[str, Any]:
    if dot_position not in DOT_POSITION_CHOICES:
        raise ValueError(f"Unsupported dot position: {dot_position}")

    line_length_pix = LINE_LENGTH_CM * pixel_cm_ratio
    dx = line_length_pix * math.sin(math.radians(ANGLE_DEG))
    dy = line_length_pix * math.cos(math.radians(ANGLE_DEG))

    perpendicular_length_pix = PERPENDICULAR_LENGTH_CM * pixel_cm_ratio
    dx_perp = perpendicular_length_pix * math.cos(math.radians(ANGLE_DEG - 90))
    dy_perp = perpendicular_length_pix * math.sin(math.radians(ANGLE_DEG - 90))

    distance_point = DOT_DISTANCE_CM * pixel_cm_ratio
    dot_size = DOT_SIZE_CM * pixel_cm_ratio
    if dot_position == "top-right":
        dot_pos = [dx - distance_point, dy + distance_point]
    else:
        dot_pos = [-dx + distance_point, -dy - distance_point]

    return {
        "line_start": (dx, dy),
        "line_end": (-dx, -dy),
        "perpendicular_start": (dx_perp, dy_perp),
        "perpendicular_end": (-dx_perp, -dy_perp),
        "dot_pos": dot_pos,
        "dot_size": dot_size,
    }


def show_fish_alignment(dot_position: str, runtime: dict[str, Any] | None = None) -> None:
    from psychopy import event, monitors, tools, visual

    runtime = dict(runtime or {})
    pixels_monitor = runtime.get("pixels_monitor", PIXELS_MONITOR)
    monitor = monitors.Monitor(
        runtime.get("monitor_name", MONITOR_NAME),
        width=float(runtime.get("monitor_width_cm", MONITOR_WIDTH_CM)),
    )
    monitor.setSizePix(pixels_monitor)
    monitor.setDistance(float(runtime.get("monitor_distance_cm", MONITOR_DISTANCE_CM)))
    pixel_cm_ratio = tools.monitorunittools.cm2pix(1, monitor)

    win = visual.Window(
        size=pixels_monitor,
        units="pix",
        fullscr=bool(runtime.get("fullscr", True)),
        color=runtime.get("window_color", WINDOW_COLOR),
        monitor=monitor,
        screen=int(runtime.get("screen", SCREEN)),
    )
    try:
        geometry = compute_alignment_geometry(dot_position, pixel_cm_ratio)
        visual.Line(
            win,
            start=geometry["line_start"],
            end=geometry["line_end"],
            lineColor="white",
            lineWidth=3,
        ).draw()
        visual.Line(
            win,
            start=geometry["perpendicular_start"],
            end=geometry["perpendicular_end"],
            lineColor="white",
            lineWidth=3,
        ).draw()
        visual.Circle(
            win=win,
            size=geometry["dot_size"],
            fillColor="white",
            pos=geometry["dot_pos"],
        ).draw()
        win.flip()
        event.waitKeys()
    finally:
        win.close()


def prompt_dot_position() -> str:
    from psychopy import core, gui

    dlg = gui.Dlg(title="Dot Position Selector")
    dlg.addField("Dot position:", choices=list(DOT_POSITION_CHOICES))
    if not dlg.show():
        core.quit()
    return dlg.data[0]


def main() -> None:
    show_fish_alignment(prompt_dot_position())


if __name__ == "__main__":
    main()

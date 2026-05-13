from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_protocol import DotsRunPlan, MODE_LOOP_STIMULI, STIMULUS_MEDIA_VIDEO, StimulusSpec, get_mode_defaults  # noqa: E402
from dots_runner import (  # noqa: E402
    _append_post_run_metadata,
    _present_stimulus,
    _pulse_pin,
    _run_hardware_experiment,
    _setup_trigger_pins,
    run_planned_experiment,
)


class DotsRunnerHardwareTests(unittest.TestCase):
    def test_serial_open_failure_does_not_create_window(self) -> None:
        state: dict[str, int] = {"windows": 0}

        class FailingArduino:
            def __init__(self, _: str) -> None:
                raise PermissionError("access denied")

        with tempfile.TemporaryDirectory() as tmpdir:
            plan = self._minimal_plan(tmpdir)
            with self._fake_modules(FailingArduino, state):
                with self.assertRaisesRegex(RuntimeError, "COM3.*not started"):
                    _run_hardware_experiment(plan)

        self.assertEqual(state["windows"], 0)

    def test_pin_setup_failure_releases_board(self) -> None:
        state: dict[str, int] = {"exits": 0}

        class PinFailArduino:
            def __init__(self, _: str) -> None:
                pass

            def get_pin(self, _: str) -> object:
                raise PermissionError("pin unavailable")

            def exit(self) -> None:
                state["exits"] += 1

        with self._fake_pyfirmata(PinFailArduino):
            with self.assertRaisesRegex(RuntimeError, "COM3.*not started"):
                _setup_trigger_pins(self._runtime())

        self.assertEqual(state["exits"], 1)

    def test_initial_pin_write_failure_releases_board(self) -> None:
        state: dict[str, int] = {"exits": 0, "writes": 0}

        class FailingPin:
            def write(self, _: int) -> None:
                state["writes"] += 1
                raise PermissionError("write denied")

        class WriteFailArduino:
            def __init__(self, _: str) -> None:
                pass

            def get_pin(self, _: str) -> FailingPin:
                return FailingPin()

            def exit(self) -> None:
                state["exits"] += 1

        with self._fake_pyfirmata(WriteFailArduino):
            with self.assertRaisesRegex(RuntimeError, "COM3.*not started"):
                _setup_trigger_pins(self._runtime())

        self.assertEqual(state["writes"], 1)
        self.assertEqual(state["exits"], 1)

    def test_mode_defaults_include_detectable_trigger_pulse_width(self) -> None:
        defaults = get_mode_defaults(MODE_LOOP_STIMULI)

        self.assertEqual(defaults["runtime"]["trigger_pulse_sec"], 0.05)

    def test_pulse_pin_writes_high_waits_then_writes_low(self) -> None:
        events: list[tuple[str, float | int]] = []

        class Pin:
            def write(self, value: int) -> None:
                events.append(("write", value))

        def wait(duration_sec: float) -> None:
            events.append(("wait", duration_sec))

        _pulse_pin(Pin(), 0.05, wait)

        self.assertEqual(events, [("write", 1), ("wait", 0.05), ("write", 0)])

    def test_hardware_runner_prints_setup_and_b0_diagnostics(self) -> None:
        state: dict[str, int] = {"windows": 0, "pin_writes": 0}

        class Pin:
            def write(self, _: int) -> None:
                state["pin_writes"] += 1

        class Arduino:
            def __init__(self, _: str) -> None:
                pass

            def get_pin(self, _: str) -> Pin:
                return Pin()

            def exit(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            plan = self._minimal_plan(tmpdir)
            with (
                self._fake_modules(Arduino, state),
                patch("dots_runner._append_post_run_metadata"),
                patch("builtins.print") as print_mock,
            ):
                run_planned_experiment(plan)

        messages = [call.args[0] for call in print_mock.call_args_list]
        expected = [
            "[dots_runner] run_planned_experiment entered: mode=loop_stimuli branch=hardware",
            "[dots_runner] hardware runner entered",
            f"[dots_runner] metadata directory resolved: {Path(tmpdir) / 'Tester' / 'F001' / '01_raw' / '2p' / 'metadata'}",
            "[dots_runner] Arduino trigger pins initialized",
            "[dots_runner] PsychoPy window created",
            "[dots_runner] B0 acquisition trigger pulse starting",
            "[dots_runner] B0 acquisition trigger pulse finished",
            "[dots_runner] final output save starting",
            "[dots_runner] final output save finished",
        ]
        for message in expected:
            self.assertIn(message, messages)
        self.assertGreaterEqual(state["pin_writes"], 4)

    def test_present_video_stimulus_draws_movie_frames(self) -> None:
        events: list[str] = []

        class Window:
            def flip(self) -> None:
                events.append("flip")

        class Movie:
            def __init__(self, win: object, filename: str, units: str, loop: bool) -> None:
                events.append(f"movie:{Path(filename).name}:{units}:{loop}")
                self.draw_count = 0

            @property
            def isFinished(self) -> bool:
                return self.draw_count >= 2

            def draw(self) -> None:
                self.draw_count += 1
                events.append("draw")

        visual = types.SimpleNamespace(MovieStim=Movie)
        stimulus = StimulusSpec(
            runtime_key="stim_video",
            display_name="stim_video",
            path=Path("stim_video.mp4"),
            frame_count=120,
            n_dots=0,
            duration_sec=2.0,
            media_type=STIMULUS_MEDIA_VIDEO,
        )

        _present_stimulus(
            Window(),
            visual,
            [],
            stimulus,
            False,
            "fixed",
            0.2,
            None,
            [],
            [],
            None,
            None,
            0.05,
            lambda _: None,
            0,
            0,
            "stim_video",
            False,
        )

        self.assertEqual(events, ["movie:stim_video.mp4:pix:False", "draw", "flip", "draw", "flip"])

    def test_post_run_metadata_opens_metadata_and_anatomy_dialogs(self) -> None:
        dialog_titles: list[str] = []
        psychopy = types.ModuleType("psychopy")
        core = types.ModuleType("psychopy.core")
        gui = types.ModuleType("psychopy.gui")

        class Dialog:
            def __init__(self, _: dict[str, object], title: str, sortKeys: bool = False) -> None:
                dialog_titles.append(title)
                self.OK = True

        def quit_() -> None:
            raise AssertionError("core.quit should not be called when dialogs are accepted")

        gui.DlgFromDict = Dialog
        core.quit = quit_
        psychopy.core = core
        psychopy.gui = gui

        with tempfile.TemporaryDirectory() as tmpdir:
            meta_dir = Path(tmpdir)
            plan = self._minimal_plan(tmpdir)
            with patch.dict(sys.modules, {"psychopy": psychopy, "psychopy.core": core, "psychopy.gui": gui}):
                _append_post_run_metadata(
                    meta_dir,
                    "2026-04-30-1200",
                    dict(plan.metadata),
                    {},
                    {},
                    plan.runtime,
                    plan,
                )

            metadata_file = meta_dir / "2026-04-30-1200_fF001_metadata.csv"
            metadata_map = dict(zip(pd.read_csv(metadata_file)["parameter"], pd.read_csv(metadata_file)["value"]))

        self.assertEqual(dialog_titles, ["Metadata", "Anatomy"])
        self.assertEqual(str(metadata_map["fish_died"]).lower(), "false")
        self.assertEqual(int(metadata_map["frames_per_slice_anatomy"]), 90)

    def test_post_run_metadata_session_two_uses_session_suffix(self) -> None:
        psychopy = types.ModuleType("psychopy")
        core = types.ModuleType("psychopy.core")
        gui = types.ModuleType("psychopy.gui")

        class Dialog:
            def __init__(self, _: dict[str, object], title: str, sortKeys: bool = False) -> None:
                self.OK = True

        gui.DlgFromDict = Dialog
        core.quit = lambda: None
        psychopy.core = core
        psychopy.gui = gui

        with tempfile.TemporaryDirectory() as tmpdir:
            meta_dir = Path(tmpdir)
            plan = self._minimal_plan(tmpdir)
            plan.metadata["session"] = 2
            with patch.dict(sys.modules, {"psychopy": psychopy, "psychopy.core": core, "psychopy.gui": gui}):
                _append_post_run_metadata(
                    meta_dir,
                    "2026-04-30-1200",
                    dict(plan.metadata),
                    {},
                    {},
                    plan.runtime,
                    plan,
                )

            self.assertTrue((meta_dir / "2026-04-30-1200_fF001_r2_metadata.csv").exists())
            self.assertFalse((meta_dir / "2026-04-30-1200_fF001_metadata.csv").exists())

    def _minimal_plan(self, output_root: str) -> DotsRunPlan:
        return DotsRunPlan(
            mode=MODE_LOOP_STIMULI,
            metadata={
                "experimenter": "Tester",
                "fish_ID": "F001",
                "session": 1,
                "fish_orientation": "bottom-left",
            },
            functional_params={},
            stimuli_params={"max_n_dots": 1},
            runtime={**self._runtime(), "data_path": output_root},
            stimuli_catalog=[],
            trials=[],
            planned_blocks=[],
            timeline=[],
            total_duration_sec=0.0,
        )

    def _runtime(self) -> dict[str, object]:
        return {
            "arduino_port": "COM3",
            "acq_trigger_pin": 11,
            "aux_trigger_pin": 13,
            "trigger_pulse_sec": 0.05,
            "monitor_name": "DLC_Projector",
            "monitor_width_cm": 15.2,
            "monitor_distance_cm": 1,
            "pixels_monitor": [1280, 800],
            "window_color": "red",
            "screen": 1,
            "fullscr": True,
        }

    def _fake_modules(self, arduino_class: type, state: dict[str, int]) -> patch.dict:
        psychopy = types.ModuleType("psychopy")
        core = types.ModuleType("psychopy.core")
        monitors = types.ModuleType("psychopy.monitors")
        tools = types.ModuleType("psychopy.tools")
        monitorunittools = types.ModuleType("psychopy.tools.monitorunittools")
        visual = types.ModuleType("psychopy.visual")

        class Monitor:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def setSizePix(self, _: object) -> None:
                pass

            def setDistance(self, _: object) -> None:
                pass

        class Window:
            def __init__(self, *args: object, **kwargs: object) -> None:
                state["windows"] += 1

            def close(self) -> None:
                pass

        class Circle:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

        def cm2pix(*args: object, **kwargs: object) -> int:
            return 1

        class Clock:
            def getTime(self) -> float:
                return 0.0

        def wait(_: float) -> None:
            pass

        core.Clock = Clock
        core.wait = wait
        monitors.Monitor = Monitor
        monitorunittools.cm2pix = cm2pix
        tools.monitorunittools = monitorunittools
        visual.Window = Window
        visual.Circle = Circle
        psychopy.core = core
        psychopy.monitors = monitors
        psychopy.tools = tools
        psychopy.visual = visual

        pyfirmata = types.ModuleType("pyfirmata")
        pyfirmata.Arduino = arduino_class

        return patch.dict(
            sys.modules,
            {
                "psychopy": psychopy,
                "psychopy.core": core,
                "psychopy.monitors": monitors,
                "psychopy.tools": tools,
                "psychopy.tools.monitorunittools": monitorunittools,
                "psychopy.visual": visual,
                "pyfirmata": pyfirmata,
            },
        )

    def _fake_pyfirmata(self, arduino_class: type) -> patch.dict:
        pyfirmata = types.ModuleType("pyfirmata")
        pyfirmata.Arduino = arduino_class
        return patch.dict(sys.modules, {"pyfirmata": pyfirmata})


if __name__ == "__main__":
    unittest.main()

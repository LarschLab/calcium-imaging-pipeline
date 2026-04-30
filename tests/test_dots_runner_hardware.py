from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "visual_stimulation"))

from dots_protocol import DotsRunPlan, MODE_LOOP_STIMULI, get_mode_defaults  # noqa: E402
from dots_runner import _pulse_pin, _run_hardware_experiment, _setup_trigger_pins  # noqa: E402


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

    def _minimal_plan(self, output_root: str) -> DotsRunPlan:
        return DotsRunPlan(
            mode=MODE_LOOP_STIMULI,
            metadata={
                "experimenter": "Tester",
                "fish_ID": "F001",
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

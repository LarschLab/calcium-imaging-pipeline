# -*- coding: utf-8 -*-
"""
Description: Test the Arduino acquisition trigger line used by the dots GUI.

@author: Matilde Perrino
Created on 2024-11-11
"""

import time
from pyfirmata import Arduino

PORT = "COM3"
PIN = 11
PULSE_SEC = 0.05
PULSE_COUNT = 5
INTER_PULSE_SEC = 1.0

board = Arduino(PORT)

try:
    time.sleep(2)
    pin = board.get_pin(f"d:{PIN}:o")
    pin.write(0)

    print(f"Pulsing Arduino pin {PIN} on {PORT} {PULSE_COUNT} times ({PULSE_SEC:.3f} sec high).")
    for pulse_index in range(PULSE_COUNT):
        print(f"Pulse {pulse_index + 1}/{PULSE_COUNT}")
        pin.write(1)
        time.sleep(PULSE_SEC)
        pin.write(0)
        if pulse_index < PULSE_COUNT - 1:
            time.sleep(INTER_PULSE_SEC)
finally:
    board.exit()

print("Arduino trigger test complete.")

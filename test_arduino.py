# -*- coding: utf-8 -*-
"""
Description: This script to test communication with an Arduino Board

@author: Matilde Perrino
Created on 2024-11-11
"""

import time
from pyfirmata import Arduino, util

PIN = 13
# Specify the COM port where your Arduino is connected (COM3 in this case)
board = Arduino('COM3')

# Give the board some time to initialize
time.sleep(2)

# Set pin 12 as an OUTPUT
pin = board.get_pin(f'd:{PIN}:o')

pin.write(0)

# Turn the pin ON (HIGH)
pin.write(1)
print(f"Pin {PIN} is ON for 15 seconds")

# Wait for 5 seconds
time.sleep(3)

# Turn the pin OFF (LOW)
pin.write(0)
print(f"Pin {PIN} is OFF")

# Close the connection to the board
board.exit()
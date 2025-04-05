# https://learn.adafruit.com/adafruit-ds2482s-800-8-channel-i2c-to-1-wire-bus-adapter/circuitpython-and-python
# https://docs.circuitpython.org/projects/ds248x/en/latest/index.html

# SPDX-FileCopyrightText: Copyright (c) 2024 Liz Clark for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""Adafruit DS2482S-800 8-Channel DS18B20 Example"""

import time
import board
from adafruit_ds248x import Adafruit_DS248x

# Initialize I2C bus and DS248x
# i2c = board.STEMMA_I2C()
i2c = board.I2C()
ds248x = Adafruit_DS248x(i2c, 0x18)

def test_rom():
        rom = bytearray(8)
        if not ds248x.onewire_search(rom):
            print("No more devices found\n\n")

        print("Found device ROM: ", end="")
        for byte in rom:
            print(f"{byte:02X} ", end="")
        print()
        while True:
            temperature = ds248x.ds18b20_temperature(rom)
            print(f"Temperature: {temperature:.2f} °C")

            time.sleep(1)

def test_8channel():
        while True:
            for i in range(8):
                ds248x.channel = i
                print(f"Reading channel {ds248x.channel}")
                temperature = ds248x.ds18b20_temperature()
                print(f"Temperature: {temperature:.2f} °C")
                print()
                time.sleep(1)

test_8channel()

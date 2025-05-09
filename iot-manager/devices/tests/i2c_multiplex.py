# https://learn.adafruit.com/adafruit-pca9548-8-channel-stemma-qt-qwiic-i2c-multiplexer/circuitpython-python

# SPDX-FileCopyrightText: 2021 Carter Nelson for Adafruit Industries
# SPDX-License-Identifier: MIT

# This example shows using TCA9548A to perform a simple scan for connected devices
import board
import adafruit_tca9548a
import time

# Create I2C bus as normal
i2c = board.I2C()  # uses board.SCL and board.SDA
# i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller

# Create the TCA9548A object and give it the I2C bus
tca = adafruit_tca9548a.TCA9548A(i2c, 0x70)
tca2 = adafruit_tca9548a.TCA9548A(i2c, 0x71)

for channel in range(8):
    if tca[channel].try_lock():
        print("Channel {}:".format(channel), end="")
        addresses = tca[channel].scan()
        print([hex(address) for address in addresses if address != 0x70])
        tca[channel].unlock()

# test AHT sensors

import adafruit_ahtx0

while True:
	
	for i in range(2):
		print("tca 1")
		sensor = adafruit_ahtx0.AHTx0(tca[i])
		print("\nTemperature: %0.1f C" % sensor.temperature)
		print("Humidity: %0.1f %%" % sensor.relative_humidity)
		
		# test 1 MUX for AHT sensor + 1 MUX for 
		# https://learn.adafruit.com/working-with-multiple-i2c-devices/circuitpython-5
		
		print("tca 2")
		sensor = adafruit_ahtx0.AHTx0(tca2[i])
		print("\nTemperature: %0.1f C" % sensor.temperature)
		print("Humidity: %0.1f %%" % sensor.relative_humidity)
    
    
    
	time.sleep(2)



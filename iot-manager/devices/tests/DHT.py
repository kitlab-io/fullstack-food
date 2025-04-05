# dht.py
# https://learn.adafruit.com/dht/dht-circuitpython-code
# https://docs.circuitpython.org/projects/dht/en/latest/api.html#adafruit_dht.DHT21
# https://github.com/adafruit/Adafruit_CircuitPython_DHT

# https://github.com/KrzysztofZurek1973/webthing-esp32-humidity-AM2301

# https://learn.adafruit.com/modern-replacements-for-dht11-dht22-sensors/what-are-better-alternatives

# SPDX-FileCopyrightText: 2017 Limor Fried for Adafruit Industries
#
# SPDX-License-Identifier: MIT

import time

import adafruit_dht
import board

import RPi.GPIO as GPIO


# GPIO.setmode(GPIO.BOARD)
# sensor_pin = 7 # mode BOARD 7 = BCM / GPIO 4
sensor_pin = 22 # mode BCM
GPIO.setup(sensor_pin, GPIO.IN) 
print(GPIO.input(sensor_pin))

dht = adafruit_dht.DHT21(board.D22, use_pulseio=False)
#dht = adafruit_dht.DHT21(board.D22)
#dht = adafruit_dht.DHT22(board.D22, use_pulseio=False)

while True:
    try:
        temperature = dht.temperature
        humidity = dht.humidity
        # Print what we got to the REPL
        print('check DHT')
        # print("Temp: {:.1f} *C \t Humidity: {}%".format(temperature, humidity))
    except RuntimeError as e:
        # Reading doesn't always work! Just print error and we'll try again
        print("Reading from DHT failure: ", e.args)

    time.sleep(1)

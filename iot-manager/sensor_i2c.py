# https://learn.adafruit.com/adafruit-stemma-soil-sensor-i2c-capacitive-moisture-sensor/python-circuitpython-test

import board
import adafruit_ahtx0
from adafruit_seesaw.seesaw import Seesaw
import time

i2c = board.I2C()


def test_aht():
	sensor = adafruit_ahtx0.AHTx0(i2c)
	
	print("\n Temp: %0.1f C" % sensor.temperature)
	print("\n Humd: %0.1f %%" % sensor.relative_humidity)

def test_soil():
	ss = Seesaw(i2c, addr=0x36)
	
	touch = ss.moisture_read()
	temp = ss.get_temp()
	
	print("temp: "+ str(temp))
	print("mois: "+ str(touch))


while True:
	
	test_soil()
	
	time.sleep(2)

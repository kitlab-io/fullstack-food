import board
import adafruit_ahtx0
from adafruit_seesaw.seesaw import Seesaw
import time

i2c = board.I2C()
sensor = adafruit_ahtx0.AHTx0(i2c)

ss = Seesaw(i2c, addr=0x36)

while True:
	print("\n Temp: %0.1f C" % sensor.temperature)
	print("\n Humd: %0.1f %%" % sensor.relative_humidity)

	touch = ss.moisture_read()
	temp = ss.get_temp()
	
	print("temp: "+ str(temp))
	print("mois: "+ str(touch))

	time.sleep(2)
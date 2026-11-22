try:
  import usocket as socket
except:
  import socket

from machine import Pin
import network

import esp
esp.osdebug(None)

import gc
gc.collect()

# Copy wifi_secrets.example.py to wifi_secrets.py (gitignored) and fill it in.
from wifi_secrets import WIFI_SSID as ssid, WIFI_PASSWORD as password

station = network.WLAN(network.STA_IF)

station.active(True)
station.connect(ssid, password)

while station.isconnected() == False:
  pass

print('Connection successful')
print(station.ifconfig())

led = Pin(2, Pin.OUT)
# Setup on Orange Pi Zero 2W 
- tested on Orange Pi Zero 2W 4GB (TBD 1GB)
- Python 3.11

Install debian bookworm 10.2 desktop xfce linux 6.1.31
sudo apt install python3.11-venv
sudo apt-get install python3-dev
python3 -m venv venv
pip3 install Adaftuit-Blinka
pip3 install -r fullstack-food/iot-manager/requirements.txt

Remove Raspberry Pi packages?
rpi-lgpio==0.6
rpi-ws281x==5.0.0
RPi.GPIO==0.7.1

# Running all services

core services:
- redis database 
- redis queue worker

user interface services:
- flask web app backend
- single page web app frontend

admin/dev services:
- redis queue dashboard

```bash
# set working directory
cd iot-manager
# set PYTHONPATH
export PYTHONPATH="/Users/michael.garrido/Documents/GitHub/kitlab-io/fullstack-food/iot-manager":$PYTHONPATH

# activate virutal environment
source .venv/bin/activate

# start redis database
redis-server

# start redis queue worker
python services
# check if protocol is scheduled
# and schedule works

# for debug, run redis queue dashboard
rq-dashboard
```

# Simple Python library to control the TP-Link Kasa Smart Power Strip

Simple Python library to control the TP-Link Kasa Smart Power Strip (HW 1.0)<br/>
Amazon link: https://www.amazon.com/Smart-Wi-Fi-Power-Strip-TP-Link/dp/B07G95FFN3/

Command syntax is fairly similar to the single relay TP Link smart plugs<br/>
Encrypt/Decrypt code is based on https://github.com/softScheck/tplink-smartplug/blob/master/tplink_smartplug.py<br/>
The main difference seems to be that the basic get_sysinfo command only works over UDP, all other commands<br/>
can use either UDP or TCP

Now compatible with Python3 as well as Python2.7.  Tested with Python2.7 and Python3.6.  To work with Python2.7 the
future package must be installed:

```pip install future```

Also now compatible with [Adafruit's CircuitPython](https://circuitpython.org/) under the [CircuitPython branch](https://github.com/p-doyle/Python-KasaSmartPowerStrip/tree/CircuitPython).

## Example code:

```
from KasaSmartPowerStrip import SmartPowerStrip

power_strip = SmartPowerStrip('<your power strip ip>')

# get general system info
print(power_strip.get_system_info())

# get the name and other info of a plug; unless the Kasa app is used the plugs won't have a name by default
print(power_strip.get_plug_info(1))

# set the name of a plug
print(power_strip.set_plug_name(1, 'my plug'))

# toggle a plug by number (1-6)
print(power_strip.toggle_plug('off', plug_num=1))

# toggle a plug by name
print(power_strip.toggle_plug('on', plug_name='my plug'))

# toggle multiple plugs by number
print(power_strip.toggle_plugs('on', plug_num_list=[1, 3, 5]))

# toggle multiple plugs by name
print(power_strip.toggle_plugs('on', plug_name_list=['my plug', 'my plug 2']))

# toggle the leds for each relay on or off
print(power_strip.toggle_relay_leds('off'))

# get the current energy usage with mA, mV, mW and the total wh
print(power_strip.get_realtime_energy_info(plug_num=1))

# get a list with the watt hours for each day in the specified month/year
print(power_strip.get_historical_energy_info(month='10', year='2018', plug_num=1))

# reboot the power strip
# NOTE this will toggle all relays off/on but will preserve state after rebooting
# e.g. if it was off before rebooting it will remain off afterwards
print(power_strip.reboot(5))
```

## Initial Setup
To setup a new power strip without having to use the Kasa App(which requires you to create a cloud account):
1. Plug the power strip in and ensure that the status LED is alternating green/orange.  If it isn't press and <br/>
    hold one of the relay buttons for 5 seconds to perform a factory reset.
2. Look for and connect to a WiFi network which should start with TP-LINK_Power Strip.<br/>
    The default IP of the power strip is 192.168.0.1.  It will only accept commands from IP 192.168.0.100, which<br/>
    it should assign to the first device to connect to its WiFi.
3. OPTIONAL: If you want to ensure that the power strip never connects to the cloud there are a few options. <br/>
    The first is to clear the cloud server URL that is set on the power strip but I can't guarantee that this works. </br>
    UPDATE: It seems setting the server_url blank does not work and the device will still attempt to connect to n-devs.tplinkcloud.com.     I would recommend using something like [PiHole](https://github.com/pi-hole/pi-hole) for DNS where you can blacklist n-devs.tplinkcloud.com to prevent the switch from resolving it to an IP address.
    </br>
    The second option is to get the  mac address of the power strip so that you can block outgoing traffic on your 
    router before allowing it to connect to your network or to use VLANs to prevent it from connecting to the internet </br>
    If it has no internet access however it will be constantly making NTP requests, which may be required for the historical </br>
    usage data to work correctly, though I can't say for sure. 

```
power_strip = SmartPowerStrip('192.168.0.1')

print(power_strip.set_cloud_server_url(server_url=''))

print(power_strip.get_system_info()['system']['get_sysinfo']['mac'])
```

4. Use the below code to have it connect to your own WiFi network:

```
power_strip = SmartPowerStrip('192.168.0.1')

# for WPA2 the key_type is '3', I would guess WPA is '2' and WEP is '1' but I have not tested this
power_strip.set_wifi_credentials('my ssid', 'my psk', key_type='3')
```

4. After setting the WiFi info it should restart and then connect to your network at which point<br/>
    you should be able to begin using it.

<br/><br/>
## Other commands not yet implemented:

Add countdown timer rules:<br/>
```{"context":{"child_ids":["<plug childId>"]},"count_down":{"add_rule":{"act":1,"delay":1800,"enable":1,"name":"add timer"}}}```

Get countdown timer rules:<br/>
```{"context":{"child_ids":["<plug childId>"]},"count_down":{"get_rules":{}}}```

Delete countdown timer rules:<br/>
```{"context":{"child_ids":["<plug childId>"]},"count_down":{"delete_all_rules":{}}}```



## Notes on GPIO for RPi

removing python3-rpi.gpio (0.7.1~a4-1+b4) ...
Blinka Found existing installation: RPi.GPIO 0.7.1
Blinka Uninstalling RPi.GPIO-0.7.1:
Blinka Successfully uninstalled RPi.GPIO-0.7.1
Blinka Looking in indexes: https://pypi.org/simple, https://www.piwheels.org/simple
Blinka Collecting rpi-lgpio
Blinka Downloading https://www.piwheels.org/simple/rpi-lgpio/rpi_lgpio-0.6-py3-none-any.whl (11 kB)
Blinka Collecting lgpio>=0.1.0.1
Blinka Downloading lgpio-0.2.2.0-cp311-cp311-manylinux_2_34_aarch64.whl (364 kB)
Blinka ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 364.8/364.8 kB 1.5 MB/s eta 0:00:00
Blinka 
Blinka Installing collected packages: lgpio, rpi-lgpio
Blinka Successfully installed lgpio-0.2.2.0 rpi-lgpio-0.6
DONE.

## Notes on i2C sensors

(venv-global) fullstackfood@raspberrypi:~ $ sudo i2cdetect -y 1
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- 
10: -- -- -- -- -- -- -- -- 18 -- -- -- -- -- -- -- 
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
30: -- -- -- -- -- -- 36 -- 38 -- -- -- -- -- -- -- 
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
70: -- -- -- -- -- -- -- --                         
(venv-global) fullstackfood@raspberrypi:~ $ python /home/fullstackfood/fullstack-food/iot-manager/sensor_i2c.py
temp: 21.74606557578
mois: 930
temp: 21.334002221880002
mois: 914
temp: 21.84596480844
mois: 885
temp: 21.44014229556
mois: 872
temp: 21.74606557578
mois: 328
temp: 21.945864041100002
mois: 329
temp: 21.74606557578
mois: 324
temp: 21.84596480844
mois: 332
temp: 22.05200411478
mois: 736
temp: 22.15190334744
mois: 743
temp: 22.05200411478
mois: 742
temp: 22.15190334744
mois: 337
temp: 22.15190334744
mois: 813
temp: 22.05200411478
mois: 812

### Analog Soil Moisture Sensor

Reading ADS1x15 values, press Ctrl-C to quit...
|      0 |      1 |      2 |      3 |
-------------------------------------
|  16715 |   4712 |   4738 |   4709 |
|  16715 |   4716 |   4714 |   4762 |

GAIN = 1
value range:
- sensor in air: 17000
- sensor in dry soil: 15000 - 16000
- sensor in wet soil: <13000

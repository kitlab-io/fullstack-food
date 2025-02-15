# fullstack-food

## Setup 

Install Python 3.13.0 (via pyenv)

For homeassitant:

Follow Homeassistant Core installation 
Copy configurations .yaml into /srv/homeassistant
In virtualenv in  /srv/homeassistant
pip3 install -r homeassistant/requirements.txt

For iot-manager:
Create virtualenv in /srv/iot-manager
In virtualenv in  /srv/iot-manager
pip3 install -r iot-manager/requirements.txt

## Use
To interact with sensors via Circuitpython librarires:
python3 sensor_i2c.py

To interact with sensors via Raspberry Pi OS device overlays:
shell commands in iot-manager/gpio-map.sh
ex.
```bash
cd /sys/bus/w1/devices/

cat 28-000000bdcab7/temperature 
```

To capture camera snapshots via Home Assistant automations:
Make POST request to Home Assistant automation webhook per automations.yaml
ex. http://192.168.254.133:8123/api/webhook/-iXF3BvKQqw1_zj5BG7ngCq-l

Image saved to actions > action:camera.snapshot > media > file
ex. /home/fullstackfood/esphome/plantcam.jpg
```yaml
  actions:
  - action: camera.snapshot
    metadata: {}
    data:
      filename: /home/fullstackfood/esphome/plantcam.jpg
```

Make sure the configurations.yaml allows hass to write to external directory
```yaml
homeassistant:
  allowlist_external_dirs:
    - '/home/fullstackfood/esphome/'
```
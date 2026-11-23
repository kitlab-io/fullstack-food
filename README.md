# fullstack-food

Local-network monitoring and climate control for house plants, microgreens and mushrooms,
with RGB(W) LED strips that show the state of each growing area.

The project is mid-restructure (see `docs/plan/restructure-plan.md`). What works today is
the control system running against simulated hardware. Nothing below has run on real
sensors or actuators yet.

## Try the mock system

Any machine with Python 3.12:

```bash
pip install -e . pytest
python -m fsf_core validate     # check the catalog and the example sites
pytest                          # simulate weeks of growing in a couple of minutes
```

With Docker, a simulated site runs against a real MQTT broker:

```bash
FSF_SITE=mushrooms FSF_SPEED=600 docker compose -f deploy/compose/base.yaml -f deploy/compose/mock.yaml up --build
```

`FSF_SITE` is `houseplants`, `microgreens` or `mushrooms`. `FSF_SPEED` is simulated seconds
per real second. The dashboard is at http://localhost:8080 (read-only: zones, charts, devices, log, raw MQTT traffic).
The hub log prints each zone status change. To watch the MQTT traffic:

```bash
docker compose -f deploy/compose/base.yaml -f deploy/compose/mock.yaml exec broker mosquitto_sub -t 'fsf/#' -v
```

To move a planting to its next stage (for example mushrooms from incubation to fruiting):

```bash
docker compose -f deploy/compose/base.yaml -f deploy/compose/mock.yaml exec broker mosquitto_pub -t fsf/mushrooms/hub/cmd -m '{"id":"a1","name":"advance_stage","planting":"oyster-1"}'
```

## Towards real hardware

Nothing below has been run on a board yet.

```bash
fsf validate --pins sites/local/my-site          # check pin assignments, propose pins for blanks
fsf firmware build sites/local/my-site           # one ESPHome config per node in build/firmware/<site>/
fsf firmware flash sites/local/my-site shelf-node    # needs `pip install esphome` and a filled-in secrets.yaml
fsf node test shelf-node --site sites/local/my-site --mqtt-host <broker> --actuate
```

Then commission in stages, each recorded by the hub: `fsf bench <device>`, `fsf calibrate
<device>`, `fsf zone test <zone>`, and finally `fsf zone mode <zone> active`. A zone with an
actuator that has not passed its bench test stays in observe mode: the hub logs what it
would do and switches nothing.

`fsf node test` runs the same contract checks the simulated nodes pass: payloads match
`schemas/mqtt/`, an on-command ends by itself, `off` is honoured. With `--actuate` it switches
every actuator on the node for a few seconds.

## What the scenario tests cover

| Scenario | Checked |
|---|---|
| House plants | A dry pot is watered and its LED goes from needs-water back to ok; minimum interval and daily cap hold; an empty reservoir blocks the pump; a cold room raises an alert |
| Microgreens | Germination, blackout, light and harvest stages advance on schedule; the light follows the photoperiod; the daily water cap holds; a cold room shows on the strip |
| Mushrooms | Incubation chamber holds temperature; moving to the fruiting chamber switches setpoints; humidity, CO2, temperature and light stay in band; harvest and clear-down |
| Faults | Stale sensor, stuck sensor, node offline, hub crash, hub restart mid-grow |

## Where things are

`AGENTS.md` describes the layout, commands and conventions. Definitions live in `catalog/`
(generic components, exact models, species, recipes, LED themes) and `sites/` (one
installation each), all validated against `schemas/`.

Secrets never go in tracked files. Put local values in `sites/local/secrets.yaml` (gitignored).

## Legacy prototype

The original Raspberry Pi / Orange Pi prototype (`iot-manager/`, `homeassistant/`, `nodes/`)
is kept for reference until the new stack runs on hardware.

### Setup 

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

### Use
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
ex. `http://<home-assistant-host>:8123/api/webhook/<plantcam_webhook_id>`
(the webhook id is set in Home Assistant `secrets.yaml`, see `homeassistant/.homeassistant/secrets.example.yaml`)

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
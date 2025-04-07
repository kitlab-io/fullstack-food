import pathlib
from utils import load_yaml

# actuators
class LightCWWW:
    def __init__(self):
        pass
    def on(self):
        print('LightCWWW on')
        return {
            "type": "light_cwww",
            "action": "on"
        }
        pass
    def off(self):
        print('LightCWWW off')
        return {
            "type": "light_cwww",
            "action": "off"
        }
        pass

class LightRGB:
    def __init__(self):
        pass
    def on(self):
        pass
    def off(self):
        pass

class Fan:
    def __init__(self):
        pass
    def on(self):
        pass
    def off(self):
        pass
    
class HeatElement:
    def __init__(self):
        pass
    def on(self):
        pass
    def off(self):
        pass
    
class WaterPump:
    def __init__(self):
        pass
    def on(self):
        pass
    def off(self):
        pass

# sensors
class LightSensor:
    def __init__(self):
        pass
    def measure(self):
        pass

class AirSensor:
    def __init__(self):
        pass
    def measure(self):
        pass

class SoilTempSensor:
    def __init__(self):
        pass
    def measure(self):
        pass

class SoilMoistureSensor:
    def __init__(self):
        pass
    def measure(self):
        pass

class WaterLevelSensor:
    def __init__(self):
        pass
    def measure(self):
        pass
    
path_config_devices = pathlib.Path('./config/devices.yaml')
# path_config_protocols = pathlib.Path('./config/protocols.yaml')

config = {
    "devices": path_config_devices,
    # "protocols": path_config_protocols
}

def bind_devices(config_devices):
    print(config_devices)
    system_devices = {
        'light_cwww':[],
        'light_rgb':[],
        'fan':[],
        'heat_wire':[],
        'pump_water':[]
    }
    
    for category in config_devices:
        print(category)
        
        for d in config_devices[category]:
            device_type = d['type']
            if device_type == 'light_cwww':
                light_cwww = LightCWWW()
                system_devices[device_type].append(light_cwww)
            # elif device_type == 'light_rgb':
            #     system_devices[device_type].append(devices.LightRGB())
            # elif device_type == 'fan':
            #     system_devices[device_type].append(devices.Fan())
            # elif device_type == 'heat_wire':
            #     system_devices[device_type].append(devices.HeatElement())
            # elif device_type == 'pump_water':
            #     system_devices[device_type].append(devices.WaterPump())
        
    return system_devices

config_devices = load_yaml(config['devices'])['devices']
# config_protocols = load_yaml(config['protocols'])['protocols']
    
system_devices = bind_devices(config_devices)
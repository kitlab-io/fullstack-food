import pathlib
from utils import load_yaml, logger, now_str
import json
import datetime

from services.camera import CameraUSB

# actuators
class Actuator:
    def __init__(self, config_data):
        self.config_data = config_data
    
class LightCWWW(Actuator):
    def __init__(self, config_data):
        super.__init__(config_data)
        pass
    def on(self):
        logger.info('LightCWWW on')
        return {
            "type": "light_cwww",
            "action": "on"
        }
        
    def off(self):
        logger.info('LightCWWW off')
        return {
            "type": "light_cwww",
            "action": "off"
        }

class LightRGB(Actuator):
    def __init__(self, config_data):
        super.__init__(config_data)
    def on(self):
        pass
    def off(self):
        pass

class Fan(Actuator):
    def __init__(self, config_data):
        super.__init__(config_data)
    def on(self):
        pass
    def off(self):
        pass
    
class HeatElement(Actuator):
    def __init__(self, config_data):
        super.__init__(config_data)
    def on(self):
        pass
    def off(self):
        pass
    
class WaterPump(Actuator):
    def __init__(self, config_data):
        super.__init__(config_data)
        pass
    def on(self):
        pass
    def off(self):
        pass

# sensors
class Sensor:
    def __init__(self, config_data):
        self.config_data = config_data
        self.last_reading = {}
        
        
class Camera(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device = CameraUSB('/dev/video1','2592x1944')
        
    def photo(self):
        logger.info('Camera photo')
        photo_filepath, device_path = self.device.photo()
        
        return {
            "type": "camera",
            "action": "photo",
            "filepath": photo_filepath,
            "devicepath": device_path
        }
        
    
class LightSensor(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device_path = {
            "connection": "i2c",
            "multiplex": 0,
            "address": "x01",
            "chip": "xxx001"
        }
        
    def measure(self):
        data = read_gpio(self.device_path)
        return data

class AirTempHumiditySensor(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device_path = {
            "connection": "i2c",
            "multiplex": 0,
            "address": "x01",
            "chip": "xxx001"
        }
        
    def measure(self):
        data = read_gpio(self.device_path)
        return data

class AirTempHumidityBarometerSensor(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device_path = {
            "connection": "i2c",
            "multiplex": 0,
            "address": "x01",
            "chip": "xxx001"
        }
        
    def measure(self):
        data = read_gpio(self.device_path)
        return data

class SoilTempSensor(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device_path = {
            "connection": "i2c",
            "multiplex": 0,
            "address": "x01",
            "chip": "xxx001"
        }
        
    def measure(self):
        data = read_gpio(self.device_path)
        return data

class SoilMoistureSensor(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device_path = {
            "connection": "i2c",
            "multiplex": 0,
            "address": "x01",
            "chip": "xxx001"
        }
        
    def measure(self):
        data = read_gpio(self.device_path)
        return data

class WaterLevelSensor(Sensor):
    def __init__(self, config_data):
        super.__init__(config_data)
        self.device_path = {
            "connection": "i2c",
            "multiplex": 0,
            "address": "x01",
            "chip": "xxx001"
        }
        
    def measure(self):
        data = read_gpio(self.device_path)
        return data
    
    
def read_gpio(device_path):
    # 
    return {
        "values":[0,1],
        "ts": now_str()
    }

def write_gpio(device_path, data):
    
    return {}


def bind_devices(config_devices):
    logger.info(f'bind_devices {json.dumps(config_devices)}')
    system_devices = {
        'actuators':{
            'light_cwww':[],
            'light_rgb':[],
            'fan':[],
            'heat_wire':[],
            'pump_water':[],
        },
        'sensors': {
            'cameras':[],
            'water_level':[],
            'soil_moisture':[],
            'soil_temp':[],
            'air_temp_humidity':[],
            'light':[],
        }
    }
    
    for category in config_devices:
        print(category)
        # TODO check if devices are physically connected by checking i2c addresses and GPIO pins
        
        for d in config_devices[category]:
            device_type = d['type']
            
            # sensors
            if device_type == 'light_cwww':
                light_cwww = LightCWWW()
                system_devices['actuators'][device_type].append(light_cwww)
            elif device_type == 'pump_water':
                water_pump = WaterPump()
                system_devices['actuators'][device_type].append(water_pump)
            elif device_type == 'light_rgb':
                light_rgb = LightRGB()
                system_devices['actuators'][device_type].append(light_rgb)
            elif device_type == 'fan':
                fan = Fan()
                system_devices['actuators'][device_type].append(fan)
            elif device_type == 'heat_wire':
                heat_element = HeatElement()
                system_devices['actuators'][device_type].append(heat_element)
            
            # sensors
            elif device_type == 'usb_camera':
                sensor = CameraUSB()
                system_devices['sensors'][device_type].append(sensor)
            elif device_type == 'soil_moisture':
                sensor = SoilMoistureSensor()
                system_devices['sensors'][device_type].append(sensor) 
            elif device_type == 'soil_temp':
                sensor = SoilTempSensor()
                system_devices['sensors'][device_type].append(sensor)
            elif device_type == 'water_level':
                sensor = WaterLevelSensor()
                system_devices['sensors'][device_type].append(sensor) 
            elif device_type == 'air_temp_humidity':
                sensor = AirTempHumiditySensor()
                system_devices['sensors'][device_type].append(sensor) 
            elif device_type == 'air_temp_humidity_barometer':
                sensor = AirTempHumidityBarometerSensor()
                system_devices['sensors'][device_type].append(sensor)   
            elif device_type == 'light_fullspectrum':
                sensor = LightSensor()
                system_devices['sensors'][device_type].append(sensor) 
              
            
    return system_devices

# from system import load_config
# system_devices = bind_devices(config_devices)

system_devices = {}
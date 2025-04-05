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
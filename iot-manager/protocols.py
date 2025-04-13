import json
from dataclasses import dataclass

from utils import logger
from system import config_protocols
from devices import *


@dataclass
class Notification:
    message: str

def notify_human(notification:Notification):
    logger.warning(f'notify_human {notification.message}')
    # send sms
    # send email
    # send push notification
    pass

def resolve_sensor_alert(sensor:Sensor):
    logger.warning(f'resolve_sensor_alert {json.dumps(sensor.config_data)}')
    
    if sensor.isinstance(WaterLevelSensor):
        notify_human(Notification('water tank low. refill water'))
        
    if sensor.isinstance(SoilMoistureSensor):
        notify_human(Notification('soil is dry.'))


def activate_protocols():
    protocol = config_protocols['default']
    
    for activity in protocol:
        logger.info(activity['description'])
        for action in activity['actions']:
            logger.info(action)
            if action == 'light_cwww':
                pass
            
# load configuration
import yaml
import pathlib
from datetime import datetime, timedelta

from services import scheduler, sensors, actuators, camera
from services.worker import job_lights_off, job_lights_on, job_camera_photo, job_read_sensors
import devices

path_config_devices = pathlib.Path('./config/devices.yaml')
path_config_protocols = pathlib.Path('./config/protocols.yaml')

config = {
    "devices": path_config_devices,
    "protocols": path_config_protocols
}

repeat_limit = 3
system_devices = {}
config_protocols = {}
config_devices = {}

def load_yaml(path_yaml):
    with open(path_yaml, 'r') as file:
        data = yaml.safe_load(file)
    # print(data)
    return data

def to_scheduled_actions(protocol_task):
    print(protocol_task)
    

def schedule_water_pump(timing, action):
    print(timing)
    print(action)
    # get device
    # pump on
    # pump off
    
def schedule_lights(protocol_task, devices):
    global repeat_limit
    
    print('schedule_lights')
    print(protocol_task)
    print(devices)
    # get device
    light = devices['actuators']['light_cwww'][0]
    print(light)
    
    on_time, off_time = scheduler.get_start_stop_times(protocol_task)
    # on_datetime = scheduler.get_date_start() + on_time
    # off_datetime = scheduler.get_date_start() + off_time
    on_datetime = scheduler.get_date_start() + timedelta(hours=on_time[0], minutes=on_time[1], seconds=on_time[2])
    off_datetime = scheduler.get_date_start() + timedelta(hours=off_time[0], minutes=off_time[1], seconds=off_time[2])
    
    # test instant scheduling
    metadata = {
        "type": "light_cwww",
        "on_datetime": on_datetime.isoformat(),
        "off_datetime": off_datetime.isoformat()
    }
    scheduler.schedule_action_now(job_lights_on, metadata)
    
    # default: repeat for 30 times (~30 days)
    # repeat_limit = 3
    repeat_iter = 0
    if 'repeat' in protocol_task:
        r = protocol_task['repeat']
        while repeat_iter < repeat_limit:
            
            metadata = {
                "type": "light_cwww",
                "on_datetime": on_datetime.isoformat(),
                "off_datetime": off_datetime.isoformat()
            }
            
            scheduler.schedule_action(on_datetime, job_lights_on, metadata)
            scheduler.schedule_action(off_datetime, job_lights_off, metadata)
            
            on_datetime += timedelta(days=r['d'], hours=r['h'], minutes=r['m'], seconds=r['s'])
            off_datetime += timedelta(days=r['d'], hours=r['h'], minutes=r['m'], seconds=r['s'])
            
            repeat_iter += 1

def schedule_cameras(protocol_task, devices):
    global repeat_limit
    print('schedule_cameras')
    print(protocol_task)
    print(devices)
    
    on_time, off_time = scheduler.get_start_stop_times(protocol_task)    
    on_datetime = scheduler.get_date_start() + timedelta(hours=on_time[0], minutes=on_time[1], seconds=on_time[2])

    # test instant scheduling
    metadata = {
        "type": "camera",
        "on_datetime": on_datetime.isoformat(),
    }
    scheduler.schedule_action_now(job_camera_photo, metadata)

    # default: repeat for 30 times (~30 days)
    # repeat_limit = 3
    repeat_iter = 0
    if 'repeat' in protocol_task:
        r = protocol_task['repeat']
        while repeat_iter < repeat_limit:
            
            metadata = {
                "type": "camera",
                "on_datetime": on_datetime.isoformat(),
            }
            
            scheduler.schedule_action(on_datetime, job_camera_photo, metadata)

            on_datetime += timedelta(days=r['d'], hours=r['h'], minutes=r['m'], seconds=r['s'])
      
            repeat_iter += 1
            
def schedule_sensors(protocol_task, devices):
    global repeat_limit
    print('schedule_sensors')
    print(protocol_task)
    print(devices)
    
    on_time, off_time = scheduler.get_start_stop_times(protocol_task)    
    on_datetime = scheduler.get_date_start() + timedelta(hours=on_time[0], minutes=on_time[1], seconds=on_time[2])

    # test instant scheduling
    metadata = {
        "type": "sensors",
        "on_datetime": on_datetime.isoformat(),
    }
    scheduler.schedule_action_now(job_read_sensors, metadata)

    # default: repeat for 30 times (~30 days)
    # repeat_limit = 3
    repeat_iter = 0
    if 'repeat' in protocol_task:
        r = protocol_task['repeat']
        while repeat_iter < repeat_limit:
            
            metadata = {
                "type": "sensors",
                "on_datetime": on_datetime.isoformat(),
            }
            
            scheduler.schedule_action(on_datetime, job_camera_photo, metadata)

            on_datetime += timedelta(days=r['d'], hours=r['h'], minutes=r['m'], seconds=r['s'])
      
            repeat_iter += 1       
    
def schedule_heat(timing, action):
    print(timing)
    print(action)
    # get device
    # pump on
    # pump off
    # heat on
    # heat off
    
def schedule_fan(timing, action):
    print(timing)
    print(action)
    # get device
    # pump on
    # pump off
    # fan on
    # fan off

def schedule_jobs(protocols, devices):
    print('schedule_jobs')
    # select default protocol
    protocol = protocols['default']
    print(protocol)
    
    for key in protocol:
        protocol_task = protocol[key]
        # print(action)
        
        if key == 'light_cwww':
            schedule_lights(protocol_task, devices)
        elif key == 'camera':
            schedule_cameras(protocol_task, devices)
        # elif key == 'water':
        #     schedule_water_pump(protocol_task)
        # elif key == 'heat':
        #     schedule_heat(protocol_task)
        # elif key == 'fan':
        #     schedule_fan(protocol_task)
    
    # scheduler.work()

def load_config(config):
    global config_devices, config_protocols
    print(config)
    config_devices = load_yaml(config['devices'])['devices']
    config_protocols = load_yaml(config['protocols'])['protocols']
    
    return config_devices, config_protocols
# start scheduling service

# start redis server
# redis-server

# rq-dashboard
# http://127.0.0.1:9181/

# load configuration
import yaml
import pathlib
from datetime import datetime, timedelta

from services import scheduler, sensors, actuators, camera
from services.worker import job_lights_off, job_lights_on
import devices

path_config_devices = pathlib.Path('./config/devices.yaml')
path_config_protocols = pathlib.Path('./config/protocols.yaml')

config = {
    "devices": path_config_devices,
    "protocols": path_config_protocols
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
                light_cwww = devices.LightCWWW()
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
    print('schedule_lights')
    print(protocol_task)
    print(devices)
    # get device
    light = devices['light_cwww'][0]
    print(light)
    
    on_time, off_time = scheduler.get_start_stop_times(protocol_task)
    # on_datetime = scheduler.get_date_start() + on_time
    # off_datetime = scheduler.get_date_start() + off_time
    on_datetime = scheduler.get_date_start() + timedelta(hours=on_time[0], minutes=on_time[1], seconds=on_time[2])
    off_datetime = scheduler.get_date_start() + timedelta(hours=off_time[0], minutes=off_time[1], seconds=off_time[2])
    
    metadata = {
        "type": "light_cwww",
        "on_datetime": on_datetime.isoformat(),
        "off_datetime": off_datetime.isoformat()
    }
    # lights on 
    # scheduler.schedule_action(on_datetime, scheduler.job_lights_on, metadata)
    # lights off
    # scheduler.schedule_action(off_datetime, scheduler.job_lights_off, metadata)
    
    # test instant scheduling
    scheduler.schedule_action_now(job_lights_on, metadata)
    scheduler.schedule_action_now(job_lights_off, metadata)
    
    
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
        # elif key == 'water':
        #     schedule_water_pump(protocol_task)
        # elif key == 'heat':
        #     schedule_heat(protocol_task)
        # elif key == 'fan':
        #     schedule_fan(protocol_task)
    
    # scheduler.work()

def load_config(config):
    print(config)
    config_devices = load_yaml(config['devices'])['devices']
    config_protocols = load_yaml(config['protocols'])['protocols']
    
    devices = bind_devices(config_devices)
    
    schedule_jobs(config_protocols, devices)


load_config(config)
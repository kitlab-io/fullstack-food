from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.repeat import Repeat

from datetime import timedelta, datetime

from devices import system_devices
from utils import logger

# rq worker --with-scheduler

# https://python-rq.org/docs/#considerations-for-jobs

# ensure the worker can access the python functions for the job
# export PYTHONPATH="$PYTHONPATH:/Users/michael.garrido/Documents/GitHub/kitlab-io/fullstack-food/iot-manager"
# https://github.com/rq/rq/issues/2035

# r = Redis()
# https://github.com/rq/rq/blob/d9fb4fda3c6edf183f85d8456bab507bf3341148/rq/queue.py#L160
# q = Queue(connection=r)

import services.queues as queues

def work(queue, redis=queues.r):
    worker = Worker(queues=[queue], connection=redis)
    worker.work(with_scheduler=True)

def job_lights_on(target):
    logger.info(f'job_lights_on {target}')
    
    light = system_devices['light_cwww'][0]
    light.on()
    
    return target

def job_lights_off(target):
    logger.info(f'job_lights_off {target}')

    
    light = system_devices['light_cwww'][0]
    light.off()
    
    return target

def job_pump_on(target):
    logger.info(target)
    return target

def job_pump_off(target):
    logger.info(target)
    return target

def job_heat_on(target):
    logger.info(target)
    return target

def job_heat_off(target):
    logger.info(target)
    return target

def job_take_photo(target):
    logger.info(target)
    return target


if __name__ == "__main__":
    work(queues._lights) 
from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.repeat import Repeat

from datetime import timedelta, datetime

# rq worker --with-scheduler

r = Redis()
q = Queue(connection=r)

_lights = Queue(connection=r, name='lights')
_water = Queue(connection=r, name='water')
_camera = Queue(connection=r, name='camera')
_heat = Queue(connection=r, name='heat')
_cloud_sync = Queue(connection=r, name='cloud_sync')

def get_queue(action_type=None):
    if action_type == 'light_cwww':
        return _lights
    else:
        return q
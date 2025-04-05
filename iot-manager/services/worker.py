from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.repeat import Repeat

from datetime import timedelta, datetime

# rq worker --with-scheduler

# export PYTHONPATH="$PYTHONPATH:/Users/michael.garrido/Documents/GitHub/kitlab-io/fullstack-food/iot-manager"
# https://github.com/rq/rq/issues/2035

r = Redis()
q = Queue(connection=r)

def work(queue=q, redis=r):
    worker = Worker(queues=[queue], connection=redis)
    worker.work(with_scheduler=True)

def job_lights_on(target):
    print(target)
    return target

def job_lights_off(target):
    print(target)
    return target

if __name__ == "__main__":
    
    work() 
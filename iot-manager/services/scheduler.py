from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.repeat import Repeat

from datetime import timedelta, datetime
import services.queues as queues
from utils import logger
# rq worker --with-scheduler

# r = Redis()
# q = Queue(connection=r)

# job = q.enqueue_in(timedelta(seconds=10), sensors.read_air_temperature_humidity)

# Schedule job to run at 9:15, October 10th
# job = q.enqueue_at(datetime(2019, 10, 8, 9, 15), say_hello)

# Schedule job to be run in 10 seconds
# job = q.enqueue_in(timedelta(seconds=10), say_hello)

# Repeat job 3 times after successful completion, with 60 second intervals
# job = q.enqueue(say_hello, repeat=Repeat(times=3, interval=60))

# Use different intervals between repetitions
# job = q.enqueue(say_hello, repeat=Repeat(times=3, interval=[10, 30, 60])

def get_seconds(d, h, m, s):
    return d*24*60*60 + h*60*60 + m*60 + s

def get_date_start():
    today = datetime.today()
    # return [today.year, today.month, today.day]
    return today

def get_queue(metadata):
    if 'type' in metadata:
        q = queues.get_queue(metadata['type'])
    else:
        q = queues.get_queue()
        
    return q

def get_start_stop_times(protocol_task):
    start_time = None
    stop_time = None
    
    start = protocol_task['start_time']
    duration = protocol_task['duration']
    
    start_time = [start['h'], start['m'], start['s']]
    stop_time = [start['h']+duration['h'], start['m']+duration['m'], start['s']+duration['s']]
    
    return start_time, stop_time

def set_job_metadata(job, metadata):
    for key in metadata:
        # logger.info(key)
        # logger.info(metadata[key])
        job.meta[key] = metadata[key]
        job.save_meta()

def schedule_action(action_datetime, action, metadata={}):
    logger.info(f'schedule_action {action} {action_datetime} {metadata}')
    q = get_queue(metadata)
    job = q.enqueue_at(action_datetime, action, metadata)
    set_job_metadata(job, metadata)
    
    logger.info(f'Job id: {job.id} {job.meta}')
    return job
    
# def schedule_repeating_action(protocol_task, action_datetime, action, metadata={}):
#     # default: repeat for 30 days
#     logger.info(f'schedule_repeating_action {action} {action_datetime} {metadata}')
#     q = get_queue(metadata)
    
#     print(protocol_task)
    
    
def schedule_action_now(action, metadata={}, delay_s=3):
    logger.info(f'schedule_action_now {action} {metadata}')
    if 'type' in metadata:
        q = queues.get_queue(metadata['type'])
    else:
        q = queues.get_queue()
    
    job = q.enqueue_in(timedelta(seconds=delay_s), action, metadata)
    set_job_metadata(job, metadata)

    return job

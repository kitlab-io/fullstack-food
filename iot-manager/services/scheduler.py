from redis import Redis
from rq import Queue, Worker
from rq.job import Job
from rq.repeat import Repeat

from datetime import timedelta, datetime

# rq worker --with-scheduler

r = Redis()
q = Queue(connection=r)

# job = q.enqueue_in(timedelta(seconds=10), sensors.read_air_temperature_humidity)

# Schedule job to run at 9:15, October 10th
# job = q.enqueue_at(datetime(2019, 10, 8, 9, 15), say_hello)

# Schedule job to be run in 10 seconds
# job = q.enqueue_in(timedelta(seconds=10), say_hello)

# Repeat job 3 times after successful completion, with 60 second intervals
# job = q.enqueue(say_hello, repeat=Repeat(times=3, interval=60))

# Use different intervals between repetitions
# job = q.enqueue(say_hello, repeat=Repeat(times=3, interval=[10, 30, 60])

def get_date_start():
    today = datetime.today()
    # return [today.year, today.month, today.day]
    return today

def get_start_stop_times(protocol_task):
    start_time = None
    stop_time = None
    
    start = protocol_task['start_time']
    duration = protocol_task['duration']
    
    start_time = [start['h'], start['m'], start['s']]
    stop_time = [start['h']+duration['h'], start['m']+duration['m'], start['s']+duration['s']]

    # if 'repeat' in protocol_task:
    #     pass
    
    return start_time, stop_time

def set_job_metadata(job, metadata):
    for key in metadata:
        print(key)
        print(metadata[key])
        job.meta[key] = metadata[key]
        job.save_meta()

def schedule_action(action_datetime, action, metadata={}):
    print('schedule_action')
    print(action_datetime)
    print(action)
    print(metadata)
    job = q.enqueue_at(action_datetime, action, metadata)
    set_job_metadata(job, metadata)
    
    print('Job id: %s' % job.id)
    print(job.meta)
    return job
    
    
def schedule_action_now(action, metadata={}, delay_s=3):
    print('schedule_action_now')
    job = q.enqueue_in(timedelta(seconds=delay_s), action, metadata)
    set_job_metadata(job, metadata)
    
    return job
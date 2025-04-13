from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, DateTime, Sequence
from sqlalchemy.orm import relationship, backref, declarative_base, sessionmaker
from sqlalchemy.sql import func

import json

Base = declarative_base()
engine = create_engine('sqlite:///data/sensordata.db')
Session = sessionmaker(bind=engine)
connection = None

class SensorReading(Base):
    __tablename__ = "sensor_reading"
    # Base.metadata,
    id = Column(Integer, Sequence('sensor_reading_seq'), primary_key=True)
    sensor_type = Column(String)
    raw_data = Column(String) # JSON
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __init__(self, sensor_type, raw_data):
        self.sensor_type = sensor_type
        self.raw_data = raw_data
        
class Photo(Base):
    __tablename__ = "photos"
    # Base.metadata,
    id = Column(Integer, Sequence('photo_seq'), primary_key=True)
    filepath = Column(String)
    resolution = Column(String)
    zone = Column(String)
    device_path = Column(String)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __init__(self, sensor_type, raw_data):
        self.sensor_type = sensor_type
        self.raw_data = raw_data


def setup():
    # engine = create_engine('sqlite:///data/sensordata.db')
    Base.metadata.create_all(engine) 


def init():
    global connection
    # engine = create_engine('sqlite:///data/sensordata.db')
    connection = engine.connect()


def add_sensor_reading(sensor_type, raw_data):
    session = Session()
    sensor_reading = SensorReading(sensor_type, json.dumps(raw_data) )
    session.add(sensor_reading)
    session.commit()
    session.close()
    

def check_sensor_data_for_alerts(sensor_type):
    alerts = []
    
    if sensor_type == 'water_level':
        alert = check_water_level()
        if alert:
            alerts.append(sensor_type)
            
    if sensor_type == 'soil_moisture':
        alert = check_soil_moisture()
        if alert:
            alerts.append(sensor_type)
    
    if sensor_type == 'soil_temp':
        alert = check_soil_temp()
        if alert:
            alerts.append(sensor_type)
    
    return alerts
        
def check_water_level():
    return False

def check_soil_moisture():
    return False

def check_soil_temp():
    return False

def check_air_temp():
    return False

def check_air_humidity():
    return False

def check_light():
    return False
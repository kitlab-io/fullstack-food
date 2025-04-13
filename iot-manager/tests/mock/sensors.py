import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import argparse
from sqlalchemy import create_engine

from utils import base_dir
from pathlib import Path 

def generate_temperature_data(start_date=None, num_days=None, num_readings=None, 
                             interval_seconds=60, mean_temp_celsius=25, 
                             temp_std_dev=3, add_noise=True):
    """
    Generate synthetic temperature sensor data.
    
    Args:
        start_date (str): Start date in 'YYYY-MM-DD HH:MM:SS' format. Defaults to now if None.
        num_days (float): Number of days to generate data for. Must provide either this or num_readings.
        num_readings (int): Total number of readings to generate. Must provide either this or num_days.
        interval_seconds (int): Time interval between readings in seconds.
        mean_temp_celsius (float): Mean temperature in Celsius.
        temp_std_dev (float): Standard deviation for temperature variations.
        add_noise (bool): Whether to add random noise to the data.
        
    Returns:
        pandas.DataFrame: DataFrame with temperature data
    """
    # Input validation
    if num_days is None and num_readings is None:
        raise ValueError("Must provide either num_days or num_readings")
    
    if num_days is not None and num_readings is not None:
        raise ValueError("Cannot provide both num_days and num_readings")
    
    # Set up start date
    if start_date is None:
        start_time = datetime.now()
    else:
        start_time = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
    
    # Calculate number of readings based on days or use provided num_readings
    if num_days is not None:
        num_readings = int((num_days * 24 * 60 * 60) / interval_seconds)
    
    # Generate timestamps
    delta = timedelta(seconds=interval_seconds)
    timestamps = [start_time + i * delta for i in range(num_readings)]
    timestamps_ms = [int(t.timestamp() * 1000) for t in timestamps]
    
    # Generate base temperature pattern with daily cycle
    hours_of_day = [(start_time + i * delta).hour for i in range(num_readings)]
    base_temp = np.array([mean_temp_celsius + 3 * np.sin(hour * np.pi / 12) for hour in hours_of_day])
    
    # Add random variations
    if add_noise:
        temperatures_celsius = base_temp + np.random.normal(0, temp_std_dev, num_readings)
    else:
        temperatures_celsius = base_temp
    
    # Convert to Fahrenheit
    temperatures_fahrenheit = temperatures_celsius * 9/5 + 32
    
    # Create DataFrame
    df = pd.DataFrame({
        'timestamp_ms': timestamps_ms,
        'temperature_celsius': temperatures_celsius,
        'temperature_fahrenheit': temperatures_fahrenheit
    })
    
    return df

def save_dataframe_to_csv(df, filename='temperature_sensor_data.csv', directory=None):
    """
    Save DataFrame to CSV file.
    
    Args:
        df (pandas.DataFrame): DataFrame to save
        filename (str): Name of output file
        directory (str): Directory to save to, default is current dir
        
    Returns:
        str: Path to saved file
    """
    if directory:
        os.makedirs(directory, exist_ok=True)
        filepath = os.path.join(directory, filename)
    else:
        # filepath = filename
        filepath = Path(*[base_dir,'tests','data',filename])
    
    df.to_csv(filepath, index=False)
    return filepath

def load_csv_to_dataframe(filepath):
    """
    Load CSV file to DataFrame.
    
    Args:
        filepath (str): Path to CSV file
        
    Returns:
        pandas.DataFrame: Loaded DataFrame
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
    
    return pd.read_csv(filepath)

def save_dataframe_to_sqlite(df, database_path='temperature_data.db', 
                           table_name='temperature_readings', if_exists='replace'):
    """
    Save DataFrame to SQLite database using SQLAlchemy.
    
    Args:
        df (pandas.DataFrame): DataFrame to save
        database_path (str): Path to SQLite database file
        table_name (str): Name of the table to create
        if_exists (str): How to behave if table exists ('fail', 'replace', or 'append')
        
    Returns:
        str: Path to database file
    """
    engine = create_engine(f'sqlite:///{database_path}')
    df.to_sql(table_name, engine, if_exists=if_exists, index=False)
    return database_path

def main():
    parser = argparse.ArgumentParser(description='Generate synthetic temperature sensor data')
    
    # Data generation parameters
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD HH:MM:SS)', default=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    # Time span options (mutually exclusive)
    # time_group = parser.add_mutually_exclusive_group(required=True)
    parser.add_argument('--days', type=float, help='Number of days to generate data for', default=1)
    parser.add_argument('--readings', type=int, help='Total number of readings to generate')
    
    parser.add_argument('--interval', type=int, default=60, 
                      help='Interval between readings in seconds (default: 60)')
    parser.add_argument('--mean-temp', type=float, default=25, 
                      help='Mean temperature in Celsius (default: 25)')
    parser.add_argument('--std-dev', type=float, default=3, 
                      help='Standard deviation for temperature (default: 3)')
    
    # Output options
    parser.add_argument('--csv', type=str, default='temperature_sensor_data.csv', 
                      help='CSV output filename (default: temperature_data.csv)')
    parser.add_argument('--db', type=str, 
                      help='SQLite database output filename (optional)')
    parser.add_argument('--table', type=str, default='temperature_readings', 
                      help='Table name for database (default: temperature_readings)')
    
    args = parser.parse_args()
    
    # Generate data
    df = generate_temperature_data(
        start_date=args.start_date,
        num_days=args.days,
        num_readings=args.readings,
        interval_seconds=args.interval,
        mean_temp_celsius=args.mean_temp,
        temp_std_dev=args.std_dev
    )
    
    # Save to CSV
    csv_path = save_dataframe_to_csv(df, filename=args.csv)
    print(f"Data saved to CSV: {csv_path}")
    
    # Save to SQLite if specified
    if args.db:
        db_path = save_dataframe_to_sqlite(df, database_path=args.db, table_name=args.table)
        print(f"Data saved to SQLite database: {db_path}, table: {args.table}")

if __name__ == "__main__":
    main()
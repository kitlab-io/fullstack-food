#!/usr/bin/env python3
"""
Script to load temperature data from CSV files into the database.

This script reads temperature data from a CSV file, processes it, and inserts it
into the SQLite database defined in datastore.py.

Usage:
    python load_temperature_data.py [csv_file_path]

If no file path is provided, it defaults to 'tests/data/temperature_sensor_data.csv'.
"""

import os
import sys
import json
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime

# Add parent directory to path to allow imports from parent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the database module
from datastore import add_sensor_reading, setup
from utils import logger, base_dir


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Load temperature data from CSV into database'
    )
    parser.add_argument(
        'csv_file',
        nargs='?',
        default=os.path.join(base_dir, 'tests/data/temperature_sensor_data.csv'),
        help='Path to the CSV file containing temperature data (default: tests/data/temperature_sensor_data.csv)'
    )
    parser.add_argument(
        '--sensor_type',
        default='soil_temp',
        choices=['soil_temp', 'air_temp_humidity', 'air_temp_humidity_barometer'],
        help='Type of sensor data to import (default: soil_temp)'
    )
    parser.add_argument(
        '--batch_size',
        type=int,
        default=100,
        help='Number of records to insert in a batch (default: 100)'
    )
    return parser.parse_args()


def load_csv_to_dataframe(csv_path):
    """
    Load temperature data from a CSV file into a pandas DataFrame.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        pandas.DataFrame: DataFrame containing the temperature data
    """
    logger.info(f"Loading data from {csv_path}")
    
    try:
        # Read the CSV file into a DataFrame
        df = pd.read_csv(csv_path)
        
        # Check if the required columns exist
        required_columns = ['timestamp_ms', 'temperature_celsius']
        
        if not all(col in df.columns for col in required_columns):
            logger.error(f"CSV file must contain columns: {required_columns}")
            return None
            
        logger.info(f"Successfully loaded {len(df)} records from CSV")
        return df
        
    except Exception as e:
        logger.error(f"Error loading CSV file: {e}")
        return None


def process_dataframe(df, sensor_type):
    """
    Process the DataFrame to prepare data for database insertion.
    
    Args:
        df: pandas.DataFrame containing temperature data
        sensor_type: Type of sensor (soil_temp, air_temp_humidity, etc.)
        
    Returns:
        pandas.DataFrame: Processed DataFrame ready for insertion
    """
    logger.info(f"Processing {len(df)} records for sensor type: {sensor_type}")
    
    try:
        # Convert timestamp from milliseconds to datetime
        df['created_at'] = pd.to_datetime(df['timestamp_ms'], unit='ms')
        
        # Prepare data for database insertion
        processed_data = []
        
        for index, row in df.iterrows():
            # Create the data payload based on sensor type
            if sensor_type == 'soil_temp':
                data = {
                    'temp_c': float(row['temperature_celsius']),
                    'timestamp': int(row['timestamp_ms'])
                }
            elif sensor_type == 'air_temp_humidity':
                # Simulate humidity data if not available
                humidity = row.get('humidity', 50.0 + 0.1 * float(row['temperature_celsius']))
                data = {
                    'temp_c': float(row['temperature_celsius']),
                    'humidity': float(humidity),
                    'timestamp': int(row['timestamp_ms'])
                }
            elif sensor_type == 'air_temp_humidity_barometer':
                # Simulate additional barometer data if not available
                humidity = row.get('humidity', 50.0 + 0.1 * float(row['temperature_celsius']))
                pressure = row.get('pressure', 1013.25 + float(row['temperature_celsius']) * 0.2)
                data = {
                    'temp_c': float(row['temperature_celsius']),
                    'humidity': float(humidity),
                    'pressure': float(pressure),
                    'altitude': row.get('altitude', 0.0),
                    'timestamp': int(row['timestamp_ms'])
                }
            else:
                # Default fallback
                data = {
                    'temp_c': float(row['temperature_celsius']),
                    'timestamp': int(row['timestamp_ms'])
                }
                
            processed_data.append({
                'sensor_type': sensor_type,
                'data': data,
                'created_at': row['created_at']
            })
        
        return processed_data
    
    except Exception as e:
        logger.error(f"Error processing data: {e}")
        return []


def insert_data_to_db(processed_data, batch_size=100):
    """
    Insert processed data into the database.
    
    Args:
        processed_data: List of dictionaries with sensor data
        batch_size: Number of records to insert in a batch
        
    Returns:
        int: Number of records successfully inserted
    """
    logger.info(f"Inserting {len(processed_data)} records into database in batches of {batch_size}")
    
    # Ensure the database and tables exist
    setup()
    
    insert_count = 0
    batch_count = 0
    
    # Process in batches to avoid memory issues with large datasets
    for i in range(0, len(processed_data), batch_size):
        batch = processed_data[i:i + batch_size]
        batch_count += 1
        
        logger.info(f"Processing batch {batch_count} with {len(batch)} records")
        
        for record in batch:
            try:
                # Add to database
                add_sensor_reading(record['sensor_type'], record['data'])
                insert_count += 1
            except Exception as e:
                logger.error(f"Error inserting record: {e}")
    
    logger.info(f"Successfully inserted {insert_count} out of {len(processed_data)} records")
    return insert_count


def main():
    """Main function to load and process temperature data."""
    # Parse command line arguments
    args = parse_arguments()
    
    # Load CSV data into a DataFrame
    csv_path = args.csv_file
    sensor_type = args.sensor_type
    batch_size = args.batch_size
    
    logger.info(f"Starting temperature data import from {csv_path}")
    
    # Ensure the CSV file exists
    if not os.path.exists(csv_path):
        logger.error(f"CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Load and process the data
    df = load_csv_to_dataframe(csv_path)
    if df is None:
        sys.exit(1)
    
    # Process the DataFrame
    processed_data = process_dataframe(df, sensor_type)
    if not processed_data:
        logger.error("No data to insert after processing")
        sys.exit(1)
    
    # Insert data into the database
    insert_count = insert_data_to_db(processed_data, batch_size)
    
    logger.info(f"Data import complete. {insert_count} records inserted.")


if __name__ == "__main__":
    main()

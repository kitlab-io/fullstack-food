#!/usr/bin/env python3
"""
Test for the load_temperature_data.py script.

This script tests the functionality of the load_temperature_data.py script
by verifying that it correctly loads data from a CSV file and inserts it
into the database.
"""

import os
import sys
import unittest
import tempfile
import pandas as pd
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the required modules
from core.load_temperature_data import (
    load_csv_to_dataframe,
    process_dataframe,
    insert_data_to_db
)
from datastore import Base, engine, Session, SensorReading


class TestLoadTemperatureData(unittest.TestCase):
    """Test case for the load_temperature_data module."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary CSV file with test data
        self.temp_file = tempfile.NamedTemporaryFile(suffix='.csv', delete=False)
        
        # Create test data
        test_data = {
            'timestamp_ms': [1744518653000, 1744518713000, 1744518773000],
            'temperature_celsius': [19.32, 22.56, 21.91],
            'temperature_fahrenheit': [66.78, 72.60, 71.44]
        }
        
        # Write test data to CSV
        self.test_df = pd.DataFrame(test_data)
        self.test_df.to_csv(self.temp_file.name, index=False)
        
        # Set up a test database
        self.test_db_path = ':memory:'  # Use in-memory SQLite database for testing
        Base.metadata.create_all(engine)
        
        # Store the path to the real CSV file
        self.real_csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'tests/data/temperature_sensor_data.csv'
        )

    def tearDown(self):
        """Clean up after tests."""
        # Remove temporary CSV file
        if hasattr(self, 'temp_file') and os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_load_csv_to_dataframe(self):
        """Test loading CSV data into a DataFrame."""
        df = load_csv_to_dataframe(self.temp_file.name)
        
        # Check if DataFrame is returned
        self.assertIsNotNone(df)
        
        # Check if DataFrame has the correct number of rows
        self.assertEqual(len(df), 3)
        
        # Check if DataFrame has the correct columns
        self.assertTrue('timestamp_ms' in df.columns)
        self.assertTrue('temperature_celsius' in df.columns)

    def test_process_dataframe(self):
        """Test processing DataFrame."""
        df = load_csv_to_dataframe(self.temp_file.name)
        processed_data = process_dataframe(df, 'soil_temp')
        
        # Check if processed data is returned
        self.assertIsNotNone(processed_data)
        
        # Check if the correct number of records is processed
        self.assertEqual(len(processed_data), 3)
        
        # Check if the processed data has the correct format
        self.assertEqual(processed_data[0]['sensor_type'], 'soil_temp')
        self.assertEqual(processed_data[0]['data']['temp_c'], 19.32)
        self.assertEqual(processed_data[0]['data']['timestamp'], 1744518653000)
        
        # Test processing with different sensor types
        processed_air_temp = process_dataframe(df, 'air_temp_humidity')
        self.assertEqual(processed_air_temp[0]['sensor_type'], 'air_temp_humidity')
        self.assertTrue('humidity' in processed_air_temp[0]['data'])
        
        processed_baro = process_dataframe(df, 'air_temp_humidity_barometer')
        self.assertEqual(processed_baro[0]['sensor_type'], 'air_temp_humidity_barometer')
        self.assertTrue('pressure' in processed_baro[0]['data'])

    def test_insert_data_to_db(self):
        """Test inserting data into the database."""
        df = load_csv_to_dataframe(self.temp_file.name)
        processed_data = process_dataframe(df, 'soil_temp')
        
        # Insert data into the database
        insert_count = insert_data_to_db(processed_data, batch_size=2)
        
        # Check if all records were inserted
        self.assertEqual(insert_count, 3)
        
        # Verify records in the database
        session = Session()
        records = session.query(SensorReading).all()
        session.close()
        
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].sensor_type, 'soil_temp')

    def test_with_real_csv(self):
        """Test with the real CSV file if it exists."""
        if os.path.exists(self.real_csv_path):
            df = load_csv_to_dataframe(self.real_csv_path)
            
            # Check if DataFrame is returned
            self.assertIsNotNone(df)
            
            # Process a small sample of the data
            sample_df = df.head(5)
            processed_data = process_dataframe(sample_df, 'soil_temp')
            
            # Check if the processed data has the correct format
            self.assertEqual(processed_data[0]['sensor_type'], 'soil_temp')
            self.assertIn('temp_c', processed_data[0]['data'])
            self.assertIn('timestamp', processed_data[0]['data'])


if __name__ == '__main__':
    unittest.main()

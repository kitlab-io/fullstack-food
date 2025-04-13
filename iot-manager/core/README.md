# IoT Manager Core Module

The core module contains essential functionality for the IoT Manager system that is central to the application's operation but doesn't fit cleanly into other modules.

## Components

### Temperature Data Loader (`load_temperature_data.py`)

This script loads temperature readings from CSV files into the application's database. It supports different types of temperature sensors, including:

- Soil temperature sensors
- Air temperature and humidity sensors
- Barometric temperature and pressure sensors

#### Usage

```bash
# Basic usage with default file (tests/data/temperature_sensor_data.csv)
python load_temperature_data.py

# Specify a different CSV file
python load_temperature_data.py /path/to/your/data.csv

# Specify sensor type and batch size
python load_temperature_data.py --sensor_type air_temp_humidity --batch_size 50
```

#### CSV Format Requirements

The CSV file should have the following minimum columns:
- `timestamp_ms`: Timestamp in milliseconds since epoch
- `temperature_celsius`: Temperature readings in Celsius

Example CSV format:
```
timestamp_ms,temperature_celsius,temperature_fahrenheit
1744518653000,19.32,66.78
1744518713000,22.56,72.60
1744518773000,21.91,71.44
```

#### Additional Information

- The script automatically adds data to the SQLite database defined in `datastore.py`
- Batch processing is supported to handle large files efficiently
- Different sensor types will have their data formatted appropriately in the database
- For humidity and barometric sensors, if the data is not available in the CSV, reasonable simulated values will be generated based on the temperature

## Running Tests

Tests for the core module functionality can be run with:

```bash
# From the iot-manager directory
python -m unittest tests/test_load_temperature_data.py
```

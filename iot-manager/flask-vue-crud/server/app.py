import uuid
import json
import datetime
import sqlite3
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from utils import logger, load_yaml, base_dir
from system import load_config

BOOKS = [
    {
        'id': uuid.uuid4().hex,
        'title': 'On the Road',
        'author': 'Jack Kerouac',
        'read': True
    },
    {
        'id': uuid.uuid4().hex,
        'title': 'Harry Potter and the Philosopher\'s Stone',
        'author': 'J. K. Rowling',
        'read': False
    },
    {
        'id': uuid.uuid4().hex,
        'title': 'Green Eggs and Ham',
        'author': 'Dr. Seuss',
        'read': True
    }
]

# instantiate the app
app = Flask(__name__)
app.config.from_object(__name__)

# enable CORS
CORS(app, resources={r'/*': {'origins': '*'}})


def remove_book(book_id):
    for book in BOOKS:
        if book['id'] == book_id:
            BOOKS.remove(book)
            return True
    return False


# sanity check route
@app.route('/ping', methods=['GET'])
def ping_pong():
    return jsonify('pong!')


@app.route('/config', methods=['GET', 'POST'])
def config():
    response_object = {'status': 'success'}
    if request.method == 'POST':
        post_data = request.get_json()
        # BOOKS.append({
        #     'id': uuid.uuid4().hex,
        #     'title': post_data.get('title'),
        #     'author': post_data.get('author'),
        #     'read': post_data.get('read')
        # })
        response_object['message'] = 'Config updated!'
    else:
        config_protocols, config_devices = load_config()
        response_object['protocols'] = config_protocols
        response_object['devices'] = config_devices
        
    return jsonify(response_object)


@app.route('/books', methods=['GET', 'POST'])
def all_books():
    response_object = {'status': 'success'}
    if request.method == 'POST':
        post_data = request.get_json()
        BOOKS.append({
            'id': uuid.uuid4().hex,
            'title': post_data.get('title'),
            'author': post_data.get('author'),
            'read': post_data.get('read')
        })
        response_object['message'] = 'Book added!'
    else:
        response_object['books'] = BOOKS
    return jsonify(response_object)


@app.route('/books/<book_id>', methods=['PUT', 'DELETE'])
def single_book(book_id):
    response_object = {'status': 'success'}
    if request.method == 'PUT':
        post_data = request.get_json()
        remove_book(book_id)
        BOOKS.append({
            'id': uuid.uuid4().hex,
            'title': post_data.get('title'),
            'author': post_data.get('author'),
            'read': post_data.get('read')
        })
        response_object['message'] = 'Book updated!'
    if request.method == 'DELETE':
        remove_book(book_id)
        response_object['message'] = 'Book removed!'
    return jsonify(response_object)


@app.route('/api/sensor-data', methods=['GET'])
def get_sensor_data():
    response_object = {'status': 'success'}
    try:
        # Get query parameters for filtering
        sensor_type = request.args.get('type', 'soil_temp')
        days = float(request.args.get('days', 7))
        
        # Calculate date range
        end_date = datetime.datetime.now()
        
        # Handle both days and hours (days < 1 means hours)
        if days < 1:
            # Convert to hours (e.g., 0.042 days ≈ 1 hour)
            hours = round(days * 24)
            start_date = end_date - datetime.timedelta(hours=hours)
        else:
            start_date = end_date - datetime.timedelta(days=days)
        
        # Connect to the database
        db_path = Path(base_dir) / 'data' / 'sensordata.db'
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query sensor data
        cursor.execute(
            """
            SELECT id, sensor_type, raw_data, created_at
            FROM sensor_reading
            WHERE sensor_type = ? AND created_at >= ?
            ORDER BY created_at ASC
            """,
            (sensor_type, start_date.isoformat())
        )
        
        # Process the results
        data_points = []
        for row in cursor.fetchall():
            try:
                raw_data = json.loads(row['raw_data'])
                timestamp = int(datetime.datetime.fromisoformat(row['created_at']).timestamp() * 1000)
                
                # Extract the temperature value from raw_data
                if sensor_type == 'soil_temp' and 'temp_c' in raw_data:
                    temp_value = raw_data['temp_c']
                    data_points.append({
                        'timestamp': timestamp,
                        'value': temp_value
                    })
                elif sensor_type == 'air_temp_humidity' and 'temp_c' in raw_data:
                    temp_value = raw_data['temp_c']
                    data_points.append({
                        'timestamp': timestamp,
                        'value': temp_value
                    })
                elif sensor_type == 'air_temp_humidity_barometer' and 'temp_c' in raw_data:
                    temp_value = raw_data['temp_c']
                    data_points.append({
                        'timestamp': timestamp,
                        'value': temp_value
                    })
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error processing row {row['id']}: {e}")
                continue
        
        conn.close()
        
        response_object['data'] = data_points
        response_object['sensor_type'] = sensor_type
        
        print(data_points)
        
    except Exception as e:
        logger.error(f"Error fetching sensor data: {e}")
        response_object = {'status': 'error', 'message': str(e)}
        
    return jsonify(response_object)


@app.route('/api/photos', methods=['GET'])
def get_photos():
    response_object = {'status': 'success'}
    try:
        # Get query parameters for filtering
        days = float(request.args.get('days', 30))  # Default to 30 days
        plant_species = request.args.get('species')
        location = request.args.get('location')
        
        # Calculate date range
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days)
        
        # Connect to the database
        media_db_path = Path(base_dir) / 'data' / 'media.db'
        
        # Check if the database exists, if not, create it
        if not media_db_path.exists():
            from db_init_photos import init_db, init_sample_data
            init_db()
            init_sample_data()
            
        conn = sqlite3.connect(str(media_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build the query based on filters
        query = """
            SELECT id, filename, filepath, timestamp, plant_species, location, metadata, created_at
            FROM photos
            WHERE timestamp >= ?
        """
        params = [start_date.isoformat()]
        
        if plant_species:
            query += " AND plant_species LIKE ?"
            params.append(f"%{plant_species}%")
            
        if location:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")
            
        query += " ORDER BY timestamp DESC"
        
        # Execute the query
        cursor.execute(query, params)
        
        # Process the results
        photos = []
        for row in cursor.fetchall():
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            
            photos.append({
                'id': row['id'],
                'filename': row['filename'],
                'filepath': row['filepath'],
                'timestamp': row['timestamp'],
                'timestamp_ms': int(datetime.datetime.fromisoformat(row['timestamp']).timestamp() * 1000),
                'plant_species': row['plant_species'],
                'location': row['location'],
                'metadata': metadata,
                'created_at': row['created_at']
            })
        
        conn.close()
        
        # Get unique plant species and locations for filtering options
        conn = sqlite3.connect(str(media_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT plant_species FROM photos ORDER BY plant_species")
        species_list = [row['plant_species'] for row in cursor.fetchall()]
        
        cursor.execute("SELECT DISTINCT location FROM photos ORDER BY location")
        location_list = [row['location'] for row in cursor.fetchall()]
        
        conn.close()
        
        response_object['photos'] = photos
        response_object['filter_options'] = {
            'species': species_list,
            'locations': location_list
        }
        
    except Exception as e:
        logger.error(f"Error fetching photos: {e}")
        response_object = {'status': 'error', 'message': str(e)}
    
    return jsonify(response_object)


@app.route('/api/photos/<photo_id>', methods=['GET'])
def get_photo(photo_id):
    try:
        # Connect to the database
        media_db_path = Path(base_dir) / 'data' / 'media.db'
        conn = sqlite3.connect(str(media_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get the photo record
        cursor.execute("SELECT filepath FROM photos WHERE id = ?", (photo_id,))
        photo = cursor.fetchone()
        
        if not photo:
            return jsonify({'status': 'error', 'message': 'Photo not found'}), 404
        
        # Get the actual file path
        photo_path = Path(base_dir) / photo['filepath'].lstrip('/')
        
        if not photo_path.exists():
            return jsonify({'status': 'error', 'message': 'Photo file not found'}), 404
        
        # Return the file
        return send_file(str(photo_path))
        
    except Exception as e:
        logger.error(f"Error serving photo {photo_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run()

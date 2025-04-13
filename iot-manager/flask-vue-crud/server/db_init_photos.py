import sqlite3
import os
import json
import datetime
from pathlib import Path

# Get the base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Define the path to the new media database
MEDIA_DB_PATH = BASE_DIR / 'data' / 'media.db'

# Ensure the data directory exists
os.makedirs(os.path.dirname(MEDIA_DB_PATH), exist_ok=True)

# Create the SQLite database with photos table
def init_db():
    # Connect to the database (this will create it if it doesn't exist)
    conn = sqlite3.connect(str(MEDIA_DB_PATH))
    cursor = conn.cursor()
    
    # Create photos table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        plant_species TEXT,
        location TEXT,
        metadata TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create an index on the timestamp for efficient timeline queries
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_photos_timestamp ON photos(timestamp)')
    
    conn.commit()
    conn.close()
    
    print(f"Initialized photos database at {MEDIA_DB_PATH}")

# Initialize the sample data with the existing photos
def init_sample_data():
    photos_dir = BASE_DIR / 'photos'
    
    if not photos_dir.exists():
        print(f"Photos directory not found: {photos_dir}")
        return
        
    conn = sqlite3.connect(str(MEDIA_DB_PATH))
    cursor = conn.cursor()
    
    # Check if we already have data
    cursor.execute("SELECT COUNT(*) FROM photos")
    count = cursor.fetchone()[0]
    
    if count > 0:
        print(f"Database already contains {count} photos. Skipping sample data initialization.")
        conn.close()
        return
    
    # Get all jpg files from the photos directory
    photo_files = list(photos_dir.glob('*.jpg'))
    
    for photo_path in photo_files:
        filename = photo_path.name
        
        # Extract timestamp from filename if it follows the pattern or use file creation time
        if '_' in filename and ':' in filename:
            # Try to parse timestamp from filename like "-dev-video1_2592x1944_2025-04-06:01:09:39.114768Z.jpg"
            try:
                date_part = filename.split('_')[-1].split('.jpg')[0]
                timestamp = datetime.datetime.strptime(date_part, '%Y-%m-%d:%H:%M:%S.%fZ')
            except (ValueError, IndexError):
                # If parsing fails, use file creation time
                timestamp = datetime.datetime.fromtimestamp(os.path.getctime(photo_path))
        else:
            # Use file creation time for files without timestamp in name
            timestamp = datetime.datetime.fromtimestamp(os.path.getctime(photo_path))
        
        # Determine plant species and location from filename or use defaults
        if 'plant' in filename.lower():
            plant_species = 'Unknown Plant'
            location = 'Indoor Garden'
        else:
            plant_species = 'Garden Monitoring'
            location = 'Main Camera'
        
        # Create metadata JSON with image dimensions and other info
        metadata = json.dumps({
            'dimensions': '2592x1944' if '2592x1944' in filename else 'unknown',
            'source': 'Camera Capture',
            'device': filename.split('_')[0] if '_' in filename else 'unknown'
        })
        
        # Insert the photo data
        cursor.execute('''
        INSERT INTO photos (filename, filepath, timestamp, plant_species, location, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            filename,
            f'/photos/{filename}',
            timestamp.isoformat(),
            plant_species,
            location,
            metadata
        ))
    
    conn.commit()
    conn.close()
    
    print(f"Initialized sample data with {len(photo_files)} photos")

if __name__ == '__main__':
    init_db()
    init_sample_data()

from tests.mock.sensors import load_csv_to_dataframe, save_dataframe_to_sqlite
from pathlib import Path
from utils import base_dir

df = load_csv_to_dataframe(Path(*[base_dir,'tests','data','temperature_sensor_data.csv']))

save_dataframe_to_sqlite(df, database_path=Path(*[base_dir,'tests','data','temperature_sensor_data.db']),
                            table_name='temperature_readings', if_exists='replace')
import yaml
from pathlib import Path
from datetime import datetime, timezone

def load_yaml(path_yaml):
    with open(path_yaml, 'r') as file:
        data = yaml.safe_load(file)
    # print(data)
    return data

def now_str():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d:%H:%M:%S.%fZ')

import logging
# from test_div import test_division 

# get a custom logger & set the logging level
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

base_dir = Path(__file__).parent.resolve()
# Prints the directory containing the current file
print(f'base directorty: {base_dir}') 

log_filepath = Path(*[base_dir, 'system.log'])

# configure the handler and formatter as needed
log_file_mode = 'a+'
py_handler = logging.FileHandler(log_filepath, mode=log_file_mode)
py_formatter = logging.Formatter("%(name)s %(asctime)s %(levelname)s %(message)s")

# add formatter to the handler
py_handler.setFormatter(py_formatter)
# add handler to the logger
logger.addHandler(py_handler)

logger.info(f"Setup logger in module {__name__}")


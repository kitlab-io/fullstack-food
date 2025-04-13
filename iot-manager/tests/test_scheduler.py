from system import load_config, bind_devices, schedule_jobs, config_devices, config_protocols


devices = bind_devices(config_devices)
schedule_jobs(config_protocols, devices)
#!/usr/bin/with-contenv bashio
# Start the hub and the dashboard inside the add-on container.
# SKELETON: never run. Broker details come from the Mosquitto add-on through the Supervisor.
set -euo pipefail

SITE="$(bashio::config 'site')"
SITE_DIR="/config/${SITE}"
if [ ! -f "${SITE_DIR}/site.yaml" ]; then
  bashio::exit.nok "Put your site file at ${SITE_DIR}/site.yaml (addon_config folder of this add-on)"
fi

export FSF_MQTT_HOST="$(bashio::services mqtt 'host')"
export FSF_MQTT_PORT="$(bashio::services mqtt 'port')"
export FSF_MQTT_USERNAME="$(bashio::services mqtt 'username')"
export FSF_MQTT_PASSWORD="$(bashio::services mqtt 'password')"
# Home Assistant's ingress authenticates the user before a request reaches the add-on.
export FSF_WEB_NO_LOGIN=1

cd /app
python -m fsf_hub --site "${SITE_DIR}" --db /data/hub.db &
exec python -m fsf_web --site "${SITE_DIR}" --db /data/hub.db --host 0.0.0.0 --port 8080

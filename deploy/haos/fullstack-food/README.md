# Home Assistant OS add-on (skeleton)

This folder is a starting point, not a working add-on. It has never been built, installed
or started, and details of the add-on format here are from memory of the Home Assistant
documentation, not checked against it.

What it is meant to do:

- run the hub and the dashboard in one container on Home Assistant OS;
- use the Mosquitto broker add-on (login details come from the Supervisor);
- show the dashboard through Home Assistant's ingress, which does the login, so the
  dashboard's own login is switched off;
- read the site file from the add-on's config folder: `<site>/site.yaml`.

Known gaps before it can work:

- The Dockerfile needs the repository root as build context, which the add-on store does
  not provide: it needs a published image or a repository layout made for add-ons.
- Nodes need their own logins in the Mosquitto add-on; `fsf init` writes a password and
  ACL file for a standalone Mosquitto, not for the add-on.
- Two processes in one container with no supervisor: if the hub exits, nothing restarts it.
- No Home Assistant entities are created (MQTT discovery is not implemented).

# Hub install targets

Nothing here has been run on the hardware it names. Each item says what is known.

| Target | How | State |
|---|---|---|
| Any machine with Docker | `deploy/compose/base.yaml` + `mock.yaml` | Works: this is the mock stack |
| Any Linux host, real site | `fsf init`, then `base.yaml` + `sbc.yaml` | The authenticated stack starts and the broker enforces logins and ACLs (checked on a development machine with Docker Desktop) |
| Raspberry Pi OS Bookworm, 64-bit | `provision.sh`, then as above | Script written, never run |
| Armbian Bookworm on Orange Pi Zero 2W | `provision.sh`, then as above | Script written, never run |
| Home Assistant OS | add-on in `deploy/haos/` | Skeleton only, never built or installed |

## Raspberry Pi OS and Armbian

```
sudo ./provision.sh --hostname growhub --timezone Europe/Berlin
```

Then follow what the script prints: `fsf init`, edit the site, start the stack, `fsf doctor`.

Things to decide per target that the script does not do:

- **Storage**: by default the database is in a Docker volume on the SD card. For a USB or
  NVMe drive, mount it and point the `hub-data` volume at it. On an SD card, shorten
  `retention.raw_readings` in the site file.
- **Smart power strip**: the `fsf_kasa` bridge is not in the compose files yet. Run it on
  the hub host under a supervisor that restarts it, with `FSF_KASA_HOST` and the node's
  broker login from `sites/local/<site>/secrets.yaml`.
- **Orange Pi Zero 2W**: nothing board-specific is known to be needed. The 1 GB variant
  may be tight while the image builds; build elsewhere and load the image if so.
- **Updates and backups**: there is no `fsf update` or backup command yet. Update with
  `git pull` and `docker compose ... up -d --build`; copy the database from the
  `hub-data` volume to back it up.

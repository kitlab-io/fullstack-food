"""The MQTT topic contract. Payload schemas are in schemas/mqtt/."""

ROOT = "fsf"


def device(site: str, node: str, device_id: str, leaf: str) -> str:
    """leaf is one of: state (retained), cmd, ack."""
    return f"{ROOT}/{site}/{node}/{device_id}/{leaf}"


def node_status(site: str, node: str) -> str:
    """Retained. Payload is the plain string `online` or `offline` (set as the MQTT last will)."""
    return f"{ROOT}/{site}/{node}/status"


def zone_status(site: str, zone: str) -> str:
    return f"{ROOT}/{site}/zone/{zone}/status"


def hub_cmd(site: str) -> str:
    """Operator commands to the hub, e.g. {"id": "a1", "name": "advance_stage", "planting": "oyster-1"}.

    Payload: schemas/mqtt/hub_command.schema.json.
    """
    return f"{ROOT}/{site}/hub/cmd"


def hub_reply(site: str) -> str:
    """The hub's answer to each command, carrying the command's id. Not retained."""
    return f"{ROOT}/{site}/hub/reply"


def hub_state(site: str) -> str:
    """Retained snapshot: plantings, actuators, pauses, overrides, hub version and tick time."""
    return f"{ROOT}/{site}/hub/state"


def clock(site: str) -> str:
    """Retained simulated time, published only by the simulator."""
    return f"{ROOT}/{site}/sim/clock"


def sim_state(site: str) -> str:
    """Retained, published only by the simulator: speed, pause and the faults currently injected.
    Its presence is how the dashboard knows it is looking at a simulated site."""
    return f"{ROOT}/{site}/sim/state"


def sim_cmd(site: str) -> str:
    """Commands to the simulator (schemas/mqtt/sim_command.schema.json): speed, pause, fault injection."""
    return f"{ROOT}/{site}/sim/cmd"


def matches(pattern: str, topic: str) -> bool:
    """MQTT topic filter matching with + and # wildcards."""
    p_parts, t_parts = pattern.split("/"), topic.split("/")
    for i, p in enumerate(p_parts):
        if p == "#":
            return True
        if i >= len(t_parts) or (p != "+" and p != t_parts[i]):
            return False
    return len(p_parts) == len(t_parts)

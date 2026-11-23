"""The smart power strip bridge keeps the same contract as any other node (installation plan I6)."""

import copy
import json

import pytest

from fsf_core import ConfigError, InMemoryBus, VirtualClock, find_repo_root, load_site, topics
from fsf_core.nodetest import NodeContract
from fsf_kasa import MemoryBackend, PlugBridge

NODE = "plug-strip"


@pytest.fixture
def strip(catalog):
    site = load_site(find_repo_root() / "sites/examples/mushrooms", catalog)
    bus, clock, backend = InMemoryBus(), VirtualClock(), MemoryBackend()
    bridge = PlugBridge(site, NODE, bus, clock, backend)
    bridge.start()

    def wait(seconds: float) -> None:
        for _ in range(max(1, int(seconds))):
            clock.advance(1)
            bridge.tick()

    return site, bus, clock, backend, bridge, wait


def command(bus, device: str, **cmd) -> dict:
    acks: list[dict] = []
    bus.subscribe(topics.device("mushrooms", NODE, device, "ack"), lambda t, p: acks.append(json.loads(p)))
    bus.publish(topics.device("mushrooms", NODE, device, "cmd"), {"id": f"c{len(cmd)}{cmd.get('duration_s', '')}", **cmd})
    return acks[-1]


def test_the_bridge_passes_the_node_contract_suite(strip, catalog):
    site, bus, _, backend, _, wait = strip
    checks = NodeContract(site, catalog, NODE, bus, wait).run(actuate=True)
    failed = [str(c) for c in checks if not c.ok]
    assert not failed, "\n".join(failed)
    assert sum("switches off by itself when the lease ends" in c.name for c in checks) == 2
    assert backend.on == [False] * 6                    # nothing left running


def test_an_outlet_is_switched_off_when_its_lease_ends_without_the_hub(strip):
    _, bus, _, backend, _, wait = strip
    assert command(bus, "inc-heater", name="on", duration_s=180)["ok"]
    assert backend.on[0] and not backend.on[1]          # outlet 0, as the site file says
    wait(179)
    assert backend.on[0]
    wait(2)                                             # no further command arrives: the bridge ends it
    assert not backend.on[0]
    state = json.loads(bus._retained[topics.device("mushrooms", NODE, "inc-heater", "state")])
    assert state["on"] is False


def test_a_renewed_lease_keeps_it_on_and_is_capped(strip):
    _, bus, clock, backend, bridge, wait = strip
    command(bus, "inc-heater", name="on", duration_s=180)
    wait(90)
    command(bus, "inc-heater", name="on", duration_s=180)
    wait(170)
    assert backend.on[0]
    command(bus, "fr-humidifier", name="on", duration_s=999999)
    assert (bridge.lease_until["fr-humidifier"] - clock.now()).total_seconds() == 3600


def test_an_unreachable_strip_is_reported_not_hidden(strip):
    _, bus, _, backend, bridge, wait = strip
    backend.fail = True
    ack = command(bus, "inc-heater", name="on", duration_s=60)
    assert ack == {"id": ack["id"], "ok": False, "error": "strip unreachable"}
    assert "inc-heater" not in bridge.lease_until
    wait(61)
    assert bus._retained[topics.node_status("mushrooms", NODE)] == b"offline"
    backend.fail = False
    wait(61)
    assert bus._retained[topics.node_status("mushrooms", NODE)] == b"online"


def test_a_lease_that_ends_while_the_strip_is_unreachable_is_retried(strip):
    _, bus, _, backend, _, wait = strip
    command(bus, "inc-heater", name="on", duration_s=30)
    backend.fail = True
    wait(40)
    assert backend.on[0]                                # the known weakness: it could not be switched off
    backend.fail = False
    wait(1)
    assert not backend.on[0]                            # off at the first chance


def test_starting_stopping_and_stray_outlets_all_end_off(strip):
    site, bus, clock, backend, bridge, wait = strip
    backend.on[1] = True                                # someone pressed the button on the strip
    wait(61)
    assert not backend.on[1]                            # on without a lease does not stay on
    command(bus, "inc-heater", name="on", duration_s=600)
    bridge.stop()
    assert backend.on == [False] * 6 and bus._retained[topics.node_status("mushrooms", NODE)] == b"offline"

    backend.on[0] = True                                # left on by a crash
    PlugBridge(site, NODE, InMemoryBus(), clock, backend).start()
    assert not backend.on[0]


def test_outlets_are_validated_in_the_site_file(tmp_path, catalog):
    import yaml
    raw = yaml.safe_load((find_repo_root() / "sites/examples/mushrooms/site.yaml").read_text(encoding="utf-8"))

    def problems(mutate) -> str:
        changed = copy.deepcopy(raw)
        mutate(next(n for n in changed["nodes"] if n["id"] == NODE)["devices"])
        path = tmp_path / "site.yaml"
        path.write_text(yaml.safe_dump(changed), encoding="utf-8")
        with pytest.raises(ConfigError) as err:
            load_site(path, catalog)
        return "\n".join(err.value.problems)

    assert "outlet 1 is already used by inc-heater" in problems(lambda d: d[0].update(outlet=1))
    assert "outlet 6 does not exist on tplink.kasa-hs300 (0..5)" in problems(lambda d: d[0].update(outlet=6))
    assert "devices on a smart power strip need an outlet number" in problems(lambda d: d[0].pop("outlet"))


def test_a_mains_load_wired_to_a_real_board_gets_a_warning(tmp_path, catalog):
    import yaml
    raw = yaml.safe_load((find_repo_root() / "sites/examples/mushrooms/site.yaml").read_text(encoding="utf-8"))
    strip_node = next(n for n in raw["nodes"] if n["id"] == NODE)
    heater = strip_node["devices"].pop(0)
    heater.pop("outlet")
    raw["nodes"][0]["devices"].append(heater)
    raw["nodes"][0]["runtime"] = "esphome"
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    site = load_site(path, catalog)
    assert site.warnings == ["device inc-heater: a mains load on node incubation-node has no certified switch; "
                             "put it on a smart power strip node"]

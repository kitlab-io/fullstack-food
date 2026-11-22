import copy

import pytest
import yaml

from fsf_core import ConfigError, InMemoryBus, find_repo_root, load_site, resolve_recipe, seconds, topics
from fsf_core.recipes import deep_merge


def test_durations():
    assert seconds("30s") == 30
    assert seconds("5m") == 300
    assert seconds("1.5h") == 5400
    assert seconds("14d") == 14 * 86400
    assert seconds(None, default=7) == 7
    with pytest.raises(ValueError):
        seconds("soon")


def test_topic_matching():
    assert topics.matches("fsf/home/+/+/state", "fsf/home/node1/soil/state")
    assert not topics.matches("fsf/home/+/+/state", "fsf/home/node1/status")
    assert not topics.matches("fsf/home/+/status", "fsf/home/zone/tray1/status")
    assert topics.matches("fsf/#", "fsf/home/zone/tray1/status")


def test_bus_delivers_retained_messages_to_late_subscribers():
    bus = InMemoryBus()
    bus.publish("a/b", {"x": 1}, retain=True)
    bus.publish("a/c", {"x": 2})
    seen = []
    bus.subscribe("a/+", lambda topic, payload: seen.append(topic))
    assert seen == ["a/b"]


def test_deep_merge_merges_lists_by_id():
    base = {"control": [{"id": "watering", "limits": {"min_interval": "24h", "max_daily_ml": 300}}]}
    over = {"control": [{"id": "watering", "limits": {"max_daily_ml": 150}}, {"id": "new", "x": 1}]}
    merged = deep_merge(base, over, add_new_list_items=False)
    assert merged["control"] == [{"id": "watering", "limits": {"min_interval": "24h", "max_daily_ml": 150}}]
    assert base["control"][0]["limits"]["max_daily_ml"] == 300      # inputs untouched


def test_recipe_layers_resolve_in_order(catalog):
    recipe = catalog.get("Recipe", "pothos.steady")
    species = catalog.get("Species", "pothos")
    goal = catalog.get("Goal", "vacation")
    overrides = {"targets": {"soil_moisture": {"max": 70}}}
    resolved = resolve_recipe(recipe, species, goal, overrides)

    assert resolved["layers"] == ["species:pothos", "recipe:pothos.steady", "goal:vacation", "planting:overrides"]
    (stage,) = resolved["stages"]
    assert stage["id"] == "steady"
    watering = stage["control"][0]
    assert watering["limits"] == {"min_interval": "48h", "max_daily_ml": 150}      # goal overlay
    assert watering["dose"] == {"volume_ml": 150}                                  # recipe
    assert stage["targets"]["soil_moisture"] == {"min": 25, "max": 70}             # planting override
    assert stage["alerts"] == [{"status": "critical", "quantity": "air_temperature", "below": 10}]  # species default


def test_goal_overlay_does_not_add_loops_a_stage_lacks(catalog):
    recipe = catalog.get("Recipe", "blue-oyster.standard")
    resolved = resolve_recipe(recipe, catalog.get("Species", "blue-oyster"), catalog.get("Goal", "quiet"))
    stages = {s["id"]: s for s in resolved["stages"]}
    assert [loop["id"] for loop in stages["incubation"]["control"]] == ["heat"]
    fresh_air = next(loop for loop in stages["fruiting"]["control"] if loop["id"] == "fresh_air")
    assert (fresh_air["on_for"], fresh_air["every"]) == ("1m", "30m")
    assert fresh_air["actuator"] == "actuator.fan"


def test_site_goal_is_applied_to_planting(catalog):
    site = load_site(find_repo_root() / "sites/examples/houseplants", catalog)
    watering = site.plantings["snake-1"].recipe["stages"][0]["control"][0]
    assert watering["limits"] == {"min_interval": "48h", "max_daily_ml": 150}


def _broken_site(tmp_path, catalog, mutate):
    raw = yaml.safe_load((find_repo_root() / "sites/examples/houseplants/site.yaml").read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    mutate(raw)
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        load_site(path, catalog)
    return "\n".join(err.value.problems)


def test_site_validation_reports_schema_errors(tmp_path, catalog):
    def mutate(raw):
        raw["zones"][0]["kind"] = "greenhouse"
    assert "greenhouse" in _broken_site(tmp_path, catalog, mutate)


def test_site_validation_reports_all_cross_reference_errors(tmp_path, catalog):
    def mutate(raw):
        devices = raw["nodes"][0]["devices"]
        devices[0]["model"] = "acme.does-not-exist"                 # unknown model
        devices[1]["as"] = "sensor.co2"                             # model does not implement role
        del devices[2]["flow_ml_per_s"]                             # pump without flow rate
        raw["zones"][1]["indicator"]["leds"] = [5, 12]              # overlaps the other zone
        raw["plantings"][0]["recipe"] = "snake-plant.steady"        # recipe for another species
    problems = _broken_site(tmp_path, catalog, mutate)
    for expected in ("unknown model 'acme.does-not-exist'",
                     "does not implement 'sensor.co2'",
                     "pumps need flow_ml_per_s",
                     "overlap zone pothos-window",
                     "recipe snake-plant.steady is for snake-plant, not pothos"):
        assert expected in problems


def test_site_validation_requires_actuators_for_recipe_loops(tmp_path, catalog):
    def mutate(raw):
        raw["zones"][0]["devices"].remove("pothos-pump")
    assert "loop watering needs actuator.pump in zone pothos-window" in _broken_site(tmp_path, catalog, mutate)

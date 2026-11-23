"""Studio plan S2: the scenario runner itself. A runner that passes everything proves nothing,
so most of this checks that a wrong expectation fails and says what was seen instead."""

import json
import shutil
import textwrap

import pytest

from fsf_core import ConfigError, find_repo_root, seconds
from fsf_core.__main__ import main
from fsf_sim import load_scenario, run_scenario
from fsf_sim.scenario import merge, span


@pytest.fixture
def write(tmp_path):
    """write(site, name, body) -> path of a scenario file in a copy of an example site."""
    def make(site: str, name: str, body: str):
        folder = tmp_path / site
        if not folder.exists():
            shutil.copytree(find_repo_root() / "sites" / "examples" / site, folder, ignore=shutil.ignore_patterns("scenarios"))
        (folder / "scenarios").mkdir(exist_ok=True)
        path = folder / "scenarios" / f"{name}.yaml"
        path.write_text(f"kind: Scenario\nid: {name}\n" + textwrap.dedent(body), encoding="utf-8")
        return path
    return make


def outcomes(result) -> dict[str, tuple[bool, str]]:
    return {e.text: (e.ok, e.detail) for e in result.expectations}


def test_durations_may_be_compound():
    assert seconds("1h30m") == 5400 and seconds("14d3h5m") == 14 * 86400 + 3 * 3600 + 300 and seconds("2d") == 172800
    assert span(5400) == "1h 30m" and span(0) == "0"
    for bad in ("", "h", "5", "5x", "1h30"):
        with pytest.raises(ValueError):
            seconds(bad)


def test_the_environment_is_laid_over_the_sites_own():
    base = {"seed": 1, "zones": {"a": {"enclosure": "open", "soil": {"initial": 30, "ml_per_percent": 12}}}}
    assert merge(base, {"zones": {"a": {"soil": {"initial": 20}}}, "seed": 2}) == {
        "seed": 2, "zones": {"a": {"enclosure": "open", "soil": {"initial": 20, "ml_per_percent": 12}}}}
    assert base["zones"]["a"]["soil"]["initial"] == 30


# Each line is a pair: an expectation that holds for this run, and one that must fail.
PAIRS = [
    ("{ at: 10m, zone: pothos-window, status: needs_water }", "{ at: 10m, zone: pothos-window, status: ok }"),
    ("{ at: 10m, zone: pothos-window, status_not: ok }", "{ at: 10m, zone: pothos-window, status_not: needs_water }"),
    ("{ by: 30m, zone: pothos-window, status: needs_water }", "{ by: 30m, zone: pothos-window, status: critical }"),
    ("{ to: 2h, zone: snake-shelf, status: ok }", "{ zone: pothos-window, status: ok }"),
    ("{ at: 10m, zone: pothos-window, active: [needs_water] }", "{ at: 10m, zone: pothos-window, active: [needs_water, too_cold] }"),
    ("{ at: 10m, zone: pothos-window, active_not: too_cold }", "{ at: 10m, zone: pothos-window, active_not: [too_cold, needs_water] }"),
    ("{ at: 10m, zone: pothos-window, active_is: needs_water }", "{ at: 10m, zone: pothos-window, active_is: [needs_water, too_cold] }"),
    ("{ at: 10m, zone: pothos-window, stage: steady }", "{ at: 10m, zone: pothos-window, stage: flowering }"),
    ("{ at: 10m, zone: pothos-window, led: { status: needs_water, effect: breathe } }",
     "{ at: 10m, zone: pothos-window, led: { status: needs_water, effect: blink } }"),
    ("{ at: 3h, zone: pothos-window, led_sequence: [ok, needs_water, ok] }", "{ at: 3h, zone: pothos-window, led_sequence: [ok] }"),
    ("{ at: 3h, zone: pothos-window, soil_moisture: { min: 30 } }", "{ at: 3h, zone: pothos-window, soil_moisture: { max: 30 } }"),
    ("{ zone: pothos-window, soil_moisture: { min: 25, share: 0.5 } }", "{ zone: pothos-window, soil_moisture: { min: 25, share: 0.99 } }"),
    ("{ zone: pothos-window, air_temperature: { min: 15, max: 30 } }", "{ zone: pothos-window, air_temperature: { min: 22 } }"),
    ("{ at: 3h, device: pothos-pump, is_on: false }", "{ at: 3h, device: pothos-pump, is_on: true }"),
    ("{ by: 3h, device: pothos-pump, is_on: true }", "{ by: 3h, device: snake-pump, is_on: true }"),
    ("{ device: pothos-pump, max_continuous_on: 2m }", "{ device: pothos-pump, max_continuous_on: 5s }"),
    ("{ device: pothos-pump, on_time: { min: 10s, max: 5m } }", "{ device: pothos-pump, on_time: { max: 0s } }"),
    ("{ from: 2h, device: pothos-pump, on_time: { max: 0s } }", "{ from: 10m, device: pothos-pump, on_time: { max: 0s } }"),
    ("{ at: 3h, device: pothos-pump, delivered_ml: { min: 147, max: 153 } }", "{ at: 3h, device: pothos-pump, delivered_ml: { max: 100 } }"),
    ("{ from: 10m, to: 3h, device: pothos-pump, delivered_ml: { min: 147 } }", "{ from: 2h, to: 3h, device: pothos-pump, delivered_ml: { min: 1 } }"),
    ("{ at: 3h, device: pothos-pump, level: 1.0 }", "{ at: 3h, device: pothos-pump, level: 0.3 }"),
    ("{ from: 2h, device: pothos-pump, on_between: ['00:00', '00:01'] }", "{ from: 2h, device: pothos-pump, on_between: ['09:00', '12:00'] }"),
    ("{ at: 3h, strip: status-strip, brightness: 0.5 }", "{ at: 3h, strip: status-strip, brightness: 0.9 }"),
    ("{ at: 3h, planting: pothos-1, stage: steady }", "{ at: 3h, planting: pothos-1, stage: null }"),
    ("{ at: 3h, planting: pothos-1, in_zone: pothos-window }", "{ at: 3h, planting: pothos-1, in_zone: snake-shelf }"),
    ("{ event: dose }", "{ event: stage_advanced }"),
    ("{ event: dose, zone: pothos-window, count: 1 }", "{ event: dose, zone: pothos-window, count: 2 }"),
    ("{ event: dose, count: { max: 1 } }", "{ event: dose, count: { min: 2 } }"),
    ("{ no_event: dose, zone: snake-shelf }", "{ no_event: dose }"),
    ("{ to: 30m, no_event: dose }", "{ from: 30m, no_event: dose }"),
    ("{ event: dose, where: { volume_ml: 150 } }", "{ event: dose, where: { volume_ml: 151 } }"),
    ("{ event: command, contains: { by: scen } }", "{ event: command, contains: { by: dashboard } }"),
    ("{ event: dose, values: { volume_ml: [150] } }", "{ event: dose, values: { volume_ml: [150, 150] } }"),
    ("{ event: command, offsets: [2h30m] }", "{ event: command, offsets: [2h] }"),
    ("{ event: dose, rolling: { field: volume_ml, window: 24h, max: 150 } }", "{ event: dose, rolling: { field: volume_ml, window: 24h, max: 149 } }"),
]


def test_every_kind_of_check_passes_when_true_and_fails_when_not(write, catalog):
    body = textwrap.dedent("""\
        duration: 3h
        timeline:
          - { at: 0, do: set_zone, zone: pothos-window, soil_moisture: 20 }
          - { at: 2h30m, command: pause_zone, zone: snake-shelf, duration: 10m }
        expect:
        """)
    good = run_scenario(write("houseplants", "good", body + "".join(f"  - {a}\n" for a, _ in PAIRS)), catalog)
    assert good.passed, good.report()
    bad = run_scenario(write("houseplants", "bad", body + "".join(f"  - {b}\n" for _, b in PAIRS)), catalog)
    assert [e.text for e in bad.expectations if e.ok] == []
    assert not bad.passed and len(bad.failures()) == len(PAIRS)
    seen = outcomes(bad)
    assert seen["at 10m: zone pothos-window: status ok"] == (False, "at 10m status was needs_water")
    assert seen["by 30m: zone pothos-window: status critical"] == (False, "never; at the end status was needs_water")
    assert seen["throughout: zone pothos-window: status ok"][1].startswith("at 6m status was needs_water (and at ")
    assert seen["throughout: events dose in pothos-window: count 2"] == (False, "there were 1")
    assert seen["at 3h: zone pothos-window: led_sequence [ok]"] == (False, "it showed ok, needs_water, ok")
    assert "FAIL  at 10m: zone pothos-window: status ok" in bad.report()


def test_two_short_doses_apart_fail_a_minimum_gap(write, catalog):
    result = run_scenario(write("microgreens", "gap", """\
        duration: 1d
        expect:
          - { event: dose, zone: tray1, min_gap: 2h }
          - { event: dose, zone: tray1, min_gap: 1d }
        """), catalog)
    assert [e.ok for e in result.expectations] == [True, False]
    assert "the shortest gap was" in result.expectations[1].detail


def test_commands_go_through_the_hub_and_a_refusal_fails_the_run_unless_expected(write, catalog):
    result = run_scenario(write("houseplants", "commands", """\
        duration: 30m
        timeline:
          - { at: 5m, command: set_override, zone: pothos-window, quantity: soil_moisture, min: 5, duration: 1h, refused: true }
          - { at: 5m, command: set_override, zone: pothos-window, quantity: soil_moisture, min: 5, duration: 1h }
          - { at: 10m, command: pause_zone, zone: pothos-window, refused: true }
          - { at: 15m, command: advance_stage, planting: pothos-1, result: { stage: flowering } }
          - { at: 20m, do: stop_hub }
          - { at: 25m, command: resume_zone, zone: pothos-window }
        expect:
          - { at: 30m, event: command_rejected, count: 2 }
        """), catalog)
    assert [e["ok"] for e in result.timeline] == [True, False, False, False, True, False]
    assert [e["text"].split()[0] for e in result.timeline] == ["command"] * 4 + ["stop_hub", "command"]
    details = [e["detail"] for e in result.timeline]
    assert "below the species limit" in details[0] and details[1].startswith("the hub refused it: soil_moisture min 5 is below")
    assert details[2] == "the hub accepted it, but it was expected to refuse"
    assert "expected stage flowering" in details[3]
    assert details[5] == "the hub is stopped, so nothing answered"
    assert not result.passed and result.expectations[0].ok
    assert sum(f.startswith("timeline at ") for f in result.failures()) == 4


def test_a_hub_restart_in_a_scenario_keeps_its_state(write, catalog):
    result = run_scenario(write("microgreens", "restart", """\
        duration: 4d1h
        timeline:
          - { at: 2d12h, do: stop_hub }
          - { at: 2d14h, do: start_hub }
        expect:
          - { at: 2d12h, planting: radish-1, stage: blackout }
          - { at: 2d13h, planting: radish-1, stage: blackout, note: Still known while the hub is down }
          - { at: 2d13h, zone: tray1, stage: blackout }
          - { at: 2d14h30m, planting: radish-1, stage: blackout }
          - { from: 2d12h30m, to: 2d14h, no_event: dose }
          - { at: 4d1h, event: stage_advanced, offsets: [2d, 4d], note: "Four days after sowing, not after the restart" }
          - { at: 4d1h, event: planting_started, count: 1 }
          - { at: 4d1h, zone: tray1, status: ok }
        """), catalog)
    assert result.passed, result.report()


def test_a_run_can_leave_its_database_and_result_behind(write, catalog, tmp_path):
    path = write("houseplants", "kept", """\
        title: Kept for the dashboard
        duration: 1h
        timeline:
          - { at: 30m, do: set_ambient, air_temperature: 7, note: Window open }
        expect:
          - { at: 1h, zone: pothos-window, status: critical }
        """)
    out = tmp_path / "out"
    result = run_scenario(path, catalog, out_dir=out)
    saved = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert saved == result.to_dict() and saved["passed"] and saved["title"] == "Kept for the dashboard"
    assert saved["timeline"] == [{"at": "30m", "t": "2026-03-01T08:30:00+00:00", "ok": True, "detail": "",
                                  "text": "set_ambient air_temperature=7", "note": "Window open"}]
    assert "not measured from a real site" in saved["note"]
    assert (out / "hub.db").stat().st_size > 0 and result.system is None
    assert run_scenario(path, catalog, out_dir=out).passed          # running again replaces the old database


PROBLEMS = [
    ("expect:\n  - { at: 10m, zone: nowhere, status: ok }", "unknown zone 'nowhere'"),
    ("expect:\n  - { at: 10m, zone: pothos-window, status: thirsty }", "unknown status 'thirsty'"),
    ("expect:\n  - { at: 10m, device: reservoir-level, is_on: true }", "reservoir-level is not an actuator"),
    ("expect:\n  - { at: 2h, zone: pothos-window, status: ok }", "2h is after the end of the run (1h)"),
    ("expect:\n  - { at: 10s, zone: pothos-window, status: ok }", "10s is not a multiple of the 30 s tick"),
    ("expect:\n  - { at: 10m, status: ok }", "name one of zone, device, strip, planting, event or no_event"),
    ("expect:\n  - { at: 10m, zone: pothos-window }", "give exactly one check of the zone"),
    ("expect:\n  - { at: 10m, zone: pothos-window, status: ok, stage: steady }", "give exactly one check of the zone"),
    ("expect:\n  - { at: 10m, zone: pothos-window, is_on: true }", "is_on cannot be checked of a zone"),
    ("expect:\n  - { at: 10m, by: 20m, zone: pothos-window, status: ok }", "give at, or by, or a window"),
    ("expect:\n  - { from: 30m, to: 10m, zone: pothos-window, status: ok }", "from is after to"),
    ("expect:\n  - { by: 10m, event: dose }", "use at, not by, for this check"),
    ("expect:\n  - { at: 10m, device: pothos-pump, max_continuous_on: 1m }", "max_continuous_on is checked over a window"),
    ("expect:\n  - { zone: pothos-window, led_sequence: [ok] }", "led_sequence needs at"),
    ("expect:\n  - { at: 10m, zone: pothos-window, soil_moisture: { min: 1, share: 0.5 } }", "share is for a window"),
    ("expect:\n  - { at: 10m, zone: pothos-window, on: true }", "Additional properties are not allowed (True was unexpected)"),
    ("expect:\n  - { no_event: dose, count: 1 }", "no_event takes no further checks"),
    ("timeline:\n  - { at: 5m, do: sensor_stuck, device: pothos-soil }\nexpect:\n  - { event: dose }", "sensor_stuck needs quantity"),
    ("timeline:\n  - { at: 5m, do: set_ambient, zone: pothos-window }\nexpect:\n  - { event: dose }", "set_ambient does not take zone"),
    ("timeline:\n  - { at: 5m, do: set_reservoir, device: reservoir-level }\nexpect:\n  - { event: dose }", "set_reservoir needs volume_ml or percent"),
    ("timeline:\n  - { at: 5m, do: explode }\nexpect:\n  - { event: dose }", "'explode' is not one of"),
    ("timeline:\n  - { at: 5m, command: open_window }\nexpect:\n  - { event: dose }", "unknown hub command 'open_window'"),
    ("timeline:\n  - { at: 5m, do: node_offline, node: attic }\nexpect:\n  - { event: dose }", "unknown node 'attic'"),
    ("site: mushrooms\nexpect:\n  - { event: dose }", "site is 'mushrooms' but the file is in the folder of site 'houseplants'"),
]


@pytest.mark.parametrize("body, problem", PROBLEMS, ids=[p for _, p in PROBLEMS])
def test_a_scenario_that_cannot_mean_anything_is_refused_before_it_runs(write, catalog, body, problem):
    with pytest.raises(ConfigError) as caught:
        load_scenario(write("houseplants", "broken", "duration: 1h\n" + body), catalog)
    assert problem in str(caught.value), caught.value.problems


def test_a_scenario_must_sit_in_a_site_and_be_named_like_its_file(write, catalog, tmp_path):
    path = write("houseplants", "fine", "duration: 1h\nexpect:\n  - { event: dose }\n")
    stray = tmp_path / "stray.yaml"
    shutil.copyfile(path, stray)
    with pytest.raises(ConfigError, match="lives in <site>/scenarios/"):
        load_scenario(stray, catalog)
    renamed = path.with_name("other.yaml")
    path.rename(renamed)
    with pytest.raises(ConfigError, match="id 'fine' must match the file name"):
        load_scenario(renamed, catalog)


def test_the_command_line_runs_scenarios_and_validate_checks_them(write, capsys):
    passing = write("houseplants", "passing", "duration: 30m\nexpect:\n  - { at: 30m, zone: pothos-window, status: ok }\n")
    assert main(["scenario", "run", str(passing)]) == 0
    assert "scenario passing on site houseplants: passed (30m simulated)" in capsys.readouterr().out

    write("houseplants", "failing", "duration: 30m\nexpect:\n  - { at: 30m, zone: pothos-window, status: critical }\n")
    assert main(["scenario", "run", str(passing.parent.parent)]) == 1          # a site folder: all of its scenarios
    out = capsys.readouterr().out
    assert "FAIL  at 30m: zone pothos-window: status critical" in out and "at 30m status was ok" in out
    assert "1 of 2 scenarios passed" in out

    assert main(["validate", str(passing.parent.parent)]) == 0
    assert "2 scenarios: ok" in capsys.readouterr().out
    write("houseplants", "broken", "duration: 30m\nexpect:\n  - { at: 30m, zone: attic, status: ok }\n")
    assert main(["validate", str(passing.parent.parent)]) == 1
    out = capsys.readouterr().out
    assert "3 scenarios: INVALID" in out and "unknown zone 'attic'" in out
    assert main(["scenario", "run", str(passing.parent)]) == 1                  # a folder without scenarios of its own

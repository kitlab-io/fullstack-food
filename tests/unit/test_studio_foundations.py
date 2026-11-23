"""Studio plan S1: safety envelope, a site's own library, round-trip writing, revisions."""

import copy
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from fsf_core import Catalog, ConfigError, find_repo_root, load_site, yamlio
from fsf_studio import RevisionError, RevisionStore

ROOT = find_repo_root()
YAML_FILES = sorted((ROOT / "catalog").rglob("*.yaml")) + sorted((ROOT / "sites/examples").rglob("*.yaml"))


@pytest.fixture
def site_dir(tmp_path):
    """A copy of the house plants example that a test may change."""
    target = tmp_path / "my-plants"
    target.mkdir()
    shutil.copyfile(ROOT / "sites/examples/houseplants/site.yaml", target / "site.yaml")
    return target


def edit(path: Path, change) -> None:
    doc = yamlio.load(path)
    change(doc)
    yamlio.save(doc, path)


def problems(path: Path, catalog) -> str:
    with pytest.raises(ConfigError) as err:
        load_site(path, catalog)
    return "\n".join(err.value.problems)


# --------------------------------------------------------------------------- safety envelope

def test_every_example_species_has_limits_and_the_examples_fit_inside(catalog):
    for species in catalog.items["Species"].values():
        assert species.get("limits"), species["id"]
    for name in ("houseplants", "microgreens", "mushrooms"):
        load_site(ROOT / "sites/examples" / name, catalog)      # would raise if a band left its envelope


def test_a_planting_override_outside_the_envelope_is_rejected(site_dir, catalog):
    edit(site_dir / "site.yaml", lambda doc: doc["plantings"][0].update(
        overrides={"targets": {"air_temperature": {"max": 41}, "soil_moisture": {"min": 5}}}))
    text = problems(site_dir, catalog)
    assert "planting pothos-1: air_temperature max 41 is above the species limit of 35" in text
    assert "planting pothos-1: soil_moisture min 5 is below the species limit of 15" in text


def test_a_recipe_outside_the_envelope_is_rejected_when_the_library_loads(site_dir, catalog):
    recipe = copy.deepcopy(catalog.get("Recipe", "pothos.steady"))
    recipe.update(id="pothos.tropical")
    recipe["targets"]["air_temperature"] = {"min": 28, "max": 45}
    (site_dir / "library" / "recipes").mkdir(parents=True)
    (site_dir / "library" / "recipes" / "pothos.tropical.yaml").write_text(yaml.safe_dump(recipe), encoding="utf-8")
    assert "recipe pothos.tropical: air_temperature max 45 is above the species limit of 35" in problems(site_dir, catalog)


def test_site_wide_actuator_limits_bind_every_recipe_goal_and_override(site_dir, catalog):
    def raise_cap(doc):
        doc["plantings"][0]["overrides"] = {"control": [{"id": "watering", "limits": {"max_daily_ml": 900}}]}
    edit(site_dir / "site.yaml", raise_cap)
    assert ("planting pothos-1: stage steady loop watering: max_daily_ml must be set and at most 400 "
            "(site limit for actuator.pump)") in problems(site_dir, catalog)

    mushrooms = site_dir.parent / "shrooms"
    mushrooms.mkdir()
    shutil.copyfile(ROOT / "sites/examples/mushrooms/site.yaml", mushrooms / "site.yaml")
    edit(mushrooms / "site.yaml", lambda doc: doc.insert(3, "safety", {"actuator_limits": {"actuator.heater": {"max_on": "20m"}}}))
    text = problems(mushrooms, catalog)
    assert "stage incubation loop heat: max_on must be set and at most 20m (site limit for actuator.heater)" in text


def test_the_hub_refuses_an_override_outside_the_envelope(mock):
    system = mock("mushrooms")
    with pytest.raises(ValueError, match="relative_humidity min 40 is below the species limit of 60"):
        system.hub.advance_stage("oyster-1")
        system.hub.set_override("fruiting-chamber", "relative_humidity", "1h", min=40)
    assert system.hub.overrides == {}
    assert system.hub.set_override("fruiting-chamber", "relative_humidity", "1h", min=80)["band"]["min"] == 80


def test_limits_must_make_sense(catalog, tmp_path):
    species = {"kind": "Species", "id": "odd", "common_name": "Odd", "category": "houseplant", "limits": {"sparkle": {"max": 3}, "air_temperature": {"min": 30, "max": 10}}}
    library = tmp_path / "library" / "species"
    library.mkdir(parents=True)
    (library / "odd.yaml").write_text(yaml.safe_dump(species), encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        catalog.with_library(tmp_path / "library")
    text = "\n".join(err.value.problems)
    assert "limit for unknown quantity 'sparkle'" in text and "limit for air_temperature has min above max" in text


# --------------------------------------------------------------------------- a site's own library

def add_recipe(site_dir: Path, catalog, recipe_id: str = "pothos.thirsty") -> None:
    recipe = copy.deepcopy(catalog.get("Recipe", "pothos.steady"))
    recipe.update(id=recipe_id)
    recipe["control"][0]["dose"]["volume_ml"] = 200
    folder = site_dir / "library" / "recipes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{recipe_id}.yaml").write_text(yaml.safe_dump(recipe), encoding="utf-8")


def test_a_site_can_add_its_own_recipe_without_touching_the_catalog(site_dir, catalog):
    before = sorted(p.name for p in (ROOT / "catalog" / "recipes").iterdir())
    add_recipe(site_dir, catalog)
    edit(site_dir / "site.yaml", lambda doc: doc["plantings"][0].update(recipe="pothos.thirsty"))

    site = load_site(site_dir, catalog)
    assert site.plantings["pothos-1"].recipe["stages"][0]["control"][0]["dose"] == {"volume_ml": 200}
    assert site.catalog.origin["Recipe"]["pothos.thirsty"] == "site" and site.catalog.origin["Recipe"]["pothos.steady"] == "builtin"
    assert "pothos.thirsty" not in catalog.items["Recipe"]              # the shared catalog object is unchanged
    assert sorted(p.name for p in (ROOT / "catalog" / "recipes").iterdir()) == before


def test_a_site_library_cannot_replace_built_in_entries_or_hold_parts(site_dir, catalog):
    add_recipe(site_dir, catalog, "pothos.steady")
    assert "recipe 'pothos.steady' already exists in the built-in catalog; give yours another id" in problems(site_dir, catalog)
    shutil.rmtree(site_dir / "library")

    models = site_dir / "library" / "models"
    models.mkdir(parents=True)
    shutil.copyfile(ROOT / "catalog/models/generic.12v-fan.yaml", models / "my.fan.yaml")
    text = problems(site_dir, catalog)
    assert "a site library may hold species, recipe, goal, theme only; models belong to the built-in catalog" in text


def test_a_hub_runs_a_site_recipe(site_dir, catalog):
    from fsf_sim import MockSystem
    add_recipe(site_dir, catalog)
    edit(site_dir / "site.yaml", lambda doc: doc["plantings"][0].update(recipe="pothos.thirsty"))
    shutil.copyfile(ROOT / "sites/examples/houseplants/sim.yaml", site_dir / "sim.yaml")
    system = MockSystem(site_dir, catalog=catalog)
    system.sim.zones["pothos-window"].soil_moisture = 20.0
    system.run(hours=3)
    assert system.events("dose", zone="pothos-window")[0]["volume_ml"] == 200
    system.stop_hub()


# --------------------------------------------------------------------------- round-trip writing

@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_catalog_and_example_file_round_trips(path):
    original = path.read_text(encoding="utf-8")
    saved = yamlio.dumps(yamlio.loads(original))
    assert yaml.safe_load(saved) == yaml.safe_load(original)            # the hub reads the same thing
    comments = [m.group(1) for line in original.splitlines() if (m := re.search(r"(?:^|\s)#\s*(.*\S)\s*$", line))]
    assert not [c for c in comments if c not in saved], "a comment was lost"
    assert yamlio.dumps(yamlio.loads(saved)) == saved                   # saving again changes nothing


def test_an_edit_keeps_comments_quotes_and_order(site_dir):
    path = site_dir / "site.yaml"
    before = path.read_text(encoding="utf-8")
    edit(path, lambda doc: doc["zones"][0].update(kind="chamber"))
    after = path.read_text(encoding="utf-8")
    assert yaml.safe_load(after)["zones"][0]["kind"] == "chamber"
    assert "# change to esphome when the real node exists" in after and "# Pins were proposed by" in after
    assert [ln.split(":")[0] for ln in after.splitlines() if re.match(r"^[a-z]", ln)] == \
           [ln.split(":")[0] for ln in before.splitlines() if re.match(r"^[a-z]", ln)]      # top-level keys in the same order
    assert not (site_dir / "site.yaml.tmp").exists()

    theme = site_dir / "theme.yaml"
    shutil.copyfile(ROOT / "catalog/themes/default.yaml", theme)
    edit(theme, lambda doc: doc["brightness"].update(day=0.4))
    assert 'effect: "off"' in theme.read_text(encoding="utf-8")         # still quoted: a bare off would read as false
    assert yaml.safe_load(theme.read_text(encoding="utf-8"))["statuses"]["idle"]["effect"] == "off"


# --------------------------------------------------------------------------- revisions

T0 = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)


def test_revisions_record_who_changed_what_and_can_be_restored(site_dir, catalog):
    store = RevisionStore(site_dir, catalog)
    assert store.list() == [] and store.changed() == ["site.yaml"]
    first = store.save("ada", "as built", now=T0)
    assert (first.number, first.parent, first.by, first.created) == (1, None, "ada", T0.isoformat())
    assert store.changed() == []
    with pytest.raises(RevisionError, match="nothing has changed since revision 1"):
        store.save("ada", "again")

    add_recipe(site_dir, catalog)
    edit(site_dir / "site.yaml", lambda doc: doc["plantings"][0].update(recipe="pothos.thirsty"))
    assert store.changed() == ["library/recipes/pothos.thirsty.yaml", "site.yaml"]
    second = store.save("grace", "bigger doses for the pothos", based_on=1)
    assert second.parent == 1 and sorted(second.files) == ["library/recipes/pothos.thirsty.yaml", "site.yaml"]
    assert [r.message for r in store.list()] == ["as built", "bigger doses for the pothos"]

    changes = {d["file"]: d for d in store.diff(1, 2)}
    assert changes["library/recipes/pothos.thirsty.yaml"]["change"] == "added"
    assert "+  - {id: pothos-1, zone: pothos-window, species: pothos, recipe: pothos.thirsty}" in changes["site.yaml"]["diff"]

    assert store.restore(1) == ["library/recipes/pothos.thirsty.yaml", "site.yaml"]
    assert not (site_dir / "library/recipes/pothos.thirsty.yaml").exists()
    assert load_site(site_dir, catalog).plantings["pothos-1"].recipe["id"] == "pothos.steady"
    assert store.changed() == ["library/recipes/pothos.thirsty.yaml", "site.yaml"]      # a draft again, relative to revision 2


def test_a_draft_that_does_not_validate_is_not_saved(site_dir, catalog):
    store = RevisionStore(site_dir, catalog)
    store.save("ada", "as built")
    edit(site_dir / "site.yaml", lambda doc: doc["plantings"][0].update(overrides={"targets": {"air_temperature": {"max": 50}}}))
    with pytest.raises(RevisionError) as err:
        store.save("mallory", "sauna")
    assert "does not validate" in str(err.value) and "above the species limit of 35" in str(err.value)
    assert len(store.list()) == 1 and store.diff(1)[0]["file"] == "site.yaml"


def test_a_stale_draft_is_refused_instead_of_overwriting(site_dir, catalog):
    store = RevisionStore(site_dir, catalog)
    store.save("ada", "as built")
    edit(site_dir / "site.yaml", lambda doc: doc.update(name="Plants on the shelf"))
    store.save("grace", "rename", based_on=1)
    edit(site_dir / "site.yaml", lambda doc: doc.update(name="My plants"))
    with pytest.raises(RevisionError, match="based on revision 1, but the newest is 2"):
        store.save("ada", "rename differently", based_on=1)
    assert len(store.list()) == 2


def test_revisions_never_contain_secrets_and_restore_leaves_them_alone(site_dir, catalog):
    (site_dir / "secrets.yaml").write_text("wifi_password: hunter2\n", encoding="utf-8")
    (site_dir / "hub.env").write_text("FSF_MQTT_PASSWORD=abc\n", encoding="utf-8")
    store = RevisionStore(site_dir, catalog)
    store.save("ada", "as built")
    edit(site_dir / "site.yaml", lambda doc: doc.update(name="Renamed"))
    store.save("ada", "rename")
    stored = [p.relative_to(store.root).as_posix() for p in store.root.rglob("*") if p.is_file()]
    assert sorted(stored) == ["0001/manifest.json", "0001/site.yaml", "0002/manifest.json", "0002/site.yaml"]
    assert "hunter2" not in "".join(p.read_text(encoding="utf-8") for p in store.root.rglob("*") if p.is_file())
    store.restore(1)
    assert (site_dir / "secrets.yaml").read_text(encoding="utf-8") == "wifi_password: hunter2\n"

    assert store.applied() is None
    store.mark_applied(2)
    assert store.applied() == 2
    with pytest.raises(RevisionError, match="there is no revision 9"):
        store.mark_applied(9)


def test_the_built_in_catalog_is_loaded_once_and_not_mutated_by_layering(catalog):
    counts = {kind: len(entries) for kind, entries in catalog.items.items()}
    again = Catalog.load()
    assert {kind: len(entries) for kind, entries in again.items.items()} == counts
    assert set(catalog.origin["Recipe"].values()) == {"builtin"}

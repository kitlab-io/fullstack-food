"""Every scenario file of the example sites is a test: saving a scenario makes it a regression test."""

import pytest

from fsf_core import find_repo_root
from fsf_sim import run_scenario

FILES = sorted((find_repo_root() / "sites" / "examples").glob("*/scenarios/*.yaml"))


def test_the_example_sites_have_scenarios():
    assert len(FILES) >= 20
    assert {f.parent.parent.name for f in FILES} == {"houseplants", "microgreens", "mushrooms"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_scenario(path, catalog):
    result = run_scenario(path, catalog)
    assert result.passed, result.report()

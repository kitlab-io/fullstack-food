import pytest

from fsf_core import Catalog
from fsf_sim import MockSystem


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return Catalog.load()


@pytest.fixture
def mock(catalog):
    """Factory for a mock system built from one of the example sites."""
    systems = []

    def make(name: str, **kwargs) -> MockSystem:
        system = MockSystem(f"sites/examples/{name}", catalog=catalog, **kwargs)
        systems.append(system)
        return system

    yield make
    for system in systems:
        if system.hub:
            system.stop_hub()

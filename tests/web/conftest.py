import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from fsf_web import Live, create_app  # noqa: E402


@pytest.fixture
def served(mock, tmp_path):
    """(system, client) for an example site; call refresh() after running time to flush the hub's writes."""
    def make(name: str, **kwargs):
        system = mock(name, db_path=str(tmp_path / f"{name}.db"), record_readings=True, **kwargs)
        live = Live(system.site.id, system.bus, system.clock)
        client = TestClient(create_app(system.site, system.catalog, system.db_path, live))
        system.live = live
        system.refresh = lambda: system.hub.store.commit()
        return system, client
    return make

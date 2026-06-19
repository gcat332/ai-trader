import pytest


@pytest.fixture(autouse=True)
def _clear_api_key(monkeypatch):
    # Importing `main`/`core.config` loads the developer's .env, which sets a real
    # API_KEY into os.environ and makes the API auth gate reject unauthenticated
    # test requests (401). Clear it per-test so the suite is deterministic regardless
    # of a local .env; tests that exercise auth set API_KEY explicitly via monkeypatch.
    # ponytail: only API_KEY leaks today; widen this if another secret starts polluting.
    monkeypatch.delenv("API_KEY", raising=False)

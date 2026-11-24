import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("WARM_FEATURED", "0")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("LLM_PROVIDER", "none")

import pytest  # noqa: E402

from app import main  # noqa: E402
from app.services import edgar, pipeline  # noqa: E402

from .real_sec import FixtureSource  # noqa: E402


@pytest.fixture(autouse=True)
def offline_sec(monkeypatch):
    """Serve SEC data from the real-data fixture and make any network call to SEC fail loudly."""
    def no_network(url, *a, **k):
        raise edgar.EdgarError(f"offline test: unexpected SEC request {url}")

    monkeypatch.setattr(edgar, "_get", no_network)
    monkeypatch.setattr(main, "LiveSource", FixtureSource)
    monkeypatch.setattr(pipeline, "LiveSource", FixtureSource)
    monkeypatch.setattr(edgar, "resolve", FixtureSource.resolve)
    monkeypatch.setattr(edgar, "search", FixtureSource.search)
    object.__setattr__(main.settings, "featured", ["NVDA", "LLY"])
    yield

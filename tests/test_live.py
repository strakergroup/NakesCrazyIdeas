import os

import pytest

from assurance.providers import ChatProvider, validate_comparisons, validate_extraction
from assurance.settings import Settings


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("CAS_RUN_LIVE_SMOKE") != "1",
    reason="Live credentials and deliberate CAS_RUN_LIVE_SMOKE=1 opt-in required",
)
def test_live_provider_synthetic_smoke():
    settings = Settings.from_env()
    assert settings.provider == "chat" and settings.allow_external and settings.provider_key
    provider = ChatProvider(settings)
    items = [{"id": "public-smoke", "text": "The example warranty is 24 months."}]
    sources = [{"id": "public-source", "text": items[0]["text"]}]
    extracted = validate_extraction(provider.extract(items), items)
    assert extracted.claims
    compared = validate_comparisons(provider.compare(extracted.claims, sources), extracted.claims, sources)
    assert all(c.outcome == "supported" for c in compared.comparisons)

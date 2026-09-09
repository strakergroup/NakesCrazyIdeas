import json

import httpx
import pytest

from assurance.providers import (
    Candidate,
    ChatProvider,
    Comparison,
    ComparisonOutput,
    ExtractionOutput,
    FixtureProvider,
    ProviderError,
    Quote,
    validate_comparisons,
    validate_extraction,
)
from assurance.settings import Settings

ITEMS = [{"id": "item-1", "text": "The warranty lasts 24 months."}]
SOURCES = [{"id": "source-a", "text": "The warranty lasts 24 months."}]


def provider(transport, **overrides):
    args = dict(
        provider="chat",
        provider_url="https://example.test/v1",
        provider_model="configured-model",
        provider_key="test-secret",
        allow_external=True,
    )
    args.update(overrides)
    return ChatProvider(Settings(**args), transport=httpx.MockTransport(transport))


def test_provider_requires_explicit_credentials_and_consent():
    for settings, code in [
        (Settings(provider="chat"), "EXTERNAL_PROCESSING_NOT_ENABLED"),
        (Settings(provider="chat", allow_external=True), "PROVIDER_CREDENTIALS_MISSING"),
    ]:
        with pytest.raises(ProviderError, match=code):
            ChatProvider(settings).extract(ITEMS)


def test_timeout_is_retryable():
    def fail(request):
        raise httpx.ReadTimeout("never expose this secret")

    with pytest.raises(ProviderError, match="PROVIDER_TIMEOUT") as error:
        provider(fail).extract(ITEMS)
    assert error.value.retryable


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"claims":[],"reviewed_item_ids":[],"uncertain_item_ids":[],"approve":true}'
                    },
                }
            ]
        },
    ],
)
def test_malformed_truncated_extra_fields_fail(body):
    with pytest.raises(ProviderError):
        provider(lambda req: httpx.Response(200, json=body)).extract(ITEMS)


def test_mock_http_adapter_contract_and_untrusted_input_prompt():
    output = FixtureProvider().extract(ITEMS)

    def response(request):
        body = json.loads(request.content)
        assert str(request.url) == "https://example.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert body["response_format"]["json_schema"]["strict"]
        assert "UNTRUSTED DATA" in body["messages"][0]["content"]
        assert "untrusted_data" in body["messages"][1]["content"]
        assert "tools" not in body
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": output.model_dump_json()}}]},
        )

    result = provider(response).extract(ITEMS)
    assert validate_extraction(result, ITEMS).claims[0].text == ITEMS[0]["text"]


def test_fabricated_source_id_and_quotes_and_missing_comparison():
    claims = FixtureProvider().extract(ITEMS).claims
    for source_id, quote in [("invented", SOURCES[0]["text"]), ("source-a", "fabricated text")]:
        result = ComparisonOutput(
            comparisons=[
                Comparison(
                    claim_id=claims[0].claim_id,
                    outcome="supported",
                    evidence=[Quote(source_id=source_id, start=0, end=len(quote), quote=quote)],
                    reason="claim",
                )
            ]
        )
        with pytest.raises(ProviderError):
            validate_comparisons(result, claims, SOURCES)
    with pytest.raises(ProviderError, match="MISSING_OR_DUPLICATE"):
        validate_comparisons(ComparisonOutput(comparisons=[]), claims, SOURCES)


def test_poor_extraction_and_fake_content_locators_fail():
    with pytest.raises(ProviderError, match="POOR_EXTRACTION"):
        validate_extraction(ExtractionOutput(claims=[], reviewed_item_ids=[], uncertain_item_ids=[]), ITEMS)
    with pytest.raises(ProviderError, match="FABRICATED_CLAIM"):
        validate_extraction(
            ExtractionOutput(
                claims=[Candidate(claim_id="a", item_id="item-1", start=0, end=3, text="bad")],
                reviewed_item_ids=["item-1"],
                uncertain_item_ids=[],
            ),
            ITEMS,
        )


def test_bounded_claim_not_universal_bill_saving_fixture_only():
    items = [{"id": "item-1", "text": "Cuts every customer's energy bills by 18%."}]
    sources = [
        {"id": "approved", "text": "Up to 18% lower energy consumption under specified test conditions."}
    ]
    fixture = FixtureProvider()
    claims = fixture.extract(items).claims
    comparison = validate_comparisons(fixture.compare(claims, sources), claims, sources)
    assert comparison.comparisons[0].outcome == "contradicted"
    assert "fixture" in comparison.comparisons[0].reason.lower()

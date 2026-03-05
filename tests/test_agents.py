from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents import DocumentMetadata, classify_image, classify_text
from app.config import settings
from pydantic_ai.models.openai import OpenAIChatModel


def _make_mock_agent(json_str: str) -> MagicMock:
    result = MagicMock()
    result.output = json_str

    agent = MagicMock()
    agent.run = AsyncMock(return_value=result)
    return agent


_TEXT_JSON = '{"date": "2024-01-15", "tags": ["invoice"]}'
_VISION_JSON = (
    '{"date": "2024-01-15", "tags": ["receipt"], "content": "Scanned text here."}'
)

MOCK_TEXT_METADATA = DocumentMetadata(date="2024-01-15", tags=["invoice"])
MOCK_VISION_METADATA = DocumentMetadata(
    date="2024-01-15", tags=["receipt"], content="Scanned text here."
)


def _get_model_name(mock_agent_cls: MagicMock) -> str:
    """Extract the model name from the OpenAIChatModel passed to Agent()."""
    model_arg = mock_agent_cls.call_args[0][0]
    assert isinstance(model_arg, OpenAIChatModel), (
        f"Expected OpenAIChatModel, got {type(model_arg)}"
    )
    return model_arg.model_name


@pytest.mark.asyncio
async def test_classify_text_uses_text_model():
    mock_agent = _make_mock_agent(_TEXT_JSON)
    with patch("app.agents.Agent", return_value=mock_agent) as mock_agent_cls:
        await classify_text("Invoice #123 from ACME Corp.")

    assert _get_model_name(mock_agent_cls) == settings.text_model, (
        f"classify_text must use text_model={settings.text_model!r}"
    )


@pytest.mark.asyncio
async def test_classify_image_uses_vision_model():
    mock_agent = _make_mock_agent(_VISION_JSON)
    with patch("app.agents.Agent", return_value=mock_agent) as mock_agent_cls:
        await classify_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/png")

    assert _get_model_name(mock_agent_cls) == settings.vision_model, (
        f"classify_image must use vision_model={settings.vision_model!r}"
    )


@pytest.mark.asyncio
async def test_classify_text_does_not_use_vision_model():
    mock_agent = _make_mock_agent(_TEXT_JSON)
    with patch("app.agents.Agent", return_value=mock_agent) as mock_agent_cls:
        await classify_text("Some document text.")

    assert _get_model_name(mock_agent_cls) != settings.vision_model, (
        "classify_text must NOT use the vision model"
    )


@pytest.mark.asyncio
async def test_classify_image_does_not_use_text_model():
    mock_agent = _make_mock_agent(_VISION_JSON)
    with patch("app.agents.Agent", return_value=mock_agent) as mock_agent_cls:
        await classify_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/png")

    assert _get_model_name(mock_agent_cls) != settings.text_model, (
        "classify_image must NOT use the text model"
    )


@pytest.mark.asyncio
async def test_classify_image_passes_binary_content():
    """BinaryContent must be included in the agent.run() call for vision to work."""
    from pydantic_ai import BinaryContent

    mock_agent = _make_mock_agent(_VISION_JSON)
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    with patch("app.agents.Agent", return_value=mock_agent):
        await classify_image(img_bytes, "image/png")

    run_args = mock_agent.run.call_args[0][0]
    assert any(isinstance(a, BinaryContent) for a in run_args), (
        "classify_image must pass BinaryContent to agent.run()"
    )


@pytest.mark.asyncio
async def test_classify_image_binary_content_media_type():
    """BinaryContent media_type must match the type passed to classify_image."""
    from pydantic_ai import BinaryContent

    mock_agent = _make_mock_agent(_VISION_JSON)

    with patch("app.agents.Agent", return_value=mock_agent):
        await classify_image(b"\x00" * 10, "image/jpeg")

    run_args = mock_agent.run.call_args[0][0]
    binary = next(a for a in run_args if isinstance(a, BinaryContent))
    assert binary.media_type == "image/jpeg"


@pytest.mark.asyncio
async def test_classify_text_caps_input_at_8000_chars():
    """Long text must be truncated before being sent to the LLM."""
    mock_agent = _make_mock_agent(_TEXT_JSON)
    long_text = "x" * 20_000

    with patch("app.agents.Agent", return_value=mock_agent):
        await classify_text(long_text)

    sent_text = mock_agent.run.call_args[0][0]
    assert len(sent_text) <= 8000


# --- _parse_metadata JSON extraction ---


def test_parse_metadata_plain_json():
    from app.agents import _parse_metadata

    m = _parse_metadata('{"date": "2024-02-27", "tags": ["fahrschein"]}', "test")
    assert m.date == "2024-02-27"
    assert "fahrschein" in m.tags


def test_parse_metadata_fenced_json():
    from app.agents import _parse_metadata

    raw = '```json\n{"date": "2024-02-27", "tags": ["ticket"]}\n```'
    m = _parse_metadata(raw, "test")
    assert m.date == "2024-02-27"


def test_parse_metadata_json_in_preamble():
    from app.agents import _parse_metadata

    raw = 'Here is the result:\n{"date": "2024-02-27", "tags": ["ticket"]}'
    m = _parse_metadata(raw, "test")
    assert m.date == "2024-02-27"


def test_parse_metadata_no_json_returns_fallback():
    from datetime import date

    from app.agents import _parse_metadata

    m = _parse_metadata("I cannot determine the date.", "test")
    assert m.date == date.today().isoformat()
    assert m.tags == ["document"]


# --- DocumentMetadata date normalisation ---


def test_date_iso_passthrough():
    m = DocumentMetadata(date="2024-02-27", tags=["ticket"])
    assert m.date == "2024-02-27"


def test_date_dmy_normalised():
    m = DocumentMetadata(date="27.02.2024", tags=["ticket"])
    assert m.date == "2024-02-27"


def test_date_mdy_normalised():
    m = DocumentMetadata(date="02/27/2024", tags=["ticket"])
    assert m.date == "2024-02-27"


def test_date_garbage_falls_back_to_today():
    m = DocumentMetadata(date="not-a-date", tags=["ticket"])
    assert m.date == date.today().isoformat()


def test_tags_empty_falls_back_to_document():
    m = DocumentMetadata(date="2024-02-27", tags=[])
    assert m.tags == ["document"]


def test_tags_sanitised():
    m = DocumentMetadata(date="2024-02-27", tags=["Fahrschein!", "BAHN"])
    assert m.tags == ["fahrschein", "bahn"]

import json
import logging
import re
from datetime import date as _date

from pydantic import BaseModel, field_validator
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

from app.config import settings

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Common alternative formats the LLM might produce
_DATE_DMY = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")  # DD.MM.YYYY
_DATE_MDY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")  # MM/DD/YYYY

# JSON code-fence the model sometimes wraps output in
_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.IGNORECASE)

_SYSTEM_PROMPT_ENG = (
    "You are a document classifier. Analyse the provided document and extract:\n"
    "1. The most relevant date (use document date if present, otherwise today's date in YYYY-MM-DD format).\n"
    "2. Up to 4 short, lowercase, hyphenated tags that describe the document type and key topics "
    "(e.g. invoice, receipt, contract, bank-statement, medical, insurance) and who is the sender.\n"
    "3. If this is an invoice, bill, or payment notice: the payment due date in YYYY-MM-DD format, or null if not found.\n"
    'Return ONLY a JSON object with keys "date", "tags", and "due_date" — no extra text.\n'
    'Example: {"date": "2024-02-27", "tags": ["invoice", "acme"], "due_date": "2024-03-15"}'
)

_SYSTEM_PROMPT_DE = (
    "Du bist ein Dokumentklassifizierer. Analysiere das bereitgestellte Dokument und extrahiere:\n"
    "1. Das relevanteste Datum (verwende das Dokumentdatum, falls vorhanden, andernfalls das heutige Datum im Format JJJJ-MM-TT).\n"
    "2. Bis zu 4 kurze, kleingeschriebene, durch Bindestriche getrennte Tags, die den Dokumenttyp und die wichtigsten Themen "
    "beschreiben (z. B. rechnung, quittung, vertrag, kontoauszug, medizinisch, versicherung) sowie den Absender.\n"
    "3. Falls es sich um eine Rechnung, Zahlungsaufforderung oder Zahlungsbenachrichtigung handelt: das Fälligkeitsdatum "
    "der Zahlung im Format JJJJ-MM-TT oder null, falls nicht gefunden.\n"
    'Gib AUSSCHLIESSLICH ein JSON-Objekt mit den Key "date", "tags" und "due_date" zurück — keinen zusätzlichen Text.\n'
    'Beispiel: {"date": "2024-02-27", "tags": ["rechnung", "acme"], "due_date": "2024-03-15"}'
)

_VISION_SYSTEM_PROMPT = (
    "You are a document extractor. Analyse the provided document image and:\n"
    "1. Extract ALL visible text content verbatim into a 'content' field.\n"
    "2. Identify the most relevant date (YYYY-MM-DD format, today if none found).\n"
    "3. Generate up to 5 short, lowercase, hyphenated tags (e.g. invoice, receipt, contract).\n"
    "4. If this is an invoice, bill, or payment notice: the payment due date in YYYY-MM-DD format, or null if not found.\n"
    'Return ONLY a JSON object with keys "date", "tags", "content", and "due_date" — no extra text.\n'
    'Example: {"date": "2024-02-27", "tags": ["invoice", "acme"], "content": "...", "due_date": "2024-03-15"}'
)

NUM_TAGS = 4


def _normalise_date(v: str) -> str:
    """Return v as YYYY-MM-DD, or today if it can't be parsed."""
    if _DATE_RE.match(v):
        return v
    m = _DATE_DMY.match(v)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = _DATE_MDY.match(v)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    logger.warning("[DocumentMetadata] unrecognised date %r — using today", v)
    return _date.today().isoformat()


def _normalise_optional_date(v: str) -> str | None:
    """Return v as YYYY-MM-DD, or None if it can't be parsed."""
    if _DATE_RE.match(v):
        return v
    m = _DATE_DMY.match(v)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = _DATE_MDY.match(v)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return None


class DocumentMetadata(BaseModel):
    date: str
    tags: list[str]
    content: str = ""  # populated by vision agent; text agent leaves it empty
    due_date: str | None = None

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, v: object) -> str:
        return _normalise_date(str(v))

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        if not v:
            return ["document"]
        cleaned = [re.sub(r"[^a-z0-9-]", "", t.lower()) for t in v[:NUM_TAGS]]
        return [t for t in cleaned if t] or ["document"]

    @field_validator("due_date", mode="before")
    @classmethod
    def validate_due_date(cls, v: object) -> str | None:
        if not v or str(v).strip().lower() in ("null", "none", "n/a", "", "-"):
            return None
        return _normalise_optional_date(str(v).strip())


def _ollama(model_name: str) -> OpenAIChatModel:
    return OpenAIChatModel(
        model_name,
        provider=OllamaProvider(base_url=settings.ollama_url),
    )


def _text_agent() -> Agent[None, str]:
    # output_type=str avoids tool-calling structured output, which Ollama
    # can't handle in multi-turn history (content: null rejection).
    return Agent(
        _ollama(settings.text_model),
        output_type=str,
        system_prompt=_SYSTEM_PROMPT_DE,
        retries=0,
    )


def _vision_agent() -> Agent[None, str]:
    return Agent(
        _ollama(settings.vision_model),
        output_type=str,
        system_prompt=_VISION_SYSTEM_PROMPT,
        retries=0,
    )


def _parse_metadata(raw: str, context: str) -> DocumentMetadata:
    """Extract JSON from raw LLM output and validate into DocumentMetadata."""
    logger.debug("[%s] raw LLM output: %r", context, raw)
    text = raw.strip()
    # Strip optional markdown code fence
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
        else:
            logger.warning("[%s] no JSON found in output, using fallback", context)
            data = {}
    meta = DocumentMetadata(
        date=data.get("date", _date.today().isoformat()),
        tags=data.get("tags", []),
        content=data.get("content", ""),
        due_date=data.get("due_date"),
    )
    logger.debug("[%s] parsed=%s", context, meta.model_dump_json())
    return meta


async def classify_text(text: str) -> DocumentMetadata:
    agent = _text_agent()
    truncated = text[:8000]
    logger.debug(
        "[classify_text] model=%r  input_chars=%d\n--- input (first 400 chars) ---\n%s",
        settings.text_model,
        len(truncated),
        truncated[:400],
    )
    result = await agent.run(truncated)
    return _parse_metadata(result.output, "classify_text")


async def classify_image(image_bytes: bytes, media_type: str) -> DocumentMetadata:
    agent = _vision_agent()
    content = BinaryContent(data=image_bytes, media_type=media_type)  # type: ignore[arg-type]
    logger.debug(
        "[classify_image] model=%r  media_type=%r  image_bytes=%d",
        settings.vision_model,
        media_type,
        len(image_bytes),
    )
    result = await agent.run(["Classify this document.", content])
    return _parse_metadata(result.output, "classify_image")

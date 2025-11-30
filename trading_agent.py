import os
import json
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY mancante nel .env")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")

# Limite compatto per contenere i costi mantenendo spazio sufficiente per un razionale
_DEFAULT_MAX_OUTPUT_TOKENS = 220
try:
    MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS))
except ValueError:
    MAX_OUTPUT_TOKENS = _DEFAULT_MAX_OUTPUT_TOKENS

ALLOWED_REASONING_EFFORT = {"none", "low", "medium", "high"}
reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "low").lower()
if reasoning_effort not in ALLOWED_REASONING_EFFORT:
    reasoning_effort = "low"

_reasoning_payload: Optional[Dict[str, Any]] = None
if reasoning_effort != "none":
    _reasoning_payload = {"effort": reasoning_effort}

client = OpenAI(api_key=OPENAI_API_KEY)


def _request_model(prompt: str, reasoning_payload: Optional[Dict[str, Any]]):
    return client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "trade_operation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "description": "Type of trading operation to perform",
                            "enum": [
                                "open",
                                "close",
                                "hold"
                            ]
                        },
                        "symbol": {
                            "type": "string",
                            "description": "The cryptocurrency symbol to act on",
                            "enum": [
                                "BTC",
                                "ETH",
                                "SOL"
                            ]
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of the trading decision",
                            "minLength": 1,
                            "maxLength": 300
                        }
                    },
                    "required": ["operation", "symbol", "reason"],
                    "additionalProperties": {
                        "description": "Optional fields like direction (long/short), target_portion_of_balance (0-1), leverage (1-10) and confidence score.",
                        "anyOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "boolean"},
                            {"type": "null"}
                        ]
                    }
                }
            },
            "verbosity": "medium"
        },
        reasoning=reasoning_payload,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        tools=[],
        store=True,
        include=[
            "reasoning.encrypted_content",
            "web_search_call.action.sources"
        ]
    )


def _extract_response_payload(response) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    # Prefer the parsed content from the Responses API (already schema-validated)
    content = response.output[0].content if response.output else None
    if content:
        for chunk in content:
            if hasattr(chunk, "parsed") and chunk.parsed is not None:
                return chunk.parsed, None

    # Fallback: try to parse raw text even if the parsed payload is missing
    raw_text = getattr(response, "output_text", None)

    if not raw_text and content:
        for chunk in content:
            if hasattr(chunk, "text") and chunk.text:
                raw_text = chunk.text
                break

    if isinstance(raw_text, bytes):
        raw_text = raw_text.decode("utf-8", "replace")

    return None, raw_text


def _raise_no_text_error(response):
    incomplete_reason = None
    if getattr(response, "incomplete_details", None):
        incomplete_reason = response.incomplete_details.get("reason")

    if incomplete_reason == "max_output_tokens":
        hint = (
            "La risposta è stata interrotta per max_output_tokens prima che venisse generato testo. "
            "Aumenta OPENAI_MAX_OUTPUT_TOKENS o imposta OPENAI_REASONING_EFFORT=none per evitare che il reasoning consumi tutti i token."
        )
    else:
        hint = "Nessun testo è stato restituito dal modello."

    raise ValueError(
        f"Impossibile interpretare la risposta del modello: {hint} "
        f"Payload grezzo: {response.model_dump(mode='json')}"
    )


def _parse_or_raise(raw_text: str):
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Impossibile interpretare la risposta del modello come JSON. "
            f"Output grezzo: {raw_text}"
        ) from exc


def previsione_trading_agent(prompt: str) -> Dict[str, Any]:
    # First attempt with the configured reasoning payload
    response = _request_model(prompt, _reasoning_payload)
    parsed, raw_text = _extract_response_payload(response)

    if parsed is not None:
        return parsed

    # If the model spent all tokens in reasoning, retry without reasoning to free tokens for the JSON
    if (
        raw_text in (None, "")
        and _reasoning_payload is not None
        and getattr(response, "incomplete_details", None)
        and response.incomplete_details.get("reason") == "max_output_tokens"
    ):
        retry_response = _request_model(prompt, None)
        parsed, raw_text = _extract_response_payload(retry_response)

        if parsed is not None:
            return parsed

        if not raw_text:
            _raise_no_text_error(retry_response)

        return _parse_or_raise(raw_text)

    if not raw_text:
        _raise_no_text_error(response)

    return _parse_or_raise(raw_text)

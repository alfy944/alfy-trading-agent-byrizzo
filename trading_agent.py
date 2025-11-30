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


def previsione_trading_agent(prompt: str) -> Dict[str, Any]:
    response = client.responses.create(
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
        reasoning=_reasoning_payload,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        tools=[],
        store=True,
        include=[
            "reasoning.encrypted_content",
            "web_search_call.action.sources"
        ]
    )

    # Prefer the parsed content from the Responses API (already schema-validated)
    content = response.output[0].content if response.output else None
    if content and hasattr(content[0], "parsed") and content[0].parsed is not None:
        return content[0].parsed

    # Fallback: try to parse raw text even if the parsed payload is missing
    raw_text = getattr(response, "output_text", None)
    if not raw_text and content and hasattr(content[0], "text"):
        raw_text = content[0].text

    if isinstance(raw_text, bytes):
        raw_text = raw_text.decode("utf-8", "replace")

    if not raw_text:
        raise ValueError(
            "Impossibile interpretare la risposta del modello: nessun testo restituito. "
            f"Payload grezzo: {response.model_dump(mode='json')}"
        )

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Impossibile interpretare la risposta del modello come JSON. "
            f"Output grezzo: {raw_text}"
        ) from exc

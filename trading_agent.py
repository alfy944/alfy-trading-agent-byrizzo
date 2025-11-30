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
                        "direction": {
                            "type": "string",
                            "description": "Trade direction: betting the price goes up (long) or down (short). For hold, may be omitted.",
                            "enum": [
                                "long",
                                "short"
                            ]
                        },
                        "target_portion_of_balance": {
                            "type": "number",
                            "description": "Fraction of (for open: balance, for close: position) to allocate/close; from 0.0 to 1.0 inclusive",
                            "minimum": 0,
                            "maximum": 1
                        },
                        "leverage": {
                            "type": "number",
                            "description": "Leverage multiplier (risk/reward, 1-10). Only applicable for 'open'.",
                            "minimum": 1,
                            "maximum": 10
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of the trading decision",
                            "minLength": 1,
                            "maxLength": 300
                        }
                    },
                    "required": ["operation", "symbol", "reason"],
                    "allOf": [
                        {
                            "if": {
                                "properties": {"operation": {"const": "open"}},
                                "required": ["operation"]
                            },
                            "then": {
                                "required": [
                                    "direction",
                                    "target_portion_of_balance"
                                ],
                                "properties": {
                                    "leverage": {
                                        "type": "number",
                                        "minimum": 1,
                                        "maximum": 10
                                    }
                                }
                            }
                        },
                        {
                            "if": {
                                "properties": {"operation": {"const": "close"}},
                                "required": ["operation"]
                            },
                            "then": {
                                "required": ["direction"]
                            }
                        }
                    ],
                    "additionalProperties": False
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

    return json.loads(response.output_text)

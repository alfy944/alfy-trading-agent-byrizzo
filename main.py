from indicators import analyze_multiple_tickers
from news_feed import fetch_latest_news
from trading_agent import previsione_trading_agent
from whalealert import format_whale_alerts_to_string
from sentiment import get_sentiment
from forecaster import get_crypto_forecasts
from hyperliquid_trader import HyperLiquidTrader
import os
import json
import db_utils
from dotenv import load_dotenv

load_dotenv()

# Collegamento ad Hyperliquid
TESTNET = True   # True = testnet, False = mainnet (occhio!)
VERBOSE = True    # stampa informazioni extra
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")


def _normalize_private_key(key: str) -> str:
    """Verifica che la chiave privata sia lunga 32 byte e restituisce la versione normalizzata."""

    if not key:
        raise RuntimeError("PRIVATE_KEY non impostata nel .env")

    key_clean = key.strip()
    if key_clean.startswith("0x"):
        key_body = key_clean[2:]
    else:
        key_body = key_clean

    if len(key_body) != 64:
        raise ValueError(
            "PRIVATE_KEY deve essere una stringa hex di 64 caratteri (32 byte). "
            "Verifica la chiave configurata nelle variabili d'ambiente."
        )

    # Verifica che sia una stringa hex valida
    int(key_body, 16)

    return "0x" + key_body if not key_clean.startswith("0x") else key_clean


def _normalize_wallet_address(address: str) -> str:
    if not address:
        raise RuntimeError("WALLET_ADDRESS non impostato nel .env")

    addr_clean = address.strip()
    if addr_clean.startswith("0x"):
        addr_body = addr_clean[2:]
    else:
        addr_body = addr_clean

    if len(addr_body) != 40:
        raise ValueError(
            "WALLET_ADDRESS deve essere lungo 40 caratteri hex (prefisso 0x opzionale)."
        )

    int(addr_body, 16)

    return "0x" + addr_body if not addr_clean.startswith("0x") else addr_clean


PRIVATE_KEY = _normalize_private_key(PRIVATE_KEY)
WALLET_ADDRESS = _normalize_wallet_address(WALLET_ADDRESS)

# Assicurati che le tabelle esistano prima di qualsiasi operazione di logging
db_utils.init_db()

# Valori di default in modo da evitare UnboundLocalError nel blocco di eccezione
system_prompt = ""
tickers = []
indicators_json = None
news_txt = ""
sentiment_json = None
forecasts_json = None
account_status = {}
try:
    bot = HyperLiquidTrader(
        secret_key=PRIVATE_KEY,
        account_address=WALLET_ADDRESS,
        testnet=TESTNET
    )

    # Calcolo delle informazioni in input per Ticker
    tickers = ['BTC', 'ETH', 'SOL']
    indicators_txt, indicators_json  = analyze_multiple_tickers(tickers)
    news_txt = fetch_latest_news()
    # whale_alerts_txt = format_whale_alerts_to_string()
    sentiment_txt, sentiment_json  = get_sentiment()
    forecasts_txt, forecasts_json = get_crypto_forecasts()


    msg_info=f"""<indicatori>\n{indicators_txt}\n</indicatori>\n\n
    <news>\n{news_txt}</news>\n\n
    <sentiment>\n{sentiment_txt}\n</sentiment>\n\n
    <forecast>\n{forecasts_txt}\n</forecast>\n\n"""

    account_status = bot.get_account_status()
    portfolio_data = f"{json.dumps(account_status)}"
    snapshot_id = db_utils.log_account_status(account_status)
    print(f"[db_utils] Operazione inserita con id={snapshot_id}")


    # Creating System prompt
    with open('system_prompt.txt', 'r') as f:
        system_prompt = f.read()
    system_prompt = system_prompt.format(portfolio_data, msg_info)

    print("L'agente sta decidendo la sua azione!")
    out = previsione_trading_agent(system_prompt)

    def _extract_atr(symbol: str, indicators_payload):
        try:
            for payload in indicators_payload:
                if payload.get("ticker", "").upper() == symbol.upper():
                    return payload.get("longer_term_15m", {}).get("atr_14_current")
        except Exception:
            return None
        return None

    atr_value = _extract_atr(out.get("symbol"), indicators_json)
    execution_result = bot.execute_signal(out, atr_value=atr_value)

    risk_order_id = None
    if isinstance(execution_result, dict):
        risk_order_id = execution_result.get("risk_order_id")

    op_id = db_utils.log_bot_operation(
        out,
        system_prompt=system_prompt,
        indicators=indicators_json,
        news_text=news_txt,
        sentiment=sentiment_json,
        forecasts=forecasts_json,
        risk_order_id=risk_order_id,
    )
    print(f"[db_utils] Operazione inserita con id={op_id}")

except Exception as e:
    try:
        db_utils.log_error(
            e,
            context={
                "prompt": system_prompt,
                "tickers": tickers,
                "indicators": indicators_json,
                "news": news_txt,
                "sentiment": sentiment_json,
                "forecasts": forecasts_json,
                "balance": account_status,
            },
            source="trading_agent",
        )
    except Exception as log_exc:
        print(f"[db_utils] Impossibile registrare l'errore: {log_exc}")

    print(f"An error occurred: {e}")
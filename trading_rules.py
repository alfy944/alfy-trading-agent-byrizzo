from __future__ import annotations

"""Regole di gestione rischio e filtri per l'apertura delle posizioni.

Questo modulo incapsula la logica richiesta per:
- Filtro di volatilità basato su ATR.
- Filtro di trend rispetto a EMA50 e buffer di indecisione.
- Blocco in finestre orarie di news macro.
- Controllo di correlazione con il RSI di BTC.
- Regole di micro-trend su EMA20 per scegliere la leva.
- Calcolo del trailing stop basato su ATR14.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VOLATILITY_THRESHOLD_PCT = 3.5
EMA50_NEUTRAL_BAND = 0.007  # 0.7%
MACRO_RISK_HOURS_UTC = {12, 13, 18}  # tipiche finestre per CPI/NFP/FOMC
TRAILING_ATR_MULTIPLIER = 1.5
MICROTREND_LEVERAGE_BOOST = 2
MICROTREND_LEVERAGE_CAP = 3


def _find_indicator(indicators: Optional[List[Dict[str, Any]]], symbol: str) -> Optional[Dict[str, Any]]:
    if not indicators:
        return None
    for item in indicators:
        if not isinstance(item, dict):
            continue
        if item.get("ticker", "").upper() == symbol.upper():
            return item
    return None


def _latest_value(series: Optional[List[Any]]) -> Optional[float]:
    if not series:
        return None
    try:
        return float(series[-1])
    except Exception:  # noqa: BLE001
        return None


def _microtrend_leverage(ema20_series: Optional[List[Any]], base_leverage: int) -> int:
    if not ema20_series or len(ema20_series) < 3:
        return base_leverage

    last_three = ema20_series[-3:]
    try:
        e1, e2, e3 = (float(x) for x in last_three)
    except Exception:  # noqa: BLE001
        return base_leverage

    if e1 < e2 < e3:
        boosted = base_leverage * MICROTREND_LEVERAGE_BOOST
        return min(MICROTREND_LEVERAGE_CAP, max(boosted, base_leverage))

    if e1 > e2 > e3:
        return 1

    return base_leverage


def _btc_rsi(indicators: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    btc = _find_indicator(indicators, "BTC")
    if not btc:
        return None
    intraday = btc.get("intraday") or {}
    return _latest_value(intraday.get("rsi_14"))


def _forecast_strength(forecasts: Optional[Any], symbol: str) -> Optional[float]:
    if not forecasts:
        return None
    items: List[Dict[str, Any]] = []
    if isinstance(forecasts, list):
        items = [x for x in forecasts if isinstance(x, dict)]
    elif isinstance(forecasts, dict):
        items = [forecasts]

    for fc in items:
        ticker = (fc.get("Ticker") or fc.get("ticker") or "").upper()
        timeframe = fc.get("Timeframe") or fc.get("timeframe")
        if ticker != symbol.upper():
            continue
        if timeframe and "15" not in str(timeframe):
            continue
        try:
            return float(fc.get("Variazione %") or fc.get("change_pct"))
        except Exception:  # noqa: BLE001
            return None
    return None


def evaluate_trade_signal(
    signal: Dict[str, Any],
    indicators: Optional[List[Dict[str, Any]]],
    forecasts: Optional[Any],
    *,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Applica i filtri pre-trade e calcola metadati aggiuntivi.

    Restituisce un dizionario con:
    - allowed: bool
    - block_reason: str | None
    - adjusted_leverage: int
    - atr_at_entry: float | None
    - trend_state: str | None
    - trailing_stop: float | None
    - forecast_strength: float | None
    """

    if signal.get("operation") != "open":
        return {
            "allowed": True,
            "block_reason": None,
            "adjusted_leverage": int(signal.get("leverage", 1)),
            "atr_at_entry": None,
            "trend_state": None,
            "trailing_stop": None,
            "forecast_strength": None,
        }

    now = now_utc or datetime.now(timezone.utc)
    indicator = _find_indicator(indicators, signal.get("symbol", ""))

    if not indicator:
        return {
            "allowed": False,
            "block_reason": "Nessun indicatore disponibile per il ticker richiesto",
            "adjusted_leverage": int(signal.get("leverage", 1)),
            "atr_at_entry": None,
            "trend_state": None,
            "trailing_stop": None,
            "forecast_strength": None,
        }

    current = indicator.get("current") or {}
    longer = indicator.get("longer_term_15m") or {}
    intraday = indicator.get("intraday") or {}

    price = float(current.get("price")) if current.get("price") is not None else None
    atr_14 = float(longer.get("atr_14_current")) if longer.get("atr_14_current") is not None else None
    ema_50 = float(longer.get("ema_50_current")) if longer.get("ema_50_current") is not None else None

    leverage = int(signal.get("leverage", 1))
    block_reason = None
    trend_state = None

    if now.hour in MACRO_RISK_HOURS_UTC:
        block_reason = f"Finestra macro sensibile (UTC {now.hour})"

    if price and atr_14:
        atr_pct = (atr_14 / price) * 100
        if atr_pct > VOLATILITY_THRESHOLD_PCT:
            block_reason = (
                f"Volatilità eccessiva: ATR% {atr_pct:.2f} supera la soglia {VOLATILITY_THRESHOLD_PCT}%"
            )

    direction = signal.get("direction")
    if price and ema_50:
        distance = abs(price - ema_50) / ema_50
        if distance <= EMA50_NEUTRAL_BAND:
            block_reason = "Prezzo troppo vicino a EMA50 (zona di indecisione)"
            trend_state = "near_ema50"
        elif direction == "long" and price <= ema_50:
            block_reason = "Filtro trend: LONG consentito solo sopra EMA50"
            trend_state = "below_ema50"
        elif direction == "short" and price >= ema_50:
            block_reason = "Filtro trend: SHORT consentito solo sotto EMA50"
            trend_state = "above_ema50"
        else:
            trend_state = "above_ema50" if price > ema_50 else "below_ema50"

    btc_rsi = _btc_rsi(indicators)
    if btc_rsi is not None and signal.get("symbol", "").upper() != "BTC":
        if direction == "long" and btc_rsi < 30:
            block_reason = "Correlazione negativa: RSI BTC < 30, evito long su altri asset"
        if direction == "short" and btc_rsi > 70:
            block_reason = "Correlazione negativa: RSI BTC > 70, evito short su altri asset"

    ema20_series = intraday.get("ema_20")
    leverage = _microtrend_leverage(ema20_series, leverage)

    trailing_stop = None
    if price is not None and atr_14 is not None:
        if direction == "long":
            trailing_stop = price - (TRAILING_ATR_MULTIPLIER * atr_14)
        elif direction == "short":
            trailing_stop = price + (TRAILING_ATR_MULTIPLIER * atr_14)

    forecast_strength = _forecast_strength(forecasts, signal.get("symbol", ""))

    return {
        "allowed": block_reason is None,
        "block_reason": block_reason,
        "adjusted_leverage": leverage,
        "atr_at_entry": atr_14,
        "trend_state": trend_state,
        "trailing_stop": trailing_stop,
        "forecast_strength": forecast_strength,
    }

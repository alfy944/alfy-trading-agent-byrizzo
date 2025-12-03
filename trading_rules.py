from __future__ import annotations

"""Regole di gestione rischio e filtri per l'apertura delle posizioni.

Questo modulo incapsula la logica richiesta per:
- Filtro di volatilità basato su ATR.
- Filtro di trend rispetto a EMA50 e buffer di indecisione.
- Blocco in finestre orarie di news macro.
- Controllo di correlazione con il RSI di BTC.
- Regole di micro-trend su EMA20 per scegliere la leva.
- Calcolo del trailing stop basato su ATR14.
- Punteggio di qualità dinamico con leva adattiva.
- Dimensionamento posizione adattivo in base a ATR e saldo.
- Peso di confidenza del forecast combinando Prophet e momentum.
- Rilevamento supporti/resistenze e break-even intelligente.
- Stop-loss soft con aggiustamento in base a liquidità/volumi.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

VOLATILITY_THRESHOLD_PCT = 3.5
EMA50_NEUTRAL_BAND = 0.007  # 0.7%
MACRO_RISK_HOURS_UTC = {12, 13, 18}  # tipiche finestre per CPI/NFP/FOMC
TRAILING_ATR_MULTIPLIER = 1.5
MICROTREND_LEVERAGE_BOOST = 2
MICROTREND_LEVERAGE_CAP = 3
QUALITY_HIGH_THRESHOLD = 80
QUALITY_MEDIUM_THRESHOLD = 60
QUALITY_BLOCK_THRESHOLD = 50
VIRTUAL_STOP_MULTIPLIER = 1.2


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


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


def _atr_pct(price: Optional[float], atr: Optional[float]) -> Optional[float]:
    if price is None or atr is None or price == 0:
        return None
    return (atr / price) * 100


def _support_resistance(intraday_highs_lows: Optional[Tuple[List[Any], List[Any]]]) -> Tuple[Optional[float], Optional[float]]:
    if not intraday_highs_lows:
        return None, None
    highs, lows = intraday_highs_lows
    if not highs or not lows:
        return None, None
    try:
        resistance = max(float(x) for x in highs)
        support = min(float(x) for x in lows)
        return support, resistance
    except Exception:  # noqa: BLE001
        return None, None


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


def _trend_signal(price: Optional[float], ema_50: Optional[float], ema_200: Optional[float]) -> float:
    if price is None or ema_50 is None:
        return 0.0
    if ema_200 is None:
        return 1.0 if price > ema_50 else -1.0 if price < ema_50 else 0.0

    if price > ema_50 > ema_200:
        return 1.0
    if price < ema_50 < ema_200:
        return -1.0
    return 0.0


def _confidence_score(
    prophet_change_pct: Optional[float],
    macd_value: Optional[float],
    ema_trend_signal: float,
    rsi_value: Optional[float],
) -> float:
    prophet_signal = 0.0
    if prophet_change_pct is not None:
        scaled = _clamp(prophet_change_pct / 5.0, -1.0, 1.0)
        prophet_signal = scaled

    macd_signal = 0.0
    if macd_value is not None:
        macd_signal = _clamp(macd_value / 100.0, -1.0, 1.0)

    rsi_signal = 0.0
    if rsi_value is not None:
        rsi_signal = _clamp((rsi_value - 50.0) / 50.0, -1.0, 1.0)

    weighted = (
        (prophet_signal * 0.4)
        + (macd_signal * 0.3)
        + (ema_trend_signal * 0.2)
        + (rsi_signal * 0.1)
    )
    # Convert from [-1, 1] to [0, 100]
    return _clamp((weighted + 1.0) * 50.0, 0.0, 100.0)


def _quality_score(
    forecast_strength: Optional[float],
    macd_value: Optional[float],
    rsi_value: Optional[float],
    atr_pct: Optional[float],
    major_trend_signal: float,
) -> float:
    # Forecast strength: valore positivo premiato, negativo penalizzato
    forecast_component = 0.5
    if forecast_strength is not None:
        normalized = _clamp(forecast_strength / 10.0, -1.0, 1.0)
        forecast_component = (normalized + 1.0) / 2.0

    momentum_component = 0.5
    macd_signal = 0.0
    rsi_signal = 0.0
    if macd_value is not None:
        macd_signal = _clamp(macd_value / 50.0, -1.0, 1.0)
    if rsi_value is not None:
        rsi_signal = _clamp((rsi_value - 50.0) / 25.0, -1.0, 1.0)
    momentum_component = _clamp((macd_signal * 0.6) + (rsi_signal * 0.4), -1.0, 1.0)
    momentum_component = (momentum_component + 1.0) / 2.0

    volatility_component = 0.5
    if atr_pct is not None:
        if atr_pct <= VOLATILITY_THRESHOLD_PCT:
            volatility_component = 1.0
        elif atr_pct >= VOLATILITY_THRESHOLD_PCT * 2:
            volatility_component = 0.0
        else:
            # Linear fade between thresholds
            upper = VOLATILITY_THRESHOLD_PCT * 2
            volatility_component = 1 - ((atr_pct - VOLATILITY_THRESHOLD_PCT) / (upper - VOLATILITY_THRESHOLD_PCT))

    trend_component = (major_trend_signal + 1.0) / 2.0  # [-1,1] -> [0,1]

    weighted = (
        (forecast_component * 0.35)
        + (momentum_component * 0.25)
        + (volatility_component * 0.2)
        + (trend_component * 0.2)
    )
    return _clamp(weighted * 100.0, 0.0, 100.0)


def _adaptive_leverage_from_quality(base_leverage: int, quality_score: float) -> Tuple[int, Optional[str]]:
    reason = None
    if quality_score >= QUALITY_HIGH_THRESHOLD:
        leverage = 3
    elif quality_score >= QUALITY_MEDIUM_THRESHOLD:
        leverage = 2
    elif quality_score < QUALITY_BLOCK_THRESHOLD:
        leverage = 1
        reason = "Qualità segnale troppo bassa per aprire con leva >1"
    else:
        leverage = 1

    return max(base_leverage, leverage), reason


def _adaptive_position_size(balance_usd: Optional[float], atr_value: Optional[float], price: Optional[float]) -> Optional[float]:
    if balance_usd is None or atr_value is None or price is None:
        return None
    if atr_value <= 0:
        return None
    risk = balance_usd * 0.01
    return risk / (atr_value * TRAILING_ATR_MULTIPLIER)


def _liquidity_stop_factor(volume_current: Optional[float], volume_average: Optional[float]) -> float:
    if volume_current is None or volume_average is None or volume_average == 0:
        return 1.0
    ratio = volume_current / volume_average
    if ratio >= 1.2:
        return 0.9  # book più profondo → SL più stretto
    if ratio <= 0.8:
        return 1.1  # book più sottile → SL più largo
    return 1.0


def evaluate_trade_signal(
    signal: Dict[str, Any],
    indicators: Optional[List[Dict[str, Any]]],
    forecasts: Optional[Any],
    *,
    account_status: Optional[Dict[str, Any]] = None,
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
    - quality_score: float | None
    - confidence_score: float | None
    - adaptive_position_size: float | None
    - support_level/resistance_level: float | None
    - break_even_trigger/break_even_allowed: float | bool | None
    - soft_stop_loss: float | None
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
            "quality_score": None,
            "confidence_score": None,
            "adaptive_position_size": None,
            "support_level": None,
            "resistance_level": None,
            "break_even_trigger": None,
            "break_even_allowed": None,
            "soft_stop_loss": None,
            "atr_pct": None,
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
            "quality_score": None,
            "confidence_score": None,
            "adaptive_position_size": None,
            "support_level": None,
            "resistance_level": None,
            "break_even_trigger": None,
            "break_even_allowed": None,
            "soft_stop_loss": None,
            "atr_pct": None,
        }

    current = indicator.get("current") or {}
    longer = indicator.get("longer_term_15m") or {}
    intraday = indicator.get("intraday") or {}

    price = float(current.get("price")) if current.get("price") is not None else None
    atr_14 = float(longer.get("atr_14_current")) if longer.get("atr_14_current") is not None else None
    ema_50 = float(longer.get("ema_50_current")) if longer.get("ema_50_current") is not None else None
    ema_200 = float(longer.get("ema_200_current")) if longer.get("ema_200_current") is not None else None
    macd_value = _latest_value(intraday.get("macd"))
    rsi14_value = _latest_value(intraday.get("rsi_14"))
    atr_pct_value = _atr_pct(price, atr_14)

    leverage = int(signal.get("leverage", 1))
    block_reason = None
    trend_state = None

    if now.hour in MACRO_RISK_HOURS_UTC:
        block_reason = f"Finestra macro sensibile (UTC {now.hour})"

    if atr_pct_value and atr_pct_value > VOLATILITY_THRESHOLD_PCT:
        block_reason = (
            f"Volatilità eccessiva: ATR% {atr_pct_value:.2f} supera la soglia {VOLATILITY_THRESHOLD_PCT}%"
        )

    direction = signal.get("direction")
    major_trend_signal = _trend_signal(price, ema_50, ema_200)
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

    forecast_strength = _forecast_strength(forecasts, signal.get("symbol", ""))
    confidence_score = _confidence_score(forecast_strength, macd_value, major_trend_signal, rsi14_value)
    quality_score = _quality_score(forecast_strength, macd_value, rsi14_value, atr_pct_value, major_trend_signal)

    leverage, quality_block = _adaptive_leverage_from_quality(leverage, quality_score)

    support_level = None
    resistance_level = None
    support_resistance = indicator.get("support_resistance") or {}
    if isinstance(support_resistance, dict):
        support_level = support_resistance.get("support")
        resistance_level = support_resistance.get("resistance")

    ema20_series = intraday.get("ema_20")
    leverage = _microtrend_leverage(ema20_series, leverage)

    volume_current = longer.get("volume_current")
    volume_average = longer.get("volume_average")
    liquidity_factor = _liquidity_stop_factor(volume_current, volume_average)

    trailing_stop = None
    if price is not None and atr_14 is not None:
        distance = TRAILING_ATR_MULTIPLIER * atr_14 * liquidity_factor
        if direction == "long":
            trailing_stop = price - distance
            if support_level:
                trailing_stop = max(trailing_stop, float(support_level))
        elif direction == "short":
            trailing_stop = price + distance
            if resistance_level:
                trailing_stop = min(trailing_stop, float(resistance_level))

    adaptive_position_size = _adaptive_position_size(
        (account_status or {}).get("balance_usd"),
        atr_14,
        price,
    )

    break_even_trigger = None
    break_even_allowed = None
    if price is not None and atr_14 is not None:
        rsi_ok = None
        if rsi14_value is not None:
            if direction == "long":
                rsi_ok = rsi14_value > 50
            elif direction == "short":
                rsi_ok = rsi14_value < 50
        near_sr = False
        if direction == "long" and resistance_level:
            near_sr = price >= float(resistance_level) * 0.995
        if direction == "short" and support_level:
            near_sr = price <= float(support_level) * 1.005

        if direction == "long":
            break_even_trigger = price + atr_14
        elif direction == "short":
            break_even_trigger = price - atr_14

        if rsi_ok is not None:
            break_even_allowed = bool(rsi_ok and not near_sr)

    soft_stop_loss = None
    if price is not None and atr_14 is not None:
        soft_distance = VIRTUAL_STOP_MULTIPLIER * atr_14 * liquidity_factor
        if direction == "long":
            soft_stop_loss = price - soft_distance
        elif direction == "short":
            soft_stop_loss = price + soft_distance
        if support_level and direction == "short":
            soft_stop_loss = max(soft_stop_loss, float(support_level)) if soft_stop_loss else soft_stop_loss
        if resistance_level and direction == "long":
            soft_stop_loss = min(soft_stop_loss, float(resistance_level)) if soft_stop_loss else soft_stop_loss

    if quality_block and block_reason is None and quality_score < QUALITY_BLOCK_THRESHOLD:
        block_reason = quality_block

    return {
        "allowed": block_reason is None,
        "block_reason": block_reason,
        "adjusted_leverage": leverage,
        "atr_at_entry": atr_14,
        "trend_state": trend_state,
        "trailing_stop": trailing_stop,
        "forecast_strength": forecast_strength,
        "quality_score": quality_score,
        "confidence_score": confidence_score,
        "adaptive_position_size": adaptive_position_size,
        "support_level": support_level,
        "resistance_level": resistance_level,
        "break_even_trigger": break_even_trigger,
        "break_even_allowed": break_even_allowed,
        "soft_stop_loss": soft_stop_loss,
        "atr_pct": atr_pct_value,
    }

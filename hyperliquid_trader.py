import asyncio
import json
import random
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, Optional

import eth_account
from eth_account.signers.local import LocalAccount

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from hyperliquid.utils import types


class HyperLiquidTrader:
    def __init__(
        self,
        secret_key: str,
        account_address: str,
        testnet: bool = True,
        skip_ws: bool = True,
    ):
        self.secret_key = secret_key
        self.account_address = account_address

        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        self.base_url = base_url

        # crea account signer
        account: LocalAccount = eth_account.Account.from_key(secret_key)

        self.info = Info(base_url, skip_ws=skip_ws)
        self.exchange = Exchange(account, base_url, account_address=account_address)

        # cache meta per tick-size e min-size
        self.meta = self.info.meta()

        # Parametri di gestione rischio basati su ATR
        self.atr_sl_multiplier = Decimal("1.5")
        self.atr_tp_multiplier = Decimal("2.5")
        self.atr_trailing_multiplier = Decimal("1.0")
        self.atr_break_even_threshold = Decimal("1.0")

        # stato trailing stop
        self.last_trailing_stops: Dict[str, Dict[str, Any]] = {}
        self._trailing_stop_running: Dict[str, bool] = {}

    def _to_hl_size(self, size_decimal: Decimal) -> str:
        # HL accetta max 8 decimali
        size_clamped = size_decimal.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        return format(size_clamped, "f")   # HL vuole stringa decimale perfetta

    # ----------------------------------------------------------------------
    #                            VALIDAZIONE INPUT
    # ----------------------------------------------------------------------
    def _validate_order_input(self, order_json: Dict[str, Any]):
        required_fields = [
            "operation",
            "symbol",
            "direction",
            "target_portion_of_balance",
            "leverage",
            "reason",
        ]

        for f in required_fields:
            if f not in order_json:
                raise ValueError(f"Missing required field: {f}")

        if order_json["operation"] not in ("open", "close", "hold"):
            raise ValueError("operation must be 'open', 'close', or 'hold'")

        if order_json["direction"] not in ("long", "short"):
            raise ValueError("direction must be 'long' or 'short'")

        try:
            float(order_json["target_portion_of_balance"])
        except:
            raise ValueError("target_portion_of_balance must be a number")

    # ----------------------------------------------------------------------
    #                           MIN SIZE / TICK SIZE
    # ----------------------------------------------------------------------
    def _get_min_tick_for_symbol(self, symbol: str) -> Decimal:
        """
        Hyperliquid definisce per ogni asset un tick size.
        Lo leggiamo da meta().
        """
        for perp in self.meta["universe"]:
            if perp["name"] == symbol:
                return Decimal(str(perp["szDecimals"]))
        return Decimal("0.00000001")  # fallback a 1e-8

    def _get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        for perp in self.meta["universe"]:
            if perp.get("name") == symbol:
                return perp
        return None

    def _round_size(self, size: Decimal, decimals: int) -> float:
        """
        Hyperliquid accetta massimo 8 decimali.
        Inoltre dobbiamo rispettare il tick size.
        """
        # prima clamp a 8 decimali
        size = size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

        # poi count of decimals per il tick
        fmt = f"{{0:.{decimals}f}}"
        return float(fmt.format(size))

    def _get_open_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        user_state = self.info.user_state(self.account_address)
        for position in user_state.get("assetPositions", []):
            pos = position.get("position") if isinstance(position, dict) else position
            if not pos:
                continue
            if pos.get("coin") != symbol:
                continue

            try:
                size = Decimal(str(pos.get("szi", 0)))
            except Exception:
                size = Decimal("0")

            if size != 0:
                return pos
        return None

    # ----------------------------------------------------------------------
    #                        GESTIONE LEVA
    # ----------------------------------------------------------------------
    def get_current_leverage(self, symbol: str) -> Dict[str, Any]:
        """Ottieni info sulla leva corrente per un simbolo"""
        try:
            user_state = self.info.user_state(self.account_address)
            
            # Cerca nelle posizioni aperte
            for position in user_state.get('assetPositions', []):
                pos = position.get('position', {})
                coin = pos.get('coin', '')
                if coin == symbol:
                    leverage_info = pos.get('leverage', {})
                    return {
                        'value': leverage_info.get('value', 0),
                        'type': leverage_info.get('type', 'unknown'),
                        'coin': coin
                    }
            
            # Se non c'è posizione aperta, controlla cross leverage default
            cross_leverage = user_state.get('crossLeverage', 20)
            return {
                'value': cross_leverage,
                'type': 'cross',
                'coin': symbol,
                'note': 'No open position, showing account default'
            }
            
        except Exception as e:
            print(f"Errore ottenendo leva corrente: {e}")
            return {'value': 20, 'type': 'unknown', 'error': str(e)}

    def set_leverage_for_symbol(self, symbol: str, leverage: int, is_cross: bool = True) -> Dict[str, Any]:
        """Imposta la leva per un simbolo specifico usando il metodo corretto"""
        try:
            print(f"🔧 Impostando leva {leverage}x per {symbol} ({'cross' if is_cross else 'isolated'} margin)")
            
            # Usa il metodo update_leverage con i parametri corretti
            result = self.exchange.update_leverage(
                leverage=leverage,      # int
                name=symbol,           # str - nome del simbolo come "BTC"
                is_cross=is_cross      # bool
            )
            
            if result.get('status') == 'ok':
                print(f"✅ Leva impostata con successo a {leverage}x per {symbol}")
            else:
                print(f"⚠️ Risposta dall'exchange: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Errore impostando leva per {symbol}: {e}")
            return {"status": "error", "error": str(e)}

    # ----------------------------------------------------------------------
    #                        TRAILING STOP DINAMICI
    # ----------------------------------------------------------------------
    def update_trailing_stops(self, symbol: str, position: Dict[str, Any], atr_value: Decimal) -> Dict[str, Any]:
        """Aggiorna il trailing stop per una posizione aperta"""
        atr_decimal = Decimal(str(atr_value))
        mids = self.info.all_mids()
        current_px = Decimal(str(mids.get(symbol, position.get("entryPx", "0"))))
        size_signed = Decimal(str(position.get("szi", 0)))
        if size_signed == 0:
            return {"status": "skipped", "reason": "no position size"}

        is_long = size_signed > 0
        stop_px = current_px - atr_decimal if is_long else current_px + atr_decimal

        last_stop = self.last_trailing_stops.get(symbol)
        if last_stop:
            last_stop_price = Decimal(str(last_stop.get("price", "0")))
            if stop_px == last_stop_price:
                return {"status": "skipped", "reason": "stop unchanged"}

        symbol_info = self._get_symbol_info(symbol)
        sz_decimals = int(symbol_info.get("szDecimals", 8)) if symbol_info else 8
        size = self._round_size(size_signed.copy_abs(), sz_decimals)

        order_type = {
            "trigger": {
                "triggerPx": float(stop_px),
                "isMarket": True,
                "tpsl": "sl",
            }
        }

        new_cloid = types.Cloid.from_int(random.getrandbits(128))

        if last_stop and last_stop.get("cloid"):
            try:
                self.exchange.bulk_cancel_by_cloid([
                    {"coin": symbol, "cloid": last_stop["cloid"]}
                ])
            except Exception as e:
                print(f"⚠️ Errore cancellando il trailing precedente per {symbol}: {e}")

        is_buy = not is_long
        try:
            response = self.exchange.order(
                name=symbol,
                is_buy=is_buy,
                sz=size,
                limit_px=0.0,
                order_type=order_type,
                reduce_only=True,
                cloid=new_cloid,
            )
        except Exception as e:
            print(f"❌ Errore impostando trailing stop per {symbol}: {e}")
            return {"status": "error", "error": str(e)}

        self.last_trailing_stops[symbol] = {
            "price": stop_px,
            "cloid": new_cloid,
            "response": response,
        }

        return {"status": "ok", "stop_px": float(stop_px), "cloid": new_cloid}

    async def trailing_stop_loop(self, symbol: str, atr_value: Decimal, poll_interval: float = 2.0):
        """Loop asincrono per aggiornare i trailing stop finché la posizione resta aperta"""
        atr_decimal = Decimal(str(atr_value))
        self._trailing_stop_running[symbol] = True

        while self._trailing_stop_running.get(symbol, False):
            position = self._get_open_position(symbol)
            if not position:
                print(f"⏹️ Posizione chiusa per {symbol}, interrompo trailing loop")
                self._trailing_stop_running[symbol] = False
                self.last_trailing_stops.pop(symbol, None)
                break

            mids = self.info.all_mids()
            current_px = Decimal(str(mids.get(symbol, position.get("entryPx", "0"))))
            last_stop = self.last_trailing_stops.get(symbol)

            should_refresh = last_stop is None
            if last_stop:
                last_stop_price = Decimal(str(last_stop.get("price", "0")))
                if abs(current_px - last_stop_price) >= atr_decimal:
                    should_refresh = True

            if should_refresh:
                self.update_trailing_stops(symbol, position, atr_decimal)

            await asyncio.sleep(poll_interval)

    # ----------------------------------------------------------------------
    #                        ESECUZIONE SEGNALE AI
    # ----------------------------------------------------------------------
    def execute_signal(self, order_json: Dict[str, Any]) -> Dict[str, Any]:
        from decimal import Decimal, ROUND_DOWN

        self._validate_order_input(order_json)

        op = order_json["operation"]
        symbol = order_json["symbol"]
        direction = order_json["direction"]
        portion = Decimal(str(order_json["target_portion_of_balance"]))
        leverage = int(order_json.get("leverage", 1))

        if op == "hold":
            print(f"[HyperLiquidTrader] HOLD — nessuna azione per {symbol}.")
            return {"status": "hold", "message": "No action taken."}

        if op == "close":
            print(f"[HyperLiquidTrader] Market CLOSE per {symbol}")
            return self.exchange.market_close(symbol)

        # OPEN --------------------------------------------------------
        # Prima di aprire la posizione, imposta la leva desiderata
        leverage_result = self.set_leverage_for_symbol(
            symbol=symbol,
            leverage=leverage,
            is_cross=True  # Puoi cambiare in False per isolated margin
        )
        
        if leverage_result.get('status') != 'ok':
            print(f"⚠️ Attenzione: impostazione leva potrebbe aver avuto problemi: {leverage_result}")
        
        # Piccola pausa per assicurarsi che la leva sia applicata
        import time
        time.sleep(0.5)
        
        # Verifica la leva attuale dopo l'aggiornamento
        current_leverage_info = self.get_current_leverage(symbol)
        print(f"📊 Leva attuale per {symbol}: {current_leverage_info}")

        # Ora procedi con l'apertura della posizione
        user = self.info.user_state(self.account_address)
        balance_usd = Decimal(str(user["marginSummary"]["accountValue"]))

        if balance_usd <= 0:
            raise RuntimeError("Balance account = 0")

        notional = balance_usd * portion * Decimal(str(leverage))

        mids = self.info.all_mids()
        if symbol not in mids:
            raise RuntimeError(f"Symbol {symbol} non presente su HL")

        mark_px = Decimal(str(mids[symbol]))
        raw_size = notional / mark_px

        # Ottieni info sul simbolo dalla meta
        symbol_info = None
        for perp in self.meta["universe"]:
            if perp["name"] == symbol:
                symbol_info = perp
                break
        
        if not symbol_info:
            raise RuntimeError(f"Symbol {symbol} non trovato nella meta universe")

        # IMPORTANTE: Ottieni il minimum order size (non szDecimals!)
        min_size = Decimal(str(symbol_info.get("minSz", "0.001")))
        sz_decimals = int(symbol_info.get("szDecimals", 8))
        max_leverage = symbol_info.get("maxLeverage", 100)

        # Verifica che la leva richiesta non superi il massimo
        if leverage > max_leverage:
            print(f"⚠️ Leva richiesta ({leverage}) supera il massimo per {symbol} ({max_leverage})")

        # Arrotonda secondo i decimali permessi
        quantizer = Decimal(10) ** -sz_decimals
        size_decimal = raw_size.quantize(quantizer, rounding=ROUND_DOWN)

        # Verifica che sia sopra il minimo
        if size_decimal < min_size:
            print(f"⚠️ Size calcolata ({size_decimal}) < minima richiesta ({min_size})")
            print(f"   Raw size: {raw_size}, Balance: {balance_usd}, Portion: {portion}, Leverage: {leverage}")
            print(f"   Notional: {notional}, Mark price: {mark_px}")
            
            # Usa direttamente il minimum size
            size_decimal = min_size

        # Converti a float per l'API
        size_float = float(size_decimal)

        is_buy = (direction == "long")

        print(
            f"\n[HyperLiquidTrader] Market {'BUY' if is_buy else 'SELL'} "
            f"{size_float} {symbol}\n"
            f"  💰 Prezzo: ${mark_px}\n"
            f"  📊 Notional: ${notional:.2f}\n"
            f"  🎯 Leva target: {leverage}x\n"
        )

        res = self.exchange.market_open(
            symbol,
            is_buy,
            size_float,
            None,
            0.01
        )

        return res

    # ----------------------------------------------------------------------
    #                           STATO ACCOUNT
    # ----------------------------------------------------------------------
    def get_account_status(self) -> Dict[str, Any]:
        data = self.info.user_state(self.account_address)
        balance = float(data["marginSummary"]["accountValue"])

        mids = self.info.all_mids()
        positions = []

        # Gestisci il formato corretto dei dati
        asset_positions = data.get("assetPositions", [])
        
        for p in asset_positions:
            # Estrai la posizione dal formato corretto
            if isinstance(p, dict) and "position" in p:
                pos = p["position"]
                coin = pos.get("coin", "")
            else:
                # Se il formato è diverso, prova ad adattarti
                pos = p
                coin = p.get("coin", p.get("symbol", ""))
                
            if not pos or not coin:
                continue
                
            size = float(pos.get("szi", 0))
            if size == 0:
                continue

            entry = float(pos.get("entryPx", 0))
            mark = float(mids.get(coin, entry))

            # Calcola P&L
            pnl = (mark - entry) * size
            
            # Estrai info sulla leva
            leverage_info = pos.get("leverage", {})
            leverage_value = leverage_info.get("value", "N/A")
            leverage_type = leverage_info.get("type", "unknown")

            positions.append({
                "symbol": coin,
                "side": "long" if size > 0 else "short",
                "size": abs(size),
                "entry_price": entry,
                "mark_price": mark,
                "pnl_usd": round(pnl, 4),
                "leverage": f"{leverage_value}x ({leverage_type})"
            })

        return {
            "balance_usd": balance,
            "open_positions": positions,
        }
    
    # ----------------------------------------------------------------------
    #                           UTILITY DEBUG
    # ----------------------------------------------------------------------
    def debug_symbol_limits(self, symbol: str = None):
        """Mostra i limiti di trading per un simbolo o tutti"""
        print("\n📊 LIMITI TRADING HYPERLIQUID")
        print("-" * 60)
        
        for perp in self.meta["universe"]:
            if symbol and perp["name"] != symbol:
                continue
                
            print(f"\nSymbol: {perp['name']}")
            print(f"  Min Size: {perp.get('minSz', 'N/A')}")
            print(f"  Size Decimals: {perp.get('szDecimals', 'N/A')}")
            print(f"  Price Decimals: {perp.get('pxDecimals', 'N/A')}")
            print(f"  Max Leverage: {perp.get('maxLeverage', 'N/A')}")
            print(f"  Only Isolated: {perp.get('onlyIsolated', False)}")
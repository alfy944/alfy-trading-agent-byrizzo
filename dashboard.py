from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from flask import Flask, render_template_string

import db_utils

app = Flask(__name__)


def _format_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "N/D"
    return value.strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_number(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "N/D"
    try:
        return f"{float(value):,.2f}{suffix}"
    except Exception:
        return str(value)


template = """
<!doctype html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Trading Bot</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f7f7f7; color: #1f2937; }
        header { background: #111827; color: white; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
        main { padding: 20px; max-width: 1200px; margin: auto; }
        .card { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); margin-bottom: 16px; }
        h1, h2 { margin: 0 0 8px 0; }
        table { width: 100%; border-collapse: collapse; margin-top: 8px; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #e5e7eb; }
        th { background: #f3f4f6; }
        .status { padding: 8px 12px; border-radius: 6px; display: inline-block; }
        .status.ok { background: #d1fae5; color: #065f46; }
        .status.warn { background: #fef3c7; color: #92400e; }
        .status.error { background: #fee2e2; color: #991b1b; }
        .pill { background: #e5e7eb; padding: 4px 8px; border-radius: 9999px; font-size: 12px; }
        .actions { display: flex; gap: 8px; align-items: center; }
        .button { background: #2563eb; color: white; border: none; border-radius: 6px; padding: 10px 14px; cursor: pointer; font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
        .button:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>Dashboard Trading Bot</h1>
            <p>Monitoraggio rapido di saldo, posizioni e operazioni recenti.</p>
        </div>
        <div class="actions">
            <button class="button" onclick="window.location.reload()">Aggiorna dati</button>
        </div>
    </header>
    <main>
        {% if status_message %}
            <div class="card status warn">{{ status_message }}</div>
        {% endif %}

        <section class="card">
            <h2>Riepilogo account</h2>
            {% if balance_summary %}
                <table>
                    <tbody>
                        <tr>
                            <th>Saldo attuale</th>
                            <td>{{ balance_summary.current_balance }}</td>
                        </tr>
                        <tr>
                            <th>Saldo iniziale</th>
                            <td>{{ balance_summary.initial_balance }}</td>
                        </tr>
                        <tr>
                            <th>PnL totale ($)</th>
                            <td>{{ balance_summary.pnl_usd }}</td>
                        </tr>
                        <tr>
                            <th>PnL totale (%)</th>
                            <td>{{ balance_summary.pnl_pct }}</td>
                        </tr>
                        <tr>
                            <th>Ultimo aggiornamento</th>
                            <td>{{ balance_summary.last_updated }}</td>
                        </tr>
                    </tbody>
                </table>
            {% else %}
                <p>Nessun dato di saldo disponibile.</p>
            {% endif %}
        </section>

        <section class="card">
            <h2>Operazioni aperte</h2>
            {% if open_positions %}
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Direzione</th>
                            <th>Size</th>
                            <th>Prezzo ingresso</th>
                            <th>Prezzo attuale</th>
                            <th>PnL (USD)</th>
                            <th>Leva</th>
                            <th>Aggiornato</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for pos in open_positions %}
                        <tr>
                            <td>{{ pos.symbol }}</td>
                            <td>{{ pos.side }}</td>
                            <td>{{ pos.size }}</td>
                            <td>{{ pos.entry_price }}</td>
                            <td>{{ pos.mark_price }}</td>
                            <td>{{ pos.pnl_usd }}</td>
                            <td>{{ pos.leverage }}</td>
                            <td>{{ pos.snapshot_at }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% else %}
                <p>Nessuna posizione aperta.</p>
            {% endif %}
        </section>

        <section class="card">
            <h2>Operazioni chiuse (ultime)</h2>
            {% if closed_operations %}
                <table>
                    <thead>
                        <tr>
                            <th>Data/Ora</th>
                            <th>Symbol</th>
                            <th>Direzione</th>
                            <th>Prezzo ingresso</th>
                            <th>Prezzo uscita</th>
                            <th>PnL (USD)</th>
                            <th>Commissioni</th>
                            <th>Leva</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for op in closed_operations %}
                        <tr>
                            <td>{{ op.created }}</td>
                            <td>{{ op.symbol }}</td>
                            <td>{{ op.direction }}</td>
                            <td>{{ op.entry_price }}</td>
                            <td>{{ op.exit_price }}</td>
                            <td>{{ op.pnl_usd }}</td>
                            <td>{{ op.fees }}</td>
                            <td>{{ op.leverage }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% else %}
                <p>Nessuna operazione chiusa registrata.</p>
            {% endif %}
        </section>

    </main>
</body>
</html>
"""


@app.route("/")
def home():
    status_message: Optional[str] = None
    balance_summary_raw = None
    open_positions_raw: List[dict] = []
    closed_operations_raw: List[dict] = []

    try:
        balance_summary_raw = db_utils.get_account_balance_summary()
    except Exception as exc:  # pragma: no cover - dashboard best effort
        status_message = f"Errore nel recupero del riepilogo saldo: {exc}"

    try:
        open_positions_raw = db_utils.get_latest_open_positions_with_details()
    except Exception as exc:  # pragma: no cover
        status_message = f"Errore nel recupero delle posizioni aperte: {exc}"

    try:
        closed_operations_raw = db_utils.get_recent_bot_operations_with_timestamp(
            limit=20, operation_type="close"
        )
    except Exception as exc:  # pragma: no cover
        status_message = f"Errore nel recupero delle operazioni chiuse: {exc}"

    balance_summary_raw = balance_summary_raw or {
        "initial_balance": 999.0,
        "current_balance": None,
        "pnl_usd": None,
        "pnl_pct": None,
        "current_at": None,
    }

    balance_summary = None
    if balance_summary_raw:
        balance_summary = {
            "current_balance": _format_number(balance_summary_raw.get("current_balance")),
            "initial_balance": _format_number(balance_summary_raw.get("initial_balance")),
            "pnl_usd": _format_number(balance_summary_raw.get("pnl_usd")),
            "pnl_pct": _format_number(balance_summary_raw.get("pnl_pct"), suffix="%"),
            "last_updated": _format_datetime(balance_summary_raw.get("current_at")),
        }

    open_positions = [
        {
            "symbol": pos.get("symbol", "-"),
            "side": pos.get("side", "-"),
            "size": _format_number(pos.get("size")),
            "entry_price": _format_number(pos.get("entry_price")),
            "mark_price": _format_number(pos.get("mark_price")),
            "pnl_usd": _format_number(pos.get("pnl_usd")),
            "leverage": pos.get("leverage", "-"),
            "snapshot_at": _format_datetime(pos.get("snapshot_at")),
        }
        for pos in open_positions_raw
    ]

    closed_operations = [
        {
            "created": _format_datetime(op.get("created_at")),
            "symbol": op.get("payload", {}).get("symbol", "-"),
            "direction": op.get("payload", {}).get("direction", "-"),
            "entry_price": _format_number(op.get("payload", {}).get("entry_price")),
            "exit_price": _format_number(op.get("payload", {}).get("exit_price")),
            "pnl_usd": _format_number(op.get("payload", {}).get("pnl_usd")),
            "fees": _format_number(op.get("payload", {}).get("fees")),
            "leverage": op.get("payload", {}).get("leverage", "-"),
        }
        for op in closed_operations_raw
    ]

    return render_template_string(
        template,
        balance_summary=balance_summary,
        open_positions=open_positions,
        closed_operations=closed_operations,
        status_message=status_message,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

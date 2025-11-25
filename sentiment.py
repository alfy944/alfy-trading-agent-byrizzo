import requests
import os
from dotenv import load_dotenv

load_dotenv()

# --- Configurazione ---

# Endpoint dell'API come da documentazione
API_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"

# La tua API Key (Best practice: impostala come variabile d'ambiente)
# NON SCRIVERE LA TUA KEY DIRETTAMENTE NEL CODICE
API_KEY = os.getenv('CMC_PRO_API_KEY')

# Intervallo per il tuo trading bot (3 minuti * 60 secondi)
INTERVALLO_SECONDI = 3 * 60


def get_latest_fear_and_greed():
    """
    Chiama l'API di CoinMarketCap per ottenere l'ultimo valore
    del Fear & Greed Index.
    """
    if not API_KEY:
        print("Errore: La variabile d'ambiente CMC_PRO_API_KEY non è impostata.")
        return None

    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': API_KEY,
    }

    parameters = {
        'limit': 1
    }

    try:
        response = requests.get(API_URL, headers=headers, params=parameters)
        response.raise_for_status()
        data = response.json()

        if data and 'data' in data and len(data['data']) > 0:
            latest_record = data['data'][0]
            valore = latest_record.get('value')
            classificazione = latest_record.get('value_classification')
            timestamp = latest_record.get('timestamp')

            return {
                "valore": valore,
                "classificazione": classificazione,
                "timestamp": timestamp
            }

        print("Errore: La risposta JSON non contiene i dati attesi.")
        return None

    except requests.exceptions.HTTPError as errh:
        print(f"Errore HTTP: {errh}")
    except requests.exceptions.ConnectionError as errc:
        print(f"Errore di Connessione: {errc}")
    except requests.exceptions.Timeout as errt:
        print(f"Errore di Timeout: {errt}")
    except requests.exceptions.RequestException as err:
        print(f"Errore generico della richiesta: {err}")

    return None


def get_sentiment():
    """
    Restituisce una stringa formattata con l'ultimo Fear & Greed Index e
    un dizionario con i dati originali (se disponibili).
    """
    sentiment_data = get_latest_fear_and_greed()
    if sentiment_data:
        sentiment_text = (
            f"Sentiment del mercato (Fear & Greed Index):\n"
            f"  Valore: {sentiment_data['valore']}\n"
            f"  Classificazione: {sentiment_data['classificazione']}\n"
            f"  Timestamp: {sentiment_data['timestamp']}"
        )
        return sentiment_text, sentiment_data

    warning = "Impossibile recuperare il sentiment del mercato."
    if not API_KEY:
        warning += " Variabile d'ambiente CMC_PRO_API_KEY mancante."

    return warning, None

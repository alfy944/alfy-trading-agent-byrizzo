# Trading Agent
![](/img.jpg)
Trading Agent è un progetto open source ispirato a [Alpha Arena](https://nof1.ai/), una piattaforma di trading AI-driven che promuove la competizione tra agenti LLMs. L’obiettivo di questo progetto è sviluppare un agente di trading automatizzato, capace di analizzare dati di mercato, notizie, sentiment e segnali provenienti da grandi movimenti (“whale alert”) per prendere decisioni di trading informate.

## Caratteristiche principali

- **Analisi multi-sorgente**: integra dati di mercato, news, sentiment analysis e whale alert.
- **Previsioni**: utilizza modelli di forecasting per anticipare i movimenti di prezzo.
- **Modularità**: ogni componente (news, sentiment, indicatori, whale alert, forecasting) è gestito da moduli separati, facilmente estendibili.
- **Ispirazione Alpha Arena**: il progetto prende spunto dall’approccio competitivo e AI-driven di Alpha Arena, con l’obiettivo di creare agenti sempre più performanti.

## Video di presentazione

Guarda la presentazione del progetto su YouTube:
[https://www.youtube.com/watch?v=Vrl2Ar_SvSo&t=45s](https://www.youtube.com/watch?v=Vrl2Ar_SvSo&t=45s)

## Dashboard web

È disponibile una dashboard web (FastAPI + HTMX) per monitorare il saldo, le posizioni aperte e le ultime operazioni generate dal bot. Per avviarla:

1. Installa le dipendenze (idealmente in un virtualenv):

   ```bash
   pip install -r requirements.txt
   ```

2. Esporta l'URL del database PostgreSQL usato dal bot (lo stesso configurato in `DATABASE_URL`):

   ```bash
   export DATABASE_URL=postgresql://user:password@host:5432/trading_db
   ```

   Assicurati che il bot abbia già scritto almeno un record nel database, altrimenti le tabelle potrebbero essere vuote.

3. Avvia la dashboard FastAPI con Uvicorn:

   ```bash
   uvicorn dashboard:app --host 0.0.0.0 --port 8000
   ```

   L'applicazione si avvia su `http://localhost:8000` (o sull'IP del server se la esegui in remoto). Apri quell'URL nel browser per visualizzare saldo, posizioni aperte e operazioni recenti.

### Deploy rapido su Railway

Per servire la dashboard online su Railway (senza doverla eseguire in locale):

1. **Crea un nuovo progetto o servizio Railway** e collega il repository (anche tramite fork).
2. Railway imposterà automaticamente l'ambiente con Nixpacks; nelle variabili di ambiente aggiungi `DATABASE_URL` puntando al database usato dal bot (es. Postgres gestito da Railway oppure lo stesso database condiviso dal bot).
3. Railway userà il comando di avvio definito in `railway.json` (`python start.py`). Per avviare la dashboard FastAPI, aggiungi una variabile di ambiente `RAILWAY_START_TARGET=dashboard` (di default parte `main.py`). Railway fornisce la variabile `PORT` automaticamente; l'app usa `PORT` quando è presente, quindi non serve configurarla manualmente.
4. Avvia il deploy. Una volta terminato, Railway espone un URL pubblico in cui è disponibile la dashboard FastAPI.

## Licenza

Questo progetto è distribuito sotto licenza MIT.

---

> Progetto sviluppato da Rizzo AI Academy.

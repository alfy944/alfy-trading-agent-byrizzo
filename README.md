# Trading Agent
![](/img.jpg)
Trading Agent è un progetto open source ispirato a [Alpha Arena](https://nof1.ai/), una piattaforma di trading AI-driven che promuove la competizione tra agenti LLMs. L’obiettivo di questo progetto è sviluppare un agente di trading automatizzato, capace di analizzare dati di mercato, notizie, sentiment e segnali provenienti da grandi movimenti (“whale alert”) per prendere decisioni di trading informate.

## Caratteristiche principali

- **Analisi multi-sorgente**: integra dati di mercato, news, sentiment analysis e whale alert.
- **Previsioni**: utilizza modelli di forecasting per anticipare i movimenti di prezzo.
- **Modularità**: ogni componente (news, sentiment, indicatori, whale alert, forecasting) è gestito da moduli separati, facilmente estendibili.
- **Ispirazione Alpha Arena**: il progetto prende spunto dall’approccio competitivo e AI-driven di Alpha Arena, con l’obiettivo di creare agenti sempre più performanti.

## Configurazione OpenAI (ottimizzazione costi)

Il bot usa le API OpenAI per generare il segnale di trading. Le impostazioni predefinite puntano a **gpt-5.1** per mantenere l'affidabilità del segnale, ma con limiti pensati per contenere i costi. Puoi regolare qualità e spesa con queste variabili d'ambiente:

- `OPENAI_MODEL`: modello da usare per le chiamate. Default `gpt-5.1` (affidabilità più alta); puoi scegliere un modello più economico se vuoi ridurre ulteriormente la spesa.
- `OPENAI_REASONING_EFFORT`: livello di ragionamento (`none`, `low`, `medium`, `high`). Default `low` per ridurre consumi mantenendo una catena logica di base.
- `OPENAI_MAX_OUTPUT_TOKENS`: numero massimo di token di risposta (default `220`) per evitare output troppo lunghi mantenendo spazio per un razionale sintetico.

Il riepilogo automatico del reasoning è disattivato per evitare token aggiuntivi: viene richiesto solo il livello di sforzo indicato.

Ricorda di configurare anche `OPENAI_API_KEY` nel file `.env`.

### Quanto costa ogni chiamata

Il costo dipende dal modello scelto e dai token effettivamente elaborati (prompt + risposta). La formula di base è:

```
costo = (token_input / 1.000.000) * prezzo_input + (token_output / 1.000.000) * prezzo_output
```

Dove `prezzo_input` e `prezzo_output` sono le tariffe per milione di token indicate nel listino OpenAI per il modello scelto. Con la configurazione di default (`OPENAI_MODEL=gpt-5.1`, `OPENAI_MAX_OUTPUT_TOKENS=220`, `OPENAI_REASONING_EFFORT=low`), una chiamata tipica usa:

- i token del prompt che passi (dipendono dalla lunghezza del testo inviato al modello);
- al massimo ~220 token di risposta (limite impostato per contenere i costi mantenendo un breve razionale).

Per sapere il costo effettivo per chiamata:

1. Prendi le tariffe aggiornate da [openai.com/pricing](https://openai.com/pricing) per il modello che stai usando.
2. Stima i token di input del tuo prompt (puoi usare strumenti di conteggio token come `tiktoken`).
3. Moltiplica usando la formula sopra. Esempio: con 2.000 token di input e 300 di output, inserisci quei valori e le tariffe del modello che hai scelto per ottenere il costo della singola chiamata.

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

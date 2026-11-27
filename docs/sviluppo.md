# Sviluppo

## Avvio

Il modo normale è il Run & Go (`run-share-*` nella cartella principale, oppure `scripts/run-*` senza link pubblico):
installa uv, un Python 3.12 privato e le librerie dentro `.runtime/`, Ollama solo se serve, poi avvia i quattro servizi
sulle prime porte libere (8000, 8100, 8200, 8300) e apre il browser. Log in `.runtime/logs/`.

Opzioni del Run & Go: `RMB_MODEL=llama3.2:1b` (modello locale più leggero), `RMB_NO_AI=1` (senza AI),
`RMB_NO_BROWSER=1`, `NGROK_AUTHTOKEN=…` (link pubblico senza domanda).

Avvio a mano, con l'ambiente già creato dal Run & Go:

```bash
.runtime/venv/bin/python -m uvicorn unisis.main:app --port 8100 &
.runtime/venv/bin/python -m uvicorn unilearn.main:app --port 8200 &
.runtime/venv/bin/python -m uvicorn unicomms.main:app --port 8300 &
.runtime/venv/bin/python -m uvicorn app.main:app --port 8000
```

Per provare senza toccare i dati veri: una copia su altre porte con `ACADEMIC_HUB_DATA_DIR` su una cartella di prova
(per esempio `--port 18000`).

## Test e build

```bash
.runtime/venv/bin/python -m unittest discover -s tests   # test Python (date d'esame), senza AI né rete

cd web
npm install
npm test            # Vitest (con Node 26: NODE_OPTIONS=--no-experimental-webstorage npm test)
npm run typecheck
npm run build       # compila hub e aree staff in frontend/app, unilearn/, unisis/, unicomms/static/staff
```

I quattro file compilati sono nel repository (il Run & Go non richiede Node.js): dopo ogni modifica a `web/` vanno
ricompilati e committati. In caso di conflitto non si sistemano a mano: si ricompilano.

Zip per i collaboratori: `scripts/make-zip.sh` → `../RemindMeBro-demo-<data>[-<ramo>].zip`.

## Configurazione

L'AI si sceglie in `data/ai.env` (vedi [`ai.env.example`](../ai.env.example)); tutto il resto con variabili d'ambiente.

| Variabile | Predefinito | Note |
|---|---|---|
| `AI_PROVIDER` | `ollama` | `gemini`, `openrouter`, `omniroute`, `openai`, `custom` o `ollama` |
| `AI_API_KEY` | — | chiave del servizio |
| `AI_MODEL`, `AI_MODEL_FAST` | Gemini: `gemini-3.8-flash`, `gemini-3.5-flash-lite` | modello principale e veloce |
| `AI_MODEL_BACKUP` | Gemini: `gemini-flash-lite-latest` | altri modelli da provare se quelli sopra sono occupati |
| `AI_BASE_URL` | dal preset | qualsiasi indirizzo compatibile con OpenAI (`…/v1`) |
| `AI_FALLBACK_OLLAMA` | `true` | se l'AI esterna non risponde, Ollama (se acceso) |
| `AI_RETRY_WAITS`, `AI_BUSY_SKIP` | `10,30` · `300` | attese quando tutti i modelli sono occupati · quanto un modello occupato resta in fondo |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | `http://127.0.0.1:11434`, `llama3.2` | AI locale |
| `EXAM_DATES_DOUBLE_CHECK` | `true` | seconda domanda all'AI per ogni data d'esame trovata |
| `NOTES_TIMEOUT` | `1800` | secondi senza nessuna parola dall'AI prima di fermare appunti e chat sul materiale |
| `DEMO_REFERENCE_DATE` | `now` | data di "oggi" (una data ISO per fissarla; vale per tutti i servizi) |
| `UNILEARN_POLL_SECONDS` | `30` | controllo di nuovi avvisi e messaggi (0 = spento) |
| `PREMIUM_PRICE`, `PREMIUM_CURRENCY`, `PREMIUM_PERIOD` | `79`, `CZK`, `month` | prezzo mostrato (pagamento simulato) |
| `ACADEMIC_HUB_DATA_DIR` | `./data` | dati di tutti i servizi |
| `UNISIS_URL`, `UNILEARN_URL`, `UNICOMMS_URL` | `http://127.0.0.1:8100`, `…:8200`, `…:8300` | dove l'hub trova i servizi (UniLearn può essere un Moodle vero) |
| `JWT_SECRET_KEY` | generata in `data/.jwt_secret` | |
| `DEMO_PASSWORD` | `demo1234` | password di Giulia |

## API

Documentazione interattiva (Swagger) con il server avviato: **http://127.0.0.1:8000/docs** (hub),
http://127.0.0.1:8100/docs (UniSIS). Tutte le chiamate dell'hub richiedono `Authorization: Bearer <token>` tranne
`/api/auth/*`, `/api/health` e `/api/demo-accounts`; quelle `/api/professor/*` solo dal computer della demo.

| Gruppo | Endpoint principali |
|---|---|
| Accesso | `POST /api/auth/login`, `POST /api/auth/register`, `GET /api/auth/me` |
| Dati dello studente | `GET /api/deadlines`, `GET /api/schedule`, `GET /api/inbox`, `GET /api/courses`, `POST /api/sync` |
| Collegamenti | `GET /api/connections`, `POST /api/connections/moodle`, `POST /api/connections/unisis/start`, `GET /api/studies` |
| Date d'esame (Free) | `GET /api/found-dates`, `POST /api/found-dates/scan`, `POST /api/found-dates/{id}/accept` · `/reject` |
| AI (Premium) | `POST /api/chat`, `GET /api/notes`, `POST /api/notes/{id}/regenerate`, `POST /api/notes/{id}/chat` |
| Piano | `GET /api/billing`, `POST /api/billing/plan` |
| Docenti | `GET /api/professor/courses`, `POST /api/professor/announcements`, `GET /api/professor/extracted-deadlines` |
| Stato | `GET /api/health` (AI in uso e riserva, vector store) |

## Dati

Tutto sta in `data/` (fuori da git): database SQLite dei quattro servizi, ChromaDB, file dei corsi, modello Whisper,
chiavi e password dello staff. Per ripartire da zero: chiudere l'app e cancellare `data/` (si ricreano account, password
staff e gli otto corsi con l'orario). Le colonne nuove dei modelli si aggiungono da sole alle tabelle esistenti.

## Problemi comuni

- **L'AI non risponde** → `.runtime/venv/bin/python -m app.services.ai_remote` dice se la chiave è accettata e quale
  modello risponde. Con Gemini sovraccarico (503) l'app passa da sola ai modelli di riserva.
- **Ollama: `model "llama3.2" not found`** → `ollama pull llama3.2`.
- **"database is locked"** → non dovrebbe più succedere (WAL + un sync alla volta); se capita, guardare
  `.runtime/logs/backend.log`.
- **Il browser mostra la versione vecchia dell'interfaccia** → ricaricare con Ctrl+Shift+R.
- **`(trapped) error reading bcrypt version`** nei log → avviso innocuo di passlib.
- **Prima risposta lenta con Ollama** → il modello si carica in memoria la prima volta (5–20 s).

# Architettura

Remind Me Bro (l'hub) non ha dati suoi da inventare: li legge da tre servizi che simulano i sistemi di un'università.
Ogni servizio è un'app FastAPI separata, con il suo database SQLite in `data/`. Il Run & Go li avvia tutti insieme sulle
prime porte libere e li chiude insieme. Nessun Docker.

```
            UniSIS (8100)            UniLearn (8200)              UniComms (8300)
       segreteria tipo InSIS     LMS compatibile Moodle       posta + Teams dei docenti
                 │                        │                            │
          OAuth 2.0 + PKCE        Moodle web services             API con chiave
                 │                        │                            │
                 └────────────┬───────────┴──────────────┬─────────────┘
                              ▼                          ▼
                     ┌─────────────────────────────────────────────┐
                     │  Remind Me Bro · hub (8000)                 │
                     │  SQLite · ChromaDB · AI (Gemini o Ollama)   │
                     │  React SPA per studenti e docenti           │
                     └─────────────────────────────────────────────┘
```

## I servizi

### UniSIS — segreteria (`unisis/`, porta 8100)
Fa da InSIS: piano di studi e crediti, orario settimanale, iscrizione ai corsi con lista d'attesa, appelli, voti
(scala ceca: 1 excellent … 4 satisfactory, 5 fail). L'hub si collega come un'app vera: client OAuth 2.0 registrato
(client ID + secret + API key), **Authorization Code + PKCE**, schermata di consenso, token cifrati, refresh, revoca.
Area staff (`/staff`, React): corsi e orario, appelli, iscrizioni, *Apps & keys* con l'audit log delle chiamate dell'hub.
Dettagli in [`unisis/README.md`](../unisis/README.md).

### UniLearn — LMS (`unilearn/`, porta 8200)
Implementa un sottoinsieme reale del protocollo **Moodle**: `/login/token.php?service=moodle_mobile_app` e
`/webservice/rest/server.php` con le stesse richieste, risposte ed errori (`core_webservice_get_site_info`,
`core_enrol_get_users_courses`, `core_course_get_contents`, `mod_assign_*`, `mod_forum_*`, `core_calendar_*`, …).
Il client dell'hub (`app/services/unilearn_client.py`) funziona anche con un Moodle vero (`UNILEARN_URL`).
Area staff: corsi, lezioni e file (per Smart Notes e Find exams), compiti, avvisi, eventi; per l'admin il log delle chiamate.
Dettagli in [`unilearn/README.md`](../unilearn/README.md).

### UniComms — posta e Teams (`unicomms/`, porta 8300)
Un docente (scelto da un elenco, senza password, solo in locale) manda un'email tipo Outlook a tutti gli studenti di un
corso o a uno solo, oppure un post Teams nel canale del corso. L'hub legge `GET /api/v1/messages` con la chiave in
`data/unicomms/hub.key`. Un'email a uno studente diventa un messaggio personale; un messaggio cancellato esce dall'Inbox.

### Remind Me Bro — hub (`app/`, porta 8000)
API FastAPI + interfaccia React compilata in un solo file (`frontend/app/index.html`, sorgenti in `web/`).

| Parte | Dove |
|---|---|
| Sincronizzazione (pulsante Sync e controllo ogni 30 s) | `app/services/sync_service.py`, `live_sync.py`, `unilearn_client.py`, `unisis_client.py`, `unicomms_client.py` |
| Scadenze trovate nei messaggi | `app/services/llm_extractor.py` |
| Date d'esame nei file dei corsi (Free) | `app/services/exam_dates/` |
| Smart Notes e chat sul materiale (Premium) | `app/services/notes/` |
| Ask Bro (RAG su SQLite + ChromaDB) | `llm_extractor.answer_student_query`, `vector_store.py` |
| AI esterna (Gemini o API compatibile con OpenAI) | `app/services/ai_remote.py` |
| Chi vede cosa | `app/services/my_courses.py`, `app/api/access.py` |

## Scelte tecniche

- **Niente date inventate.** Nei messaggi: senza riferimenti temporali nel testo, nessuna scadenza. Nei file dei corsi:
  solo le righe con una data e una parola d'esame vanno all'AI, che deve copiare la frase parola per parola; il codice
  controlla che la frase sia nel file e contenga la stessa data (lettore di date senza AI, `exam_dates/dates.py`), poi
  una seconda domanda sì/no all'AI. Lo studente conferma ogni data prima che vada nel calendario.
- **La data ufficiale vince.** Se un avviso sposta un compito, la vecchia data è nascosta (`superseded_by_id`), non
  cancellata; se poi il docente cambia la data in UniLearn, vale di nuovo quella ufficiale.
- **Sincronizzazione idempotente.** Chiave `source + external_id`: rifare il Sync non duplica nulla. Un sync alla volta
  (`SYNC_LOCK`); database in modalità WAL.
- **AI esterna con riserve.** Formato OpenAI (`/chat/completions`), streaming per i lavori lunghi con tasto Stop.
  Se un modello è occupato (503, 429) si passa subito al successivo della catena; solo alla fine si usa Ollama.
- **JSON robusto.** Risposte in JSON, `parse_llm_json()` ripara gli errori comuni, poi validazione con Pydantic.
- **Un file si legge una volta.** Il testo estratto (`extracted_texts`) e le date trovate (`file_scans`) sono per
  contenuto del file, condivisi tra gli studenti.
- **Demo pubblica sicura.** Dal link pubblico (ngrok) si raggiunge solo l'hub. Area docenti, aree staff e accesso
  veloce funzionano solo con richieste dirette a 127.0.0.1 senza intestazioni di proxy (`app/api/access.py`). Le password
  dello staff sono casuali (`data/STAFF-PASSWORDS.txt`); Giulia resta con `demo1234` per entrare veloce.
- **Dati separati tra studenti.** Spunte "fatto", messaggi personali, appunti e date accettate sono per studente; ogni
  studente vede solo i corsi che segue.

## Struttura delle cartelle

```
RemindMeBro/
├── run-share-mac.command · run-share-windows.bat · run-share-linux.sh
├── START-HERE.txt · ai.env.example · requirements.txt · requirements-whisper.txt
├── app/
│   ├── main.py · config.py
│   ├── api/            endpoint: auth, studente, docente, connessioni, note, date trovate, premium
│   ├── database/       modelli SQLAlchemy e connessione (WAL, colonne nuove aggiunte da sole)
│   ├── services/       sync, AI, client dei tre servizi, exam_dates/, notes/
│   └── mocks/          catalogo corsi iniziale
├── unisis/ · unilearn/ · unicomms/
│   ├── main.py, models.py, seed.py, staff.py, …
│   └── static/staff/index.html     area staff React compilata
├── web/                sorgenti React (hub + aree staff), Vite, Vitest
├── frontend/           app/index.html (React compilata) · index.html (interfaccia vecchia, /classic)
├── scripts/            run.sh · run.ps1 (Run & Go), run-linux.sh · run-mac.command · run-windows.bat,
│                       share.py (link pubblico + QR), make-zip.sh
├── tests/              test Python senza AI né rete
└── docs/
```

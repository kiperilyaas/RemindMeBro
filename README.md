# Academic Unified Hub & AI Assistant — Backend PoC

Backend **100% locale e a costo zero** che centralizza i flussi universitari
(UniLearn/Moodle, UniSIS, Teams, Email) e dimostra l'**estrazione automatica delle scadenze da testo libero**
con un LLM locale (**Ollama + llama3.2**) e un **assistente RAG** (ChromaDB + SQLite).

```
            ┌──────────────┐  Moodle WS API    ┌──────────────┐
 UniLearn ─▶│ unilearn_    │──────────────────▶│              │
 (8200)     │ client       │─ avvisi ─▶ AI     │              │
            └──────────────┘                   │              │
            ┌──────────────┐  OAuth 2.0 API    │              │
 UniSIS ───▶│ unisis_client│──────────────────▶│              │
            └──────────────┘                   │   SQLite     │◀── GET /api/deadlines
            ┌──────────────┐  testo informale  │ (Course,     │    GET /api/courses
 Teams  ───▶│  teams_mock  │──┬──▶ llama3.2 ──▶│  Deadline,   │
            └──────────────┘  │   (JSON)       │  Announce.,  │
                              │                │  Event)      │
                              └──▶ ChromaDB ───┴──────┬───────┘
                                   (vettori)          ▼
                                              RAG ─▶ llama3.2 ─▶ POST /api/chat
```

**Novità: partenza da zero (24 novembre 2026).** Hub, UniLearn e UniSIS partono vuoti: restano solo gli account
(password `demo1234`). La data è sempre quella di oggi (`DEMO_REFERENCE_DATE=now`). I corsi si creano dalle aree staff:
UniLearn `/staff` → *New course* (compiti, avvisi, eventi, iscritti), UniSIS `/staff` → *Courses → New course*
(orario settimanale, iscritti) ed *Exams → New exam date*, hub → area docente → *New course*. Lo stesso codice nei tre
sistemi è lo stesso corso: quando Giulia collega UniLearn o UniSIS, l'hub crea da solo i corsi che non conosce ancora.
I dati restano salvati in `data/`; al primo avvio di questa versione i vecchi dati demo vengono cancellati una volta.
"Try a case" resta solo nell'area docente dell'hub.
**Demo pubblica (24 novembre).** Dal link pubblico (ngrok) l'area docenti è chiusa: login, registrazione e token da
docente funzionano solo per richieste dirette a 127.0.0.1 senza intestazioni di proxy (`app/api/access.py`). Gli account
staff (docenti hub, admin e docenti UniLearn, segreteria UniSIS) ricevono al primo avvio password casuali al posto di
`demo1234`, raccolte in `data/STAFF-PASSWORDS.txt`; nessuna pagina mostra più password. Gli studenti si registrano da soli:
l'hub crea anche gli account UniSIS (`POST /api/v1/provisioning/students`, credenziali OAuth del client) e UniLearn
(`POST /admin/tool/provision/student`, chiave in `data/unilearn/provisioning.key`) e li collega subito
(`app/services/provisioning.py`). Ogni studente ha le sue spunte "fatto" (tabella `deadline_done`) e la sync di UniLearn
tocca solo i corsi di chi sincronizza. Il database dell'hub aggiunge tabelle e colonne nuove senza ricrearsi.

Gli 8 corsi della demo sono a scelta: Giulia li sceglie in Studies → Course registration (iscrizione UniSIS) e l'hub
la iscrive o la toglie anche in UniLearn (web service `enrol_self_enrol_user` e `local_unilearn_self_unenrol`). Nell'hub
lo studente vede scadenze, eventi e avvisi solo dei corsi che segue (`app/services/my_courses.py`). Per ripartire da zero: chiudi l'app e cancella `data/`.

**Novità v0.3:** interfaccia interamente in inglese e corsi demo di **Economics & Finance**
(Microeconomics, Corporate Finance, Financial Accounting, Financial Markets and Institutions, Econometrics);
anche le risposte dell'AI e i messaggi mock sono in inglese. Il database locale viene rigenerato
automaticamente al primo avvio.

**v0.2:** autenticazione JWT con due ruoli (**Studente** / **Docente**), area docente
per pubblicare avvisi con estrazione AI automatica, e frontend SPA (`frontend/index.html`) collegato alle API.

## Stack

| Componente | Tecnologia |
|---|---|
| API | Python 3.11+ · FastAPI · Uvicorn |
| DB relazionale | SQLite · SQLAlchemy 2.0 |
| Vector DB | ChromaDB (persistente in `data/chroma`) |
| LLM | Ollama · `llama3.2` (3B) |
| Auth | JWT (python-jose) · bcrypt (passlib) |
| Frontend | SPA in un solo file HTML (`frontend/index.html`), servita da FastAPI |

---

## Area docenti e segreteria + casi pronti (novità v0.7)

Tutta la parte "staff" è rifatta in React con uno stile unico, minimale (grigi neutri, bordi sottili, un colore per sistema):

| Sistema | Indirizzo | Chi | Cosa |
|---|---|---|---|
| Hub | http://127.0.0.1:8000 (login docente) | `chiara.neri@demo.it`, … | Courses, Announce (risultato AI), Dates found by AI, **Try a case** |
| UniLearn | http://127.0.0.1:8200/staff | `chiara.neri`, `marco.rossi`, … · `admin` | corsi, compiti (data modificabile al clic), avvisi, Web services (admin), **Try a case** |
| UniSIS | http://127.0.0.1:8100/staff | `registrar` | appelli e finestre, posti, corsi e lista d'attesa, studenti, Apps & keys, **Try a case** |

**Try a case**: ogni scheda esegue con un clic un'azione reale nel sistema e dice cosa controllare nell'hub
come Giulia. Quasi tutti hanno **Undo**, così si possono ripetere.

| Dove | Caso | Cosa vedi nell'hub dopo Sync |
|---|---|---|
| UniLearn | Move a deadline (Problem Set 2 → 2 Nov) | la data ufficiale vince sulla data trovata dall'AI in Teams |
| UniLearn | Hide a deadline in an announcement | l'AI trova "bank shortlist" (30 Oct) nell'avviso |
| UniLearn | Post a message without a date | nessuna scadenza inventata |
| UniLearn | Add an urgent assignment | quiz per domani, evidenziato come urgente |
| UniLearn | Giulia hands in her work | Excel lab spuntato come fatto |
| UniLearn | Cut off Remind Me Bro | "Token deleted", va ricollegato |
| UniSIS | Open the winter exam session now | pulsanti "Register" attivi in Studies |
| UniSIS | Add seats to a full test | Financial Accounting test di nuovo prenotabile |
| UniSIS | Open a second room for a full elective | dalla lista d'attesa a "Enrolled" |
| UniSIS | Reschedule a test | Econometrics lab test spostato al 3 Dec |
| UniSIS | Revoke Remind Me Bro's access | "Reconnect your student record" |
| Hub | Extend a deadline / relative date / no date / formal assignment | estrazione AI dal vivo |

Le API staff sono in `unilearn/staff.py` e `unisis/staff.py` (`/staff/api/*`, cookie di sessione + header
`X-Requested-With: staff` contro il CSRF). Le pagine studente di UniLearn e UniSIS restano quelle di prima;
le vecchie pagine staff restano raggiungibili (`/admin` in UniSIS, `/course/<id>` in UniLearn).

## Nuova interfaccia React (v0.6)

L'hub ha una UI nuova (stile "Timeline", proposta B) scritta in **React 18 + TypeScript** in `web/`.
La build è un unico file HTML già compilato in `frontend/app/index.html`: il Run & Go non richiede Node.js.

| Ruolo | Sezioni |
|---|---|
| Studente | **Timeline** (giorno per giorno: lezioni, scadenze, esami, *Plan my week* con blocchi di studio), **Inbox** (riassunto AI per messaggio), **Studies** (UniSIS live: appelli, prove parziali, elective, libretto), **Semester** (carico di lavoro per settimana + una corsia per corso), **AI** (Premium: Ask Bro e Smart Notes), **Connect** (UniLearn e UniSIS) |
| Docente | **My courses** (statistiche, nuovo compito, nuovo corso), **Announce** (pubblica e vedi subito cosa ha capito l'AI), **AI dates** (correggi o scarta) |

La vecchia interfaccia resta su **http://127.0.0.1:8000/classic**. Sviluppo e test della UI: vedi [`web/README.md`](web/README.md)
(`npm run dev`, `npm test`, `npm run build`).

## Premium: Ask Bro e Smart Notes

La sezione **AI** dello studente contiene Ask Bro (la chat) e Smart Notes. Le due funzioni sono a pagamento: chi è sul piano Free vede i prezzi e un checkout simulato (nessuna carta, nessun addebito). Il piano si cambia anche da **Account → Plan** con un interruttore. Giulia (`student@demo.it`) parte su Premium; ogni altro studente parte su Free.

- Prezzo: `app/config.py`, righe `PREMIUM_PRICE` (79), `PREMIUM_CURRENCY` (CZK) e `PREMIUM_PERIOD` (month). Si possono anche impostare con le variabili d'ambiente con lo stesso nome. Dopo la modifica va riavviato il Run & Go.
- Smart Notes legge con i web service di Moodle (`core_course_get_contents` + `webservice/pluginfile.php`) i file che il docente carica in UniLearn → `/staff` → corso → *Lessons and materials*: PDF, PPTX, DOCX, TXT, audio e video. Funziona anche con un Moodle vero.
- Niente parte da solo: la sync trova lezioni e file (stato "Not made yet") e lo studente preme **Make notes** sulla lezione che vuole. Solo allora l'app legge i file, trascrive le registrazioni e scrive gli appunti.
- Per ogni lezione: testo da slide e documenti (`pypdf`, `python-pptx`, `python-docx`), trascrizione delle registrazioni con `faster-whisper` sul computer, poi llama3.2 scrive titolo, riassunto, punti chiave e definizioni. Stati: Queued, Syncing, Transcribing, AI processing, Ready, Error.
- Nella pagina di una lezione, la scheda **Ask the material** apre una chat che risponde solo con i file caricati: tutta la lezione oppure un file scelto dall'elenco. Il testo è diviso in pezzi che ricordano la slide, la pagina o il minuto della registrazione; i pezzi più vicini alla domanda (per significato con ChromaDB e per parole in comune) vanno a llama3.2, che cita le fonti come [1], [2]. Se la risposta non è nel materiale, lo dice. La conversazione è salvata (una per lezione e una per ogni file) e si cancella con "Delete this conversation". Endpoint: `GET/POST/DELETE /api/notes/{id}/chat` (`?source_id=` per un file).
- Lo studente legge, modifica (Markdown), copia o salva in PDF. Se il docente aggiunge file, gli appunti restano com'erano e mostrano "New material"; si rifanno con "Make notes again".
- Run & Go installa `faster-whisper` in un passo a parte (`requirements-whisper.txt`) e scarica il modello `base` (~150 MB) in `data/whisper` in sottofondo. Se l'installazione non riesce l'app parte lo stesso e salta audio e video. FFmpeg non serve: è già dentro PyAV.

## Avvisi dei docenti in tempo reale

Un avviso pubblicato in UniLearn (**Post an announcement**) arriva nell'Inbox degli studenti iscritti a quel corso entro circa mezzo minuto, senza premere Sync: l'hub legge i forum Announcements ogni 30 secondi (`app/services/live_sync.py`, variabile `UNILEARN_POLL_SECONDS`, 0 = spento) e l'app chiede i nuovi messaggi ogni 30 secondi, con un avviso a schermo. Lo studente vede solo i messaggi dei corsi che segue: se il corso non ha iscritti, UniLearn lo segnala sopra il modulo. Nell'Inbox i messaggi appena arrivati hanno l'etichetta **New** e una barra in alto ("1 new message just arrived"); la barra avvisa anche quando un messaggio non letto è nascosto dal filtro (es. un avviso senza scadenza non è "Important") e lo mostra con *Show all*. Il numero dei non letti compare sulla voce Inbox e nel titolo della scheda del browser, es. "(2) Remind Me Bro".

## Tre programmi, un solo avvio (v0.5)

| Servizio | Porta | Cosa fa | Come si collega l'hub |
|---|---|---|---|
| **Remind Me Bro** (hub + SPA) | 8000 | dashboard, AI, chat RAG | — |
| **UniSIS** (`unisis/`) | 8100 | segreteria: orario, appelli, iscrizioni, voti | OAuth 2.0 + PKCE (client ID, secret, API key) |
| **UniLearn** (`unilearn/`) | 8200 | LMS **compatibile con Moodle**: corsi, compiti, consegne, calendario, forum avvisi | **API web service di Moodle** con token personale |

Il Run & Go (sezione 0) li avvia **tutti e tre** con un solo doppio clic, sulle prime porte libere,
e li chiude insieme. Nessun Docker: ogni servizio è un'app FastAPI con il suo database SQLite in `data/`.

## UniLearn — il nostro Moodle (novità v0.5)

`unilearn/` implementa un sottoinsieme **reale** del protocollo Moodle, con le stesse richieste e risposte:
`/login/token.php?service=moodle_mobile_app` (username + password → token di 32 caratteri esadecimali) e
`/webservice/rest/server.php?wstoken=…&wsfunction=…&moodlewsrestformat=json`, sintassi degli array
(`courseids[0]=1`) e formato degli errori (`invalidtoken`, `invalidlogin`, …). Funzioni disponibili:
`core_webservice_get_site_info`, `core_enrol_get_users_courses`, `mod_assign_get_assignments`,
`mod_assign_get_submission_status`, `core_calendar_get_calendar_events`, `mod_forum_get_forums_by_courses`,
`mod_forum_get_forum_discussions`. Il client dell'hub (`app/services/unilearn_client.py`) funziona anche
con un Moodle vero: basta `UNILEARN_URL=https://moodle.tuo-ateneo.it`.

L'hub **non contiene più i compiti Moodle finti**: compiti, stato delle consegne, eventi e avvisi arrivano
solo collegando UniLearn. La password viene usata una volta per ottenere il token e non viene salvata;
il token è cifrato nel DB. Gli avvisi del forum passano dall'AI (una sola volta per post) come i messaggi Teams.

| Cosa | Dove |
|---|---|
| Portale UniLearn | http://127.0.0.1:8200 — studente `giulia.esposito`, docenti `chiara.neri`, `marco.rossi`, …, admin `admin` (password `demo1234`) |
| Nell'hub | **Connections → UniLearn**: username + password → **Connect** |

Flusso demo consigliato:
1. Hub (studente) → Connections → **UniLearn** → `giulia.esposito` / `demo1234` → Connect: compaiono 5 compiti e 2 eventi.
2. UniLearn come `marco.rossi` → corso Microeconomics → **Change due date** del Problem Set, oppure **Post an announcement**
   ("Please send a one-page report by 5 November") → nell'hub **Sync now**: la data ufficiale si aggiorna, l'AI trova la scadenza nell'avviso.
3. UniLearn come `giulia.esposito` → consegna un compito → Sync: nell'hub risulta completato.
4. UniLearn come `admin` → **Web services**: log in tempo reale di ogni chiamata dell'hub e token attivi.
5. UniLearn → *Security keys* → **Delete** del token: l'hub mostra "Token deleted" e chiede di ricollegarsi.

## UniSIS — il nostro sistema di segreteria (v0.4)

`unisis/` è un **servizio separato** (porta 8100, database proprio) che fa da InSIS / Esse3 dell'ateneo demo:
piano di studi e crediti, orario, **iscrizione ai corsi** con lista d'attesa, **iscrizione agli appelli**, voti,
portale studente e back office della segreteria. Remind Me Bro si collega con una **connessione vera**:
client OAuth 2.0 registrato (client ID + secret + API key), **Authorization Code + PKCE**, schermata di consenso,
token cifrati, refresh automatico, revoca dallo studente. Design completo in [`unisis/README.md`](unisis/README.md).

| Cosa | Dove |
|---|---|
| Portale UniSIS | http://127.0.0.1:8100 — studente `giulia.esposito`, segreteria `registrar` (password `demo1234`) |
| API UniSIS (Swagger) | http://127.0.0.1:8100/docs |
| Nell'hub | **Connections → Connect UniSIS**, poi la nuova pagina **Studies** |

Flusso demo consigliato:
1. Hub (studente) → Connections → **Connect UniSIS** → login su UniSIS → **Allow access** → si torna su *Studies*.
2. Prenota la *Midterm test* di Financial Markets (3 posti) e iscriviti a un elective pieno (lista d'attesa): le azioni vengono scritte su UniSIS.
3. *Today* e *Schedule* mostrano orario e promemoria delle finestre d'iscrizione presi da UniSIS.
4. In UniSIS come `registrar`: **Open now** su un appello → in *Studies* premi Refresh e prenotalo.
5. UniSIS → *Apps & keys*: client ID, secret (hash), API key, token attivi e **audit log** di ogni chiamata dell'hub.
6. Portale studente UniSIS → *Connected apps* → **Revoke**: l'hub chiede di riconnettersi.

## 0. Run & Go (un clic, nessuna installazione manuale)

Per far provare l'app a chi non ha Python né Ollama (es. un Mac "pulito"):

| Sistema | File da aprire |
|---|---|
| macOS | `run-mac.command` (doppio clic) |
| Windows | `run-windows.bat` (doppio clic) |
| Linux | `./run-linux.sh` |

Lo script (`scripts/run.sh` per Mac/Linux, `scripts/run.ps1` per Windows):
1. scarica **uv** e un **Python 3.12** privato dentro `.runtime/` (niente installazioni di sistema);
2. crea l'ambiente e installa `requirements.txt` (solo se è cambiato);
3. usa Ollama se c'è già, altrimenti: **Mac** → scarica la versione CLI dentro `.runtime/ollama`,
   **Windows** → installer per-utente senza admin, **Linux** → installer ufficiale (chiede la password);
4. scarica `llama3.2` (~2 GB, una volta sola) e il modello di ricerca di ChromaDB;
5. avvia **UniSIS** (8100–8110), **UniLearn** (8200–8210) e l'hub (8000–8010) sulle prime porte libere,
   collega l'hub ai due servizi e **apre il browser**; nel terminale stampa tutti gli account demo.

Chiudendo la finestra del terminale si fermano hub, UniSIS, UniLearn e Ollama (se l'ha avviato lo script).
Opzioni: `RMB_MODEL=llama3.2:1b` (modello più leggero), `RMB_NO_AI=1` (senza AI), `RMB_NO_BROWSER=1`.
Istruzioni per l'utente finale (IT/EN) in `START-HERE.txt`.

**Link pubblico per gli amici:** `run-share-mac.command` / `run-share-windows.bat` / `run-share-linux.sh`
fanno lo stesso avvio con `RMB_SHARE=1`: scaricano ngrok in `.runtime/ngrok`, chiedono una volta il token
(o lo prendono da `NGROK_AUTHTOKEN`), aprono un tunnel sulla porta dell'hub e lanciano `scripts/share.py`,
che stampa il QR code nel terminale e scrive `.runtime/share/qr.html` e `url.txt`. Le API del frontend usano
l'origine della pagina, quindi l'hub funziona dal link; UniSIS e UniLearn restano locali (il consenso OAuth
di UniSIS da un altro dispositivo non funziona). Per ripartire da zero cancella `.runtime/` e `data/`.

## 1. Installare e avviare Ollama

**Linux (Arch)**
```bash
sudo pacman -S ollama          # oppure: curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama    # oppure, in un terminale dedicato: ollama serve
```
**macOS / Windows:** scarica l'installer da https://ollama.com/download

Scarica e prova il modello (≈2 GB, solo la prima volta):
```bash
ollama run llama3.2
# scrivi un messaggio di prova, poi esci con /bye
```
Ollama resta in ascolto su `http://127.0.0.1:11434`.

## 2. Installare le dipendenze Python

```bash
cd academic_hub_backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Avviare il server backend

```bash
uvicorn unisis.main:app --port 8100 &      # segreteria
uvicorn unilearn.main:app --port 8200 &    # LMS compatibile Moodle
uvicorn app.main:app --reload              # hub (porta 8000)
```

La data di "oggi" della demo è fissata a **martedì 20/10/2026 09:30** (coerente con i dati mock
e con il frontend). Per usare l'orologio di sistema: `DEMO_REFERENCE_DATE=now uvicorn app.main:app --reload`.

> Se hai già avviato la versione precedente, il database in `data/` viene **ricreato automaticamente**
> al primo avvio (lo schema è cambiato; i dati sono tutti mock e vengono rigenerati).

## 4. Aprire il frontend

Con il server avviato apri **http://127.0.0.1:8000/** (la SPA è servita dallo stesso server, nessun problema di CORS).
In alternativa puoi aprire `frontend/index.html` direttamente dal disco: le chiamate vanno a
`http://localhost:8000/api` e il `CORSMiddleware` le accetta. Se il backend non risponde compare il
banner **"Backend non connesso su localhost:8000"** e l'app riprova da sola ogni 8 secondi.

### Account demo (password `demo1234`)

| Ruolo | Email | Corso |
|---|---|---|
| Studente | `student@demo.it` | – |
| Docente | `marco.rossi@demo.it` | Microeconomics |
| Docente | `laura.bianchi@demo.it` | Corporate Finance |
| Docente | `giovanni.verdi@demo.it` | Financial Accounting |
| Docente | `chiara.neri@demo.it` | Financial Markets and Institutions |
| Docente | `paolo.conti@demo.it` | Econometrics |

Sono cliccabili nella schermata di login. Ci si può anche registrare scegliendo **Studente** o **Docente**:
un docente che si registra con lo stesso nome di un docente Moodle (es. "Prof. Marco Rossi") riceve
automaticamente quel corso, oppure può crearne uno nuovo da "I Miei Corsi".

### Flusso demo consigliato
1. **Studente** → *Connections* → collega **UniLearn** (e UniSIS), poi *Sync all*: l'AI trova le scadenze nei messaggi
   (il Problem Set di Microeconomics passa dal 23/10 al 30/10, la data Moodle vecchia sparisce;
   se poi il docente cambia la data ufficiale in UniLearn, vale di nuovo quella).
2. **Inbox**, **Schedule** → *Plan my week*, **Ask Bro** (chat RAG con llama3.2).
3. Logout → **Docente** (`chiara.neri@demo.it`) → *Pubblica Avviso*: scrivi
   "Hi everyone, the project deadline is moved to 25 October at 18:00" e guarda il JSON di Ollama,
   la scadenza salvata e il compito Moodle aggiornato.
4. *Scadenze Estratte dall'AI*: correggi o scarta un'estrazione sbagliata.
5. Torna studente: la nuova scadenza è già in *Today*.

## 5. Testare le API con Swagger UI

Apri **http://127.0.0.1:8000/docs**, clicca **Authorize** e inserisci email e password
(es. `student@demo.it` / `demo1234`; per gli endpoint docente usa un account docente). Poi esegui in ordine:

| # | Endpoint | Cosa mostra agli sponsor |
|---|---|---|
| 0 | `GET /api/health` | Ollama raggiungibile, modello presente |
| 1 | `POST /api/sync` | Import UniLearn (se collegato) + Teams + email + UniSIS; in `ai_details` le scadenze estratte dall'AI e il rilevamento dello **slittamento** del Problem Set di Microeconomics (23/10 → 30/10) |
| 2 | `GET /api/deadlines` | Vista unificata ordinata per data: `source=moodle` vs `source=teams` con `extracted_by_ai=true` |
| 3 | `GET /api/courses` | Corsi attivi |
| 4 | `POST /api/simulate-teams-message` | **Demo live:** scrivi un messaggio inventato e guarda l'estrazione in tempo reale |
| 5 | `POST /api/chat` | Domande in linguaggio naturale con risposta basata solo sul contesto locale |

### Esempi via curl

```bash
# login -> token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"student@demo.it","password":"demo1234"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# collega UniLearn (Moodle web services): la password serve solo per ottenere il token
curl -X POST http://127.0.0.1:8000/api/connections/moodle -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"username":"giulia.esposito","password":"demo1234"}'

curl -X POST http://127.0.0.1:8000/api/sync -H "Authorization: Bearer $TOKEN"
curl http://127.0.0.1:8000/api/deadlines -H "Authorization: Bearer $TOKEN"

curl -X POST http://127.0.0.1:8000/api/chat -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "When is the Microeconomics problem set due?"}'

# docente: pubblica un avviso (estrazione AI automatica)
PTOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"chiara.neri@demo.it","password":"demo1234"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -X POST http://127.0.0.1:8000/api/professor/announcements -H "Authorization: Bearer $PTOKEN" \
  -H "Content-Type: application/json" \
  -d '{"course_id": 4, "content": "Hi everyone, the project deadline is moved to 25 October at 18:00.", "channel": "teams"}'
```

Messaggi utili per la demo live (l'LLM capisce anche l'italiano, ma risponde sempre in inglese):
- *"No lecture tomorrow. The Econometrics regression report is now due on 20 November at noon."*
- *"Registration for the Corporate Finance midterm is open until next Thursday."*
- *"Have a nice weekend everyone!"* → `has_deadline: false` (caso negativo)

---

## Endpoint disponibili

Tutti gli endpoint richiedono `Authorization: Bearer <token>` tranne `/api/auth/*` (register/login/token),
`/api/health` e `/api/demo-accounts`. Gli endpoint `/api/professor/*` richiedono il ruolo docente (altrimenti 403).

| Metodo | Path | Descrizione |
|---|---|---|
| POST | `/api/auth/register` | Registrazione (email, password, nome completo, ruolo) → token + profilo |
| POST | `/api/auth/login` | Login JSON → `access_token` JWT + profilo |
| POST | `/api/auth/token` | Login form OAuth2 (pulsante *Authorize* di Swagger) |
| GET | `/api/auth/me` | Profilo dell'utente del token |
| POST | `/api/sync` | Pipeline completa di sincronizzazione + estrazione AI |
| GET | `/api/inbox` | Inbox unificata con riassunto AI (scadenza rilevata o no) |
| GET | `/api/schedule` | Orario in un intervallo (`?start=2026-10-19&end=2026-10-25`, default settimana corrente) |
| GET | `/api/professor/courses` | Corsi del docente con statistiche |
| POST | `/api/professor/courses` | Crea un corso |
| POST | `/api/professor/announcements` | Pubblica un avviso → salvataggio + ChromaDB + estrazione llama3.2 |
| GET | `/api/professor/announcements` | Avvisi pubblicati dal docente |
| POST | `/api/professor/assignments` | Crea un compito formale con scadenza |
| GET | `/api/professor/extracted-deadlines` | Scadenze estratte dall'AI dai suoi messaggi/corsi |
| PATCH | `/api/professor/extracted-deadlines/{id}` | Corregge titolo/data di un'estrazione |
| DELETE | `/api/professor/extracted-deadlines/{id}` | Scarta un'estrazione (ripristina l'eventuale data Moodle sostituita) |
| GET | `/api/deadlines` | Scadenze ordinate per data (`?include_completed=false&source=teams&course_id=1`) |
| PATCH | `/api/deadlines/{id}/complete` | Segna una scadenza come completata |
| GET | `/api/courses` | Corsi attivi |
| GET | `/api/announcements` | Avvisi recenti (Moodle + Teams) |
| GET | `/api/events` | Eventi di calendario |
| POST | `/api/chat` | Assistente RAG (`{"question": "...", "include_context": true}` per vedere il contesto) |
| POST | `/api/simulate-teams-message` | Estrazione in tempo reale da un messaggio arbitrario |
| GET | `/api/connections` | Stato di UniSIS, UniLearn, Teams, email |
| POST | `/api/connections/moodle` | Collega UniLearn: `{username, password}` → token Moodle (password non salvata) |
| POST | `/api/connections/moodle/sync` | Importa compiti, consegne, eventi e avvisi (con AI) |
| DELETE | `/api/connections/moodle` | Scollega UniLearn |
| POST | `/api/connections/unisis/start` | Avvia l'OAuth verso UniSIS (callback: `/api/connections/unisis/callback`) |
| GET | `/api/studies` | Dati live da UniSIS (appelli, iscrizioni, voti) |
| GET | `/api/health` | Stato di Ollama e del vector store (pubblico) |
| GET | `/api/demo-accounts` | Account demo per la schermata di login (pubblico) |

## Struttura del progetto

```
academic_hub_backend/
├── run-mac.command / run-windows.bat / run-linux.sh   # Run & Go
├── scripts/run.sh, scripts/run.ps1
├── START-HERE.txt              # istruzioni per l'utente finale
├── unilearn/                   # UniLearn: Moodle-compatible LMS (separate service, port 8200)
│   ├── main.py, ws.py, web.py  # login/token.php + webservice/rest/server.php, web portal
│   ├── models.py, seed.py      # courses, assignments, submissions, forums, calendar, tokens
│   ├── staff.py                # API /staff/api (docenti, admin) + casi pronti
│   └── templates/, static/     # static/staff/index.html = app React compilata
├── unisis/                     # UniSIS: student information system (separate service, port 8100)
│   ├── main.py, api.py, web.py # REST API v1 + OAuth 2.0, web portal (student + registrar)
│   ├── models.py, services.py  # data model and business rules (windows, capacity, waiting list)
│   ├── seed.py, security.py    # demo data, hashing, PKCE, client credentials
│   ├── staff.py                # API /staff/api (segreteria) + casi pronti
│   └── templates/, static/
├── web/                        # sorgenti React + TypeScript: hub, area UniLearn /staff, area UniSIS /staff (Vite, Vitest)
├── frontend/
│   ├── app/index.html          # UI React compilata (un solo file), servita su http://127.0.0.1:8000/
│   └── index.html              # interfaccia precedente, servita su /classic
├── app/
│   ├── main.py                 # FastAPI app, lifespan (DB, seed demo), CORS, frontend
│   ├── config.py               # impostazioni (env vars)
│   ├── database/
│   │   ├── db.py               # engine, sessioni, init_db
│   │   └── models.py           # User, Course, Deadline, Announcement, Event
│   ├── mocks/
│   │   ├── moodle_mock.py      # solo il catalogo corsi (il resto arriva da UniLearn)
│   │   └── teams_mock.py       # messaggi informali dei docenti
│   ├── services/
│   │   ├── vector_store.py     # ChromaDB: indicizzazione + ricerca semantica
│   │   ├── llm_extractor.py    # estrazione JSON + chatbot RAG
│   │   ├── unilearn_client.py  # client Moodle web services (token, sync compiti/eventi/avvisi)
│   │   ├── unisis_client.py    # client OAuth 2.0 + PKCE verso UniSIS
│   │   └── sync_service.py     # pipeline di sincronizzazione
│   └── api/
│       ├── connections_endpoints.py  # UniSIS connection (OAuth client) + Studies
│       ├── auth.py             # JWT, bcrypt, register/login/me, ruoli, account demo
│       ├── endpoints.py        # route studente (protette da Bearer token)
│       ├── professor_endpoints.py  # route docente
│       └── schemas.py          # schemi Pydantic
├── data/                       # creata all'avvio (SQLite + ChromaDB)
├── requirements.txt
└── README.md
```

## Scelte tecniche rilevanti

- **Output JSON robusto:** Ollama è chiamato con `format="json"` e `temperature=0`; in più
  `parse_llm_json()` rimuove i blocchi ```` ```json ```` , estrae il primo oggetto `{...}`
  bilanciato, ripara virgole finali e `True/False/None`. Il risultato è validato con Pydantic
  (date in più formati, scadenze senza data scartate).
- **Few-shot + data di riferimento** nel prompt: l'LLM risolve "venerdì prossimo" e l'anno mancante.
- **Collegamento al corso:** match esatto → sottostringa → fuzzy (`difflib`) → canale Teams di provenienza.
- **Sincronizzazione idempotente:** chiave `source + external_id`; rieseguire `/api/sync` non duplica nulla.
- **Date spostate:** se un avviso sposta un compito Moodle, la vecchia scadenza viene marcata
  `superseded_by_id` e nascosta (resta in DB per tracciabilità); `GET /api/deadlines?include_superseded=true` la mostra.
- **Sicurezza PoC:** password bcrypt, JWT HS256 firmato con una chiave casuale salvata in `data/.jwt_secret`
  (o `JWT_SECRET_KEY`). Le registrazioni come docente sono libere: in produzione andrebbero approvate.
- **Data ufficiale vs data dell'avviso:** se il docente cambia la scadenza direttamente in UniLearn, la data
  ufficiale torna a valere e la scadenza estratta dall'AI da un messaggio precedente viene nascosta.
- **Anti-allucinazione:** se il messaggio non contiene alcun riferimento temporale (date, giorni, "tomorrow", …)
  un'eventuale scadenza proposta dall'LLM viene scartata.
- **Degrado controllato:** se Ollama o ChromaDB non sono disponibili, i dati UniLearn vengono comunque
  importati e gli errori sono riportati nel campo `errors` del riepilogo.

## Configurazione (variabili d'ambiente)

| Variabile | Default | Note |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | |
| `OLLAMA_MODEL` | `llama3.2` | |
| `DEMO_REFERENCE_DATE` | `now` | orologio del computer; una data ISO per fissarla (vale anche per UniLearn e UniSIS) |
| `JWT_SECRET_KEY` | generata in `data/.jwt_secret` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | durata del token (12 h) |
| `DEMO_SEED_USERS` | `true` | crea gli account demo all'avvio |
| `DEMO_PASSWORD` | `demo1234` | |
| `CORS_ORIGINS` | `*` | lista separata da virgole |
| `CHROMA_MODE` | `persistent` | `memory` per non salvare su disco |
| `CHROMA_EMBEDDING` | `default` | `ollama` per usare embedding Ollama |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | usato solo con `CHROMA_EMBEDDING=ollama` |
| `ACADEMIC_HUB_DATA_DIR` | `./data` | cartella di SQLite e ChromaDB (anche di UniSIS e UniLearn) |
| `UNISIS_URL` | `http://127.0.0.1:8100` | indirizzo di UniSIS visto dall'hub |
| `UNILEARN_URL` | `http://127.0.0.1:8200` | indirizzo di UniLearn (o di un Moodle vero) |

## Troubleshooting

- **`503 Impossibile contattare Ollama`** → avvia `ollama serve` (o `systemctl start ollama`) e verifica con `curl http://127.0.0.1:11434`.
- **`model "llama3.2" not found`** → `ollama pull llama3.2`.
- **Errori ChromaDB al primo `/api/sync`** → l'embedding di default (all-MiniLM-L6-v2, ~80 MB) viene
  scaricato una sola volta da Chroma; serve connessione solo in quel momento. Per una modalità
  totalmente offline: `ollama pull nomic-embed-text` e avvia con `CHROMA_EMBEDDING=ollama`
  (se cambi embedding, cancella prima `data/chroma`).
- **Ripartire da zero** → ferma il server e cancella la cartella `data/`.
- **`(trapped) error reading bcrypt version`** nei log → avviso innocuo di passlib; `bcrypt` è fissato a 4.0.1
  perché passlib 1.7.4 non funziona con bcrypt ≥ 4.1.
- **Il frontend dice "Backend non connesso"** → verifica che uvicorn sia su porta 8000. Se usi un'altra
  porta, dalla console del browser: `localStorage.setItem("rmb.apiBase","http://localhost:PORTA/api")`.
- **Prima risposta lenta** → al primo utilizzo Ollama carica il modello in memoria (5–20 s); le chiamate successive sono più rapide.

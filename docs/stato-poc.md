# Stato del PoC — Remind Me Bro (aggiornato 26 novembre 2026)

Regola: dopo ogni modifica (codice, rami, decisioni) questo documento va aggiornato subito, così la prossima sessione sa a che punto siamo. Le regole di lavoro sono in `CLAUDE.md`. Una copia di questo documento sta anche nel Project "SarasProject" su claude.ai (`claude/stato-poc.md`).

## Come si lavora
- Dal 26 novembre si lavora con **Claude Code** sul computer di Illia, nella cartella `~/saraProjects/RemindMeBro`: push diretto su GitHub, PR con `gh pr create` (o dal sito), app avviabile e log leggibili. Prima si lavorava da una macchina virtuale di Cowork (push via `git bundle` e cloud, nessun accesso all'app avviata): quel metodo non serve più.
- GitHub: https://github.com/kiperilyaas/RemindMeBro, ramo `main`. Ogni modifica va in un ramo nuovo, commit (messaggi in italiano), push e pull request senza conflitti che Illia unisce su GitHub. `.gitignore` tiene fuori `data/`, database, chiavi, `STAFF-PASSWORDS*.txt`, `.env`, `.runtime/`, `node_modules/`. `~/saraProjects/RemindMeBro1` è una copia vecchia, fuori da git.
- Zip per i collaboratori dopo ogni modifica: `scripts/make-zip.sh` → `~/saraProjects/RemindMeBro-demo-<data>.zip` (su un ramo diverso da `main` il nome finisce con il nome del ramo). Gli zip dal 25 novembre di `feature/smart-notes` … `feature/better-answers` sono in `RemindMeBro/.runtime/`.
- Log dell'app: `.runtime/logs/backend.log` (ora locale), `unilearn.log`, `unisis.log`, `whisper.log`. Database: `data/academic_hub.db`. Se le porte sono occupate il launcher sceglie la successiva (il 26 novembre l'hub era su 8001 e UniLearn su 8201).
- La cartella è una sola: cambiare ramo cambia anche l'app che Illia avvia (i file compilati `frontend/app/index.html`, `unilearn/static/staff/index.html`, `unisis/static/staff/index.html` sono nel repo). Dopo modifiche al backend l'app va riavviata (avvisare Illia prima).
- Illia usa un computer non molto potente: i lavori dell'AI (Ollama, Whisper) sono lenti.
- Conflitti tipici tra rami: i file compilati (si ricompilano da `web/` dopo l'unione, mai a mano) e la fine di `web/src/styles.css` (ogni ramo aggiunge blocchi in fondo: si tengono tutti).
- Prove: `npm test` e `npm run typecheck` in `web/`; per provare il backend senza toccare l'app vera, una copia su altre porte con `ACADEMIC_HUB_DATA_DIR` su una cartella di prova (utenti demo con `bootstrap_demo_data(db, seed_users=True)`). Per streaming e Stop dell'AI basta un Ollama finto in Python che manda NDJSON.

## Storia di `main`
- `ad8ffdf` (24 novembre): primo commit, tutto il lavoro fino a quel giorno.
- `9ff18db` (25 novembre): PR #1 `feature/login-intro` unita da Illia. Contiene:
  - intro video dopo il login: `frontend/brand/intro.mp4` (9:16, telefoni) e `intro-4x3.mp4` (4:3, schermi orizzontali), serviti da `/media/<nome>`; `web/src/components/LoginIntro.tsx`, flag `justSignedIn` in `state/session.tsx`. Parte solo dopo un login o una registrazione veri, sopra l'app che si carica. A 1,6 s, quando il campanello manda l'onda, si apre un cerchio dal campanello con un anello viola. Skip ed Esc; niente intro con "riduci movimento"; se il video non parte entro 1,5 s si va all'app.
  - dal link pubblico la pagina di login mostra Giulia Esposito per entrare con un tocco (docenti solo in locale).
  - barra in basso sul telefono: niente `viewport-fit=cover`, `lib/viewport.ts` con `--screen-bottom`. Da confermare da Illia su iPhone (Chrome e Safari).
  - `make-zip.sh` con il nome del ramo nello zip.
- `f1891e7` (25 novembre): PR #2 `feature/calendar` unita da Illia. Calendario della proposta A nella Timeline dello studente. `web/src/views/student/Calendar.tsx`: Agenda (oggi con linea dell'ora, poi 21 giorni, solo quelli con qualcosa), Week (frecce, settimana ISO, striscia di 7 giorni con pallini, tocco = scorre al giorno), Month (griglia 6 settimane, pallini lezione per corso / scadenza / esame, legenda, giorno scelto sotto). Tasto Today, filtro corsi, Plan my week, Mark as done in tutte le viste; vista scelta salvata nel browser; le scadenze in alto aprono il mese sul giorno. Eventi caricati dall'inizio del mese. Filtri e scadenze in alto mostrano il nome del corso.

## Stato delle PR (26 novembre, sera)
- Unite da Illia in `main`: #3 `feature/smart-notes`, #4 `feature/lesson-chat`, #5 `feature/notes-on-demand`, #6 `feature/inbox-new`, #7 `feature/better-answers`, #8 `feature/quick-login`, #9 `fix/db-locked` (`main` = `db81b84`).
- Aperte, una catena (ognuna nasce dalla precedente), da unire in quest'ordine:
  - #10 `fix/notes-timeout` (`c981d44`)
  - #11 `fix/inbox-course-names` (`54e13f2`)
  - #12 `feature/notes-stop` (`5b73702`)
  - #13 `chore/claude-code` (`1d6fb32`): `CLAUDE.md` e questo documento in `docs/`
  - `feature/outlook-teams` (nato da `chore/claude-code`): Inbox svuotata, corsi divisi tra i cinque docenti, messaggi da Outlook e Teams. PR da aprire dal sito (su questo computer `gh` non è installato).
- Tutte verso `main`. Una PR della catena mostra anche i commit delle precedenti finché quelle non sono unite.

## Inbox, docenti, Outlook e Teams (26 novembre, ramo `feature/outlook-teams`)
- Inbox svuotata su richiesta di Illia (dati, non codice): cancellati gli 11 avvisi dell'hub e gli 8 post rimasti nei forum Announcements di UniLearn, con le 9 scadenze che l'AI ci aveva trovato. Restano le 3 scadenze ufficiali (compiti UniLearn). Copia di prima in `.runtime/backup-before-clear-inbox-2026-11-26/`. L'indice di Ask Bro (ChromaDB) si ripulisce al prossimo avvio (`prune_vector_store`), perché l'app era accesa.
- Bug trovato: un post cancellato in UniLearn restava nell'Inbox (in UniLearn c'erano 8 post, nell'hub 11). Ora `unilearn_client.sync_posts` (Sync e controllo ogni 30 s) cancella dall'hub i post spariti dai forum letti, con le loro scadenze AI (`sync_service.delete_announcement`, che toglie anche il documento da ChromaDB e rimette visibile una data ufficiale nascosta da quel messaggio).
- Corsi divisi tra i cinque docenti (prima solo Neri e Rossi): Chiara Neri 2PR515 e 2IB468; Laura Bianchi 2MO522 e 2IB421; Marco Rossi 3SG712 e 3PA662; Giovanni Verdi 3MA674; Paolo Conti 3PO643. Cambiati `unilearn/seed.py`, `unisis/seed.py`, `app/mocks/moodle_mock.py`; per i dati già esistenti `move_demo_courses` (a ogni avvio dei tre servizi) sposta un corso solo se ha ancora il docente vecchio della demo: un docente scelto a mano resta.
- Messaggi da Outlook e Teams (richiesta di Illia). Un collegamento vero (Microsoft Graph) chiede un'app registrata in Azure e il consenso dell'amministratore dell'università: per la demo lo studente li aggiunge lui. Inbox → "Add message": Outlook o Teams, mittente, oggetto, corso (o "Let the AI guess"), testo incollato; per Outlook si può trascinare un'email salvata come `.eml` (Outlook: … → Download / Save as; il `.msg` del vecchio Outlook non si legge).
  - Backend: `app/services/personal_messages.py` (`parse_eml` con la libreria `email`, testo da HTML, data in ora locale; `add_message` → `process_informal_message` con `owner_id`). Endpoint `POST /api/inbox/messages`, `POST /api/inbox/parse-eml`, `DELETE /api/inbox/messages/{id}` (solo i propri).
  - Messaggi personali: colonna `announcements.user_id`; li vede solo chi li ha aggiunti (anche se il corso non è tra i suoi), e la scadenza trovata ha `user_id` dello studente. Un messaggio personale non sposta né nasconde le scadenze del corso degli altri; i docenti non lo vedono (né in "extracted deadlines" né nel conteggio avvisi); Ask Bro filtra in ChromaDB i messaggi di altri studenti (`owner_id` nei metadati).
  - Frontend: `views/student/AddMessage.tsx`, tasto "Add message" e "Delete" sui propri messaggi in `Inbox.tsx`; la fonte `email` ora si chiama "Outlook". CSS `.add-msg`, `.drop` in fondo a `styles.css`.
- Prove: API su una copia del database (aggiunta con e senza scadenza, fonte non ammessa 422, visibilità per un docente, cancellazione propria e altrui, `.eml` HTML con oggetto codificato, file non email 422); spostamento dei corsi su copie di UniLearn e UniSIS (4 spostati, la seconda volta 0); rimozione dei post cancellati con UniLearn acceso; 34 Vitest.
- Test su Node 26: Node 26 ha un suo `localStorage` che copre quello di jsdom e 6 test falliscono con `npm test`. Con `NODE_OPTIONS=--no-experimental-webstorage npm test` passano tutti. Da sistemare nella configurazione di Vitest (Illia ha detto "non ora").

## Smart Notes: Stop, Elimina, niente ripartenze da sole (26 novembre, ramo `feature/notes-stop`)
- Problema di Illia: una lezione (2PR515 "Lesson 1", un PDF di 11.567 caratteri, 2 parti) restava "AI processing" a lungo, ripartiva a ogni avvio dell'app e anche dopo aver tolto il PDF da UniLearn; nessun modo di fermarla. Cause: `main.py` rimetteva in coda all'avvio le lezioni a metà; `sync.py` non cancellava le lezioni in lavorazione; nessuno Stop. Nel F12 si vedevano `GET /api/notes` ogni 3 s (controllo stato mentre una lezione lavora) e Inbox/scadenze ogni 30 s: normale.
- `worker.py`: `stop(note_id)` (insieme `_stopping`), `_check` tra i passi, `should_stop` passato a `generate` (→ `_ask` → `chat_long`) e a `transcribe` (controlla tra due segmenti, `TranscribeStopped`). Fermata → stato "ready" se c'erano appunti (`generated_hash`), altrimenti "new".
- `llm_extractor.chat_long`: non usa più la libreria `ollama` ma `httpx` sull'API `/api/chat` in streaming; con `extensions={"trace": ...}` prende il socket appena connesso e un thread di controllo (ogni 0,5 s) fa `shutdown` del socket quando `should_stop()` è vero: si ferma anche mentre Ollama sta ancora leggendo il testo e non ha mandato nulla; Ollama vede il client andare via. Eccezione `LLMStopped`. (Chiudere il client httpx da un altro thread NON interrompe una lettura in corso: provato.)
- `sync.py`: `reset_interrupted(db)` all'avvio (al posto della rimessa in coda): lezioni a metà → "ready" o "new" con errore "Stopped when the app was closed. Press Make notes to start again."; una lezione tolta da UniLearn viene fermata (`worker.stop`) e cancellata anche se in lavorazione (le note modificate restano).
- Endpoint: `POST /api/notes/{id}/stop`, `DELETE /api/notes/{id}` (cascata su `note_sources` e `lesson_chat_messages`).
- Frontend `SmartNotes.tsx`: tasto Stop sulla scheda della lezione e nella pagina (accanto allo spinner), cestino nella barra della nota con `window.confirm`, lezione in lavorazione apribile, controllo stato ogni 5 s. `api/client.ts`: `stopNote`, `deleteNote`.
- Provato: Stop → lezione ferma in 0,2 s; riavvio → non in coda; stop/delete via API; streaming lento, Ollama muto e spento.

## Inbox: nome del corso (26 novembre, ramo `fix/inbox-course-names`)
- Richiesta di Illia: nell'Inbox i messaggi mostravano il codice del corso (es. `3SG712`), deve esserci il nome.
- `components/ui.tsx` → `CourseChip` con `showName`: mostra `name` in `.cchip-n` (tagliato con "…"), il codice va nel `title`. Usato in `views/student/Inbox.tsx`. Studies e Smart Notes restano col codice perché il nome è già scritto accanto. CSS `.cchip.named`, `.cchip-n` in fondo a `styles.css`. Test inbox aggiornato.

## Smart Notes: "timed out" sui file lunghi (26 novembre, ramo `fix/notes-timeout`)
- Errore visto da Illia: "The local AI is not running (Ollama at http://127.0.0.1:11434): timed out" mentre Ollama lavorava ancora. Causa: un solo client Ollama con limite di 120 s (`OLLAMA_TIMEOUT`), senza streaming: su un computer lento un file lungo supera i 120 s.
- `chat_long(messages, options, json_mode, should_stop)` in streaming: il limite (`NOTES_TIMEOUT`, `app/config.py`, predefinito 1800 s) conta dall'ultima parola ricevuta; collegamento 10 s. Errori distinti (`_raise_long`): Ollama spento ("not running"), nessuna parola per `NOTES_TIMEOUT` ("gave no answer for N minutes"), errore di Ollama. Usato da `notes/generator.py` (`_ask`) e `notes/lesson_chat.py`. Frontend: la domanda "Ask the material" aspetta fino a 30 min (prima 3).
- Restano a 120 s, senza streaming: Ask Bro (`/api/chat`, frontend 180 s) e l'estrazione delle scadenze dai messaggi (`_chat` in `llm_extractor.py`). Da allungare se anche lì compare "timed out".

## Sync: "database is locked" (26 novembre, ramo `fix/db-locked`)
- Errore visto da Illia premendo Sync: `OperationalError: database is locked` su `UPDATE connections SET last_sync_at`. Causa: `live_sync` (controllo avvisi UniLearn ogni 30 s, thread in sottofondo) tiene aperta una scrittura mentre l'AI legge i post; il Sync premuto aspettava solo 5 s (attesa predefinita di Python per SQLite).
- `app/services/sync_lock.py`: `SYNC_LOCK` (RLock). `@exclusive` su `sync_service.run_sync_pipeline`, `unilearn_client.sync_user`, `unisis_client.sync_user` (aspettano); `live_sync.poll_once` usa `try_exclusive()` e salta il giro se un sync è in corso.
- `app/database/db.py`: `timeout=30` e, alla connessione, `PRAGMA journal_mode=WAL`, `busy_timeout=30000`, `synchronous=NORMAL`. Con WAL accanto a `data/academic_hub.db` compaiono i file `-wal` e `-shm` (normali).
- Provato: seconda scrittura aspetta 7,5 s e riesce; poll saltato durante un sync; due Sync insieme rispondono 200.

## Accesso veloce per il debug (26 novembre, ramo `feature/quick-login`)
- Richiesta di Illia: sul computer che avvia il programma, pulsanti per entrare con un clic negli account di docenti e studenti in UniLearn e UniSIS.
- UniLearn `/login` e UniSIS `/login` (pagine Jinja `templates/login.html`): sotto il modulo "Quick sign-in · only on this computer" con tutti gli account (UniLearn: docenti, admin, studenti; UniSIS: Student Office, studenti), `POST /login/quick` (uid, csrf, next). In UniSIS funziona anche dentro il login dell'OAuth (il `next` resta). Stili `.login-stack`, `.quick-list`, `.quick-btn` in fondo a `unilearn.css` e `unisis.css`.
- Aree staff React: `/staff/api/demo-accounts` restituisce `local`; `POST /staff/api/quick-login` `{uid}` solo per docenti/admin (UniLearn) e Student Office (UniSIS). `web/src/staff/kit.tsx`: `StaffLogin` con `onQuick`, `useStaffSession().quickLogin`; i pulsanti degli account entrano subito quando `local`.
- Sicurezza: tutto passa da `app/api/access.py` (`is_local_request`, come nell'hub). Dal link pubblico niente elenco e richieste rifiutate. Provato con i servizi avviati: locale entra, `X-Forwarded-For` rifiutato, id di uno studente rifiutato nell'area staff.

## AI a pagamento: Ask Bro e Smart Notes (ramo `feature/smart-notes`)
- Richiesta di Illia (25 novembre): l'AI diventa a pagamento; Ask Bro e Smart Notes stanno insieme in una sezione "AI" e si aprono con Premium. Prezzo 79 CZK al mese; Giulia parte su Premium, con un interruttore in Account che cambia il piano.
- Piano: colonna `plan_choice` in `users` (vuota = mai scelto: Giulia Premium, gli altri Free), proprietà `user.plan` / `is_premium`, `plan` in `/api/auth/me`. `app/api/premium.py`: `GET /api/billing`, `POST /api/billing/plan` (pagamento simulato), dipendenza `require_premium` (402) su `/api/chat` e `/api/notes/*`. Docenti sempre ammessi.
- Prezzo: `app/config.py` → `PREMIUM_PRICE = "79"`, `PREMIUM_CURRENCY = "CZK"`, `PREMIUM_PERIOD = "month"` (anche come variabili d'ambiente). Il frontend lo legge da `/api/billing`.
- UniLearn: tabelle `course_sections` e `resources`, file in `data/unilearn/files/<hash>`; staff → corso → "Lessons and materials" (aggiungi lezione, carica PDF/PPTX/DOCX/TXT/MD, audio MP3/M4A/WAV/OGG/FLAC/AAC, video MP4/MOV/WEBM/MKV, cancella). Web service `core_course_get_contents` (standard Moodle) e download `/webservice/pluginfile.php/<id>/mod_resource/content/0/<file>?token=` solo per gli iscritti.
- Hub, `app/services/notes/`: `sync.py` (corsi seguiti → lezioni con file → una `LessonNote` per studente e lezione, `NoteSource` per file; note modificate dallo studente non sovrascritte, segnate "New material"), `worker.py` (un thread: download in `data/materials`, testo, trascrizione, appunti; stati waiting → syncing → transcribing → processing → ready/error; un file illeggibile viene saltato con avviso; Stop, vedi sopra), `extract.py` (pypdf, python-pptx con note del relatore, python-docx), `transcribe.py` (faster-whisper `base`, CPU int8, modello in `data/whisper`), `generator.py` (llama3.2 in JSON con `num_ctx` 8192; testi lunghi a pezzi da ~9000 caratteri, poi unione; Markdown con Summary, Key points, Definitions, Sources). Il testo estratto resta in `extracted_texts` per hash: lo stesso file si legge una volta sola per tutti. Dal ramo `feature/notes-stop` le lezioni rimaste a metà NON ripartono all'avvio. Anche il Sync generale e il Sync di UniLearn cercano nuovi materiali (solo Premium).
- Endpoint: `GET /api/notes`, `POST /api/notes/sync`, `GET/PUT /api/notes/{id}`, `POST /api/notes/{id}/regenerate`, `POST /api/notes/{id}/stop`, `DELETE /api/notes/{id}`.
- Ask Bro: il contesto RAG aggiunge fino a 2 note dello studente che contengono parole della domanda.
- Frontend: voce "AI" nella barra (anche sul telefono); il pannello laterale di Ask Bro non c'è più, il tasto viola apre la sezione AI. `views/student/AI.tsx` (schede Ask Bro / Smart Notes, rotte `#ai`, `#ai?tab=notes`, `#ai?tab=notes&note=<id>`), `components/Paywall.tsx` (piano, anteprima sfocata, checkout simulato), `views/student/SmartNotes.tsx` (corsi → lezioni con stato, apertura nota, Edit in Markdown, Copy text, Save as PDF con la stampa del browser, Make notes again, Stop, elimina), `lib/markdown.tsx`, Account → Plan con interruttore. Classe CSS della nota: `.snote` (`.note` esisteva già).
- Run & Go (`run.sh`, `run.ps1`, quindi tutti i launcher): `faster-whisper` da `requirements-whisper.txt` in un passo separato (se fallisce l'app parte lo stesso e salta audio e video), poi download del modello in sottofondo (`python -m app.services.notes.transcribe --download`, log `whisper.log`). FFmpeg non serve (PyAV lo contiene). pypdf, python-pptx, python-docx in `requirements.txt`. `make-zip.sh` include `requirements-whisper.txt`.
- Chat solo sul materiale (richiesta di Illia, 25 novembre, ramo `feature/lesson-chat`): nella pagina di una nota le schede Notes / Ask the material; "Ask about" sceglie tutta la lezione o un solo file. `POST /api/notes/{id}/chat` (`question`, `source_id` facoltativo, `history` per le domande che seguono), solo Premium. `app/services/notes/lesson_chat.py`: il testo estratto è diviso in pezzi da ~1100 caratteri con la posizione (Slide n, Page n, minuto della registrazione); ricerca per significato in ChromaDB (collezione `lesson_chunks`, indicizzata una volta per file, condivisa tra studenti) e per parole (senza parole comuni inglesi, italiane e ceche; radice di 6 lettere), unite con reciprocal rank fusion; fino a 8 pezzi / 6500 caratteri a llama3.2, che risponde solo con quelli e cita [1], [2]. Se ChromaDB non funziona basta la ricerca per parole. Le trascrizioni hanno l'ora ogni minuto circa (`[12:30]`); quelle già fatte prima non ce l'hanno. Frontend: `views/student/LessonChat.tsx`, fonti citate apribili sotto ogni risposta.
- Correzioni chieste da Illia (25 novembre, ramo `feature/notes-on-demand`):
  - Appunti solo su richiesta: la sync crea le lezioni con stato `new` ("Not made yet") e non mette nulla in coda; lettura, trascrizione e appunti partono solo con "Make notes" (sulla scheda o nella pagina; usa `POST /api/notes/{id}/regenerate`). File nuovi: gli appunti restano "ready" e mostrano "New material", nessun rifacimento automatico. La chat su una lezione `new` risponde "Press Make notes first".
  - Chat "Ask the material" salvata: tabella `lesson_chat_messages` (note_id, source_id vuoto = lezione intera, role, content, sources JSON). `GET/DELETE /api/notes/{id}/chat` (`?source_id=`), la `POST` salva domanda e risposta e prende le ultime 6 righe della stessa conversazione come storia. Pulsante "Delete this conversation".
  - Avvisi UniLearn: la causa nei dati di Illia era che il post "Kesson introduce" stava in 2PR515, corso a cui Giulia non è iscritta in UniLearn (segue 2IB468, 2MO522, 3SG712; Corporate Governance già superato con 3); in più arrivavano solo con Sync. Ora `app/services/live_sync.py` legge i forum Announcements di ogni studente collegato ogni 30 s (`UNILEARN_POLL_SECONDS`, 0 = spento; `unilearn_client.sync_posts`, anche l'AI per le scadenze), e il frontend (`state/student.tsx`) chiede Inbox e scadenze ogni 30 s mostrando un avviso per i messaggi nuovi. UniLearn staff avvisa se il corso non ha iscritti.
  - Inbox che segnala i messaggi arrivati (richiesta di Illia, ramo `feature/inbox-new`): `fresh` in `state/student.tsx` (id arrivati con l'app aperta, dal controllo ogni 30 s o da Sync) → etichetta New e bordo finché non si esce dall'Inbox; barra in alto "N new messages just arrived" / "N unread" con quanti non letti sono nascosti dal filtro e Show all; l'Inbox si apre su All se c'è un non letto non Important (gli avvisi senza scadenza non sono Important: prima finivano nascosti dal filtro predefinito); titolo della scheda "(N) Remind Me Bro"; avviso "New message in your Inbox".
- Risposte più precise nella chat sul materiale (26 novembre, ramo `feature/better-answers`). Con i file veri di Illia due risposte citavano male: il mid-term progress report (3.11.) è a pagina 4 di `Intro_SE_II_Winter26.pdf` ma la risposta diceva "Page 11" e citava pagina 5; l'esame finale (16.12, `IB-IM-674_Fall_2026.-X (6).pdf` pagina 1) citava [13], che non esisteva. Nota: nei PDF di slide il numero stampato in basso può essere diverso dalla pagina del PDF; l'app usa la pagina del PDF. Cambi in `lesson_chat.py`: prompt con regole (risposta diretta, fatto in grassetto come nel file, breve o elenco, solo [n], niente pagine o file), fonti in ordine di pertinenza (max 6, 5500 caratteri), `check_citations` (ogni frase alla fonte che contiene le sue date e numeri; citazione sbagliata spostata o tolta; numero che nessuna fonte ha → "(not found in the material)"; pagine e nomi di file del modello tolti), ricerca per parole con coppie vicine e date più in alto per le domande "quando", storia senza i vecchi [n], `snippet` con la frase che contiene il fatto. Frontend: chip con la pagina ("p. 4", "slide 3", "12:30"), fonti raggruppate per file, la nota "Answers use only..." è un'icona (i) accanto al menu e un suggerimento solo a conversazione vuota.
- Prove: 32 Vitest su `feature/better-answers`; prova API completa (caricamento, sync, stati, note, modifica, file nuovo, rigenera, 402 per Free, note di Giulia non leggibili da altri, download senza token 403) con LLM e Whisper finti; screenshot desktop e telefono controllati.

## Tre servizi, un solo avvio (Run & Go)
| Servizio | Porta | Ruolo | Collegamento dall'hub |
|---|---|---|---|
| Remind Me Bro (hub FastAPI + UI React) | 8000 | studente e docente, estrazione scadenze con Ollama llama3.2, chat RAG con ChromaDB, Smart Notes | — |
| UniSIS (`unisis/`) | 8100 | segreteria tipo InSIS/Esse3, area staff React su `/staff` | OAuth 2.0 + PKCE |
| UniLearn (`unilearn/`) | 8200 | LMS che parla le API web service di Moodle, area staff React su `/staff` | token Moodle |

- Avvio: `run-mac.command` / `run-windows.bat` / `run-linux.sh` (`scripts/run.sh`, `scripts/run.ps1`). Se la cartella è stata spostata o copiata, l'ambiente Python viene rifatto e i pacchetti reinstallati (correzione del 21 novembre).
- Link pubblico: `run-share-*` = stesso avvio + ngrok sulla porta dell'hub + QR code (`scripts/share.py`, pagina `.runtime/share/qr.html`). Token ngrok chiesto una volta. Dal link si raggiunge solo l'hub.

## Calendario: proposte sul canvas
- Canvas: https://claude.ai/artifact/EwCGrMWTUjPReSqegBhsDk (A Agenda, B griglia settimanale, C mese + giorno). Illia ha scelto la A; ora è in `main` (PR #2).

## Marchio
- Loghi Remind Me Bro (22 novembre/24 novembre): `web/src/assets/brand/` (logo per sfondo chiaro, logo per sfondo scuro, icona 192 e 64), componente `web/src/components/Brand.tsx`. Login: logo per sfondo scuro; barra in alto: logo secondo il tema, solo icona sul telefono; favicon e schermata di caricamento: icona; area docenti: icona; pagina QR: `frontend/brand/logo-light-bg.png`; consenso UniSIS: `unisis/static/remindmebro-icon.png`.

## Demo pubblica sicura (24 novembre)
- Area docenti solo da questo computer: login, registrazione e token da docente funzionano solo per richieste dirette a 127.0.0.1/localhost senza intestazioni di proxy (ngrok aggiunge sempre X-Forwarded-For e l'host pubblico). Codice: `app/api/access.py`, controllo in `get_current_user` e `_authenticate`. Anche `/classic` solo in locale. Lo stesso controllo vale per l'accesso veloce di UniLearn e UniSIS (ramo `feature/quick-login`).
- Password staff: al primo avvio docenti hub, admin e docenti UniLearn, segreteria UniSIS ricevono password casuali al posto di `demo1234`. File per servizio (`data/STAFF-PASSWORDS-hub.txt`, `data/unilearn/STAFF-PASSWORDS.txt`, `data/unisis/STAFF-PASSWORDS.txt`), riuniti da run.sh/run.ps1 in `data/STAFF-PASSWORDS.txt`. Nessuna pagina mostra password di staff.
- Registrazione studenti: "Create account" nell'hub (solo studente dal link pubblico). L'hub crea anche l'account UniSIS (`POST /api/v1/provisioning/students`, autenticato con client ID e secret dell'hub; registra il consenso e restituisce i token OAuth) e UniLearn (`POST /admin/tool/provision/student`, chiave in `data/unilearn/provisioning.key`), stessa email e password, già collegati (`app/services/provisioning.py`). I nuovi studenti partono sul piano Free.
- Dati separati tra studenti: spunta "fatto" per studente (tabella `deadline_done`), consegne UniLearn spuntate solo per chi ha consegnato, la sync di UniLearn cancella compiti ed eventi solo nei corsi di chi sincronizza, note di Smart Notes per studente. Il database dell'hub aggiunge tabelle e colonne nuove senza ricrearsi (utenti e collegamenti restano).
- Giulia (`student@demo.it / demo1234`) è voluta anche dal link pubblico, per entrare veloce. Resta: uno studente che preme "Disconnect UniSIS" dal telefono non può ricollegarsi (il consenso UniSIS è solo locale).

## Dati di partenza
- Account: studentessa demo `student@demo.it` / `demo1234` (UniLearn e UniSIS: `giulia.esposito`); staff con password in `data/STAFF-PASSWORDS.txt`; UniSIS ha il corso di laurea BSc Economics and Finance e i due semestri dell'anno accademico in corso (calcolati dalla data di oggi).
- Otto corsi della demo (codici VŠE), 6 ECTS, semestre in corso, a scelta, senza lezioni, compiti o esami:
  - Chiara Neri: 2PR515 Corporate Governance (SB 408, creato da Illia), 2IB468 Ethics in Finance (SB 410).
  - Laura Bianchi: 2MO522 Financial Strategies in International Business (SB 411), 2IB421 Global ESG and Implications for Sustainable Business (SB 412).
  - Marco Rossi: 3SG712 Growth strategies (SB 413), 3PA662 Human Resource Management Seminar (SB 414).
  - Giovanni Verdi: 3MA674 International Management (SB 415).
  - Paolo Conti: 3PO643 Social Entrepreneurship: Innovation and Impact (SB 416).
  - Fino al 26 novembre tutti e otto erano di Neri e Rossi (ramo `feature/outlook-teams`).
  - Elenco in `unilearn/seed.py`, `unisis/seed.py`, `app/mocks/moodle_mock.py` (`seed_courses` aggiunge solo i corsi mancanti).
- Orologio: `DEMO_REFERENCE_DATE=now` di default nei tre servizi e nel frontend. I dati di UniSIS usano l'ora locale del computer che fa girare l'app.
- I dati restano in `data/`. Per ripartire: cancellare `data/` (si ricreano account, password staff e otto corsi). Colonne nuove nei modelli vengono aggiunte alle tabelle esistenti all'avvio (`_add_missing_columns`).
- Dal ramo `fix/db-locked` il database dell'hub è in modalità WAL.

## Scelta dei corsi
- Gli 8 corsi sono a scelta (UniSIS `kind="elective"`), nessuno studente iscritto. La finestra di iscrizione del semestre si apre al primo avvio per 30 giorni; la segreteria la apre/chiude in UniSIS /staff → Exams → Course registration.
- Lo studente sceglie in Remind Me Bro → Studies → Course registration (o nel portale UniSIS). UniSIS decide; UniLearn segue con i web service `enrol_self_enrol_user` (standard Moodle) e `local_unilearn_self_unenrol` (nostro) in `unilearn/ws.py`, insieme a `core_course_get_courses_by_field`. Avviene dopo ogni Enrol/Drop dall'hub, a ogni Sync e quando si collega UniLearn.
- Nell'hub lo studente vede scadenze, eventi, avvisi, note di Smart Notes (e contesto dell'assistente AI) solo dei corsi che segue: codici nello snapshot delle connessioni (`course_codes`), filtro in `app/services/my_courses.py`. I docenti vedono tutto.

## Strumenti staff
- UniLearn `/staff` → New course (codice + nome + aula), lezioni e materiali (file per Smart Notes), iscritti, compiti, avvisi, eventi di calendario, modifica, cancella corso. UniSIS `/staff` → Courses → New course (aula principale, orario settimanale con aula per lezione, a scelta/obbligatorio), pagina corso con modifica, cambio aula della singola lezione, iscritti; Exams → New exam date. Hub → area docente → New course.
- Aula: in UniLearn gli eventi senza aula prendono quella del corso; in UniSIS una lezione senza aula usa l'aula principale; cambiando l'aula, eventi/lezioni nell'aula vecchia la seguono.
- Stesso codice = stesso corso tra i tre sistemi; un docente dell'hub può "prendere" un corso arrivato da UniLearn/UniSIS scrivendo lo stesso codice.
- "Try a case" solo nell'area docente dell'hub, con date relative a oggi.
- Sul computer che avvia la demo: accesso con un clic a ogni account di UniLearn e UniSIS (ramo `feature/quick-login`).

## Voti: scala ceca (la demo si presenta in Repubblica Ceca)
- 1 excellent (il massimo), 2 very good, 3 good, 4 satisfactory (ultimo voto sufficiente), 5 fail; "pass" per le attività senza voto.
- Media pesata sui crediti dei soli esami superati (1–4): più bassa è migliore. Il 5 non dà crediti e non entra nella media.
- UniSIS: voto scelto da un elenco. Portale studente e hub (Studies) mostrano voto e nome; l'assistente AI riceve la spiegazione della scala.

## Decisioni
- UniLearn al posto di un Moodle in Docker; il client funziona anche con un Moodle vero (`UNILEARN_URL`), anche per Smart Notes.
- La data ufficiale cambiata in UniLearn vince su una data trovata dall'AI in un messaggio più vecchio.
- Senza riferimenti temporali nel testo l'AI non crea scadenze.
- Ask Bro e Smart Notes sono Premium (79 CZK al mese, pagamento simulato nel prototipo). Trascrizione e appunti girano sul computer (faster-whisper + llama3.2).
- Studenti: vedono i messaggi solo dei corsi che seguono; gli avvisi arrivano da soli entro ~30 s.
- Smart Notes non elabora nulla senza il clic su Make notes, non riparte da sola dopo un riavvio, e si può fermare (Stop) o eliminare.
- Un sync alla volta (`SYNC_LOCK`): il Sync premuto aspetta il controllo automatico, che salta il giro se un Sync è in corso.
- I lavori lunghi dell'AI (appunti, Ask the material) non hanno un limite di tempo totale: si fermano solo se Ollama tace per `NOTES_TIMEOUT` (30 min) o con Stop.
- Allo studente si mostra il nome del corso, non il codice (calendario, Inbox).
- Outlook e Teams: niente collegamento Microsoft Graph nella demo; lo studente aggiunge i messaggi (testo o `.eml`), che restano personali.
- Un avviso cancellato in UniLearn sparisce anche dall'Inbox, con le scadenze trovate dall'AI.
- Dal 26 novembre il codice si fa con Claude Code (regole in `CLAUDE.md`); il design (canvas) resta su claude.ai.
- Test: 26 Vitest su `main`, 30 su `feature/smart-notes`, 31 su `feature/lesson-chat` e `feature/notes-on-demand`, 32 su `feature/inbox-new` e `feature/better-answers`, 33 da `feature/quick-login` in poi, 34 su `feature/outlook-teams` (con Node 26: `NODE_OPTIONS=--no-experimental-webstorage`); prove complete via API sui tre servizi.

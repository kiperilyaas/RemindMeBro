# Remind Me Bro — istruzioni per Claude Code

Progetto di Illia (con Sara): PoC "Academic Unified Hub & AI Assistant", frontend "Remind Me Bro". Demo da presentare in Repubblica Ceca (corsi VŠE). Quattro servizi locali: hub (FastAPI + React, porta 8000), UniSIS (8100, segreteria tipo InSIS), UniLearn (8200, LMS compatibile con Moodle) e UniComms (8300, posta tipo Outlook e Teams dei docenti).

## Prima di tutto
- Leggi `docs/stato-poc.md`: dice a che punto siamo, quali rami e PR sono aperti, cosa è stato deciso e perché.
- Rispondi sempre in italiano, in modo diretto. Testi semplici, senza frasi da chatbot né parole gonfiate.

## Regole di lavoro
1. **Un ramo nuovo per ogni modifica**, prima di toccare il codice (`feature/...` per le novità, `fix/...` per le correzioni). Mai lavorare direttamente su `main`.
2. **Alla fine**: commit (messaggio in italiano: titolo breve, poi cosa e perché), `git push -u origin <ramo>`, **pull request verso `main` senza conflitti**. Se GitHub segnala conflitti, unisci `main` nel ramo e risolvili prima di consegnare.
3. **Dopo ogni modifica al codice** fai lo zip per i collaboratori: `scripts/make-zip.sh` → `~/saraProjects/RemindMeBro-demo-<data>[-<ramo>].zip`.
4. **Aggiorna `docs/stato-poc.md`** subito dopo ogni modifica (rami, PR, decisioni, cause dei bug trovati) e committalo nello stesso ramo.
5. Allo studente si mostra il **nome del corso**, non il codice (il codice al massimo nel suggerimento).
6. Non mettere nei commit modifiche locali di Illia che non ha chiesto (per esempio il modello in `scripts/run.sh`).
7. Prima di riavviare l'app di Illia avvisalo: interrompe quello che sta facendo (per esempio appunti di Smart Notes in corso).

## Comandi
- Avvio completo (quattro servizi + AI): `./scripts/run-linux.sh` (Mac `scripts/run-mac.command`, Windows `scripts/run-windows.bat`); con link pubblico ngrok + QR: `run-share-*`. Nella cartella principale restano solo i tre `run-share-*`, `README.md`, `CLAUDE.md` e `.gitignore`: librerie Python ed esempio dell'AI in `config/`, guida per chi prova la demo in `docs/START-HERE.txt`.
- Documentazione: `README.md` (vetrina per GitHub, corta), `docs/architettura.md`, `docs/sviluppo.md` (avvio, test, configurazione, API), `docs/stato-poc.md`.
- AI: `data/ai.env` (fuori da git, contiene la chiave: non mostrarla mai) sceglie l'AI esterna (Gemini di default, o qualsiasi API compatibile con OpenAI); senza chiave si usa Ollama. Controllo: `.runtime/venv/bin/python -m app.services.ai_remote`.
- Log: `.runtime/logs/backend.log`, `unilearn.log`, `unisis.log`, `unicomms.log`, `whisper.log`.
- Frontend (`web/`): `npm test` (Vitest), `npm run typecheck`, `npm run build` (compila hub → `frontend/app/index.html`, UniLearn → `unilearn/static/staff/index.html`, UniSIS → `unisis/static/staff/index.html`, UniComms → `unicomms/static/staff/index.html`). I quattro file compilati sono nel repo: **ricompilali dopo ogni modifica a `web/` e committali**.
- Test Python (senza AI né rete): `.runtime/venv/bin/python -m unittest discover -s tests`. Con Node 26: `NODE_OPTIONS=--no-experimental-webstorage npm test`.
- Python: ambiente in `.runtime/venv` (creato dal launcher). Esempio: `.runtime/venv/bin/python -m uvicorn app.main:app --port 18000` per una copia di prova accanto all'app vera.
- Dati locali in `data/` (fuori da git): database SQLite in modalità WAL, password staff in `data/STAFF-PASSWORDS.txt` (non mostrarle mai), file dei corsi, modello Whisper.

## Conflitti tipici tra rami
- `frontend/app/index.html` e gli altri file compilati: non si sistemano a mano, si ricompilano da `web/` dopo l'unione.
- La fine di `web/src/styles.css`: ogni ramo aggiunge blocchi in fondo, si tengono tutti.

## Sicurezza della demo pubblica
- L'area docenti, l'accesso veloce di UniLearn/UniSIS, tutto UniComms e la lista degli account funzionano solo sul computer che avvia la demo (`app/api/access.py`, `is_local_request`). Dal link pubblico (ngrok) arriva solo l'hub.
- Giulia Esposito (`student@demo.it` / `demo1234`) è voluta anche dal link pubblico, per entrare veloce.

## Dati simulati
- L'hub è la demo pronta per gli utenti: niente pulsanti per "inventare" dati nell'hub dello studente. Tutto quello che arriva (avvisi, email, Teams, compiti, orari) si simula dai servizi: UniLearn, UniSIS, UniComms.

## Design
Le proposte grafiche (canvas) si fanno su claude.ai, nel Project "SarasProject". Qui si lavora sul codice.

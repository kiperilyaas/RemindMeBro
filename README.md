<div align="center">

# Remind Me Bro

**All of uni in one timeline.**

Lezioni, scadenze, esami e messaggi dei docenti in un'unica app per lo studente.<br>
Un'AI trova le date nascoste nei messaggi e nei file dei corsi, e non ne inventa.

Prototipo (PoC) per i corsi della VŠE di Praga · Python · FastAPI · React · Gemini o Ollama

</div>

---

## Cosa fa

- 📅 **Timeline**: calendario unico (Agenda, Week, Month) con lezioni, scadenze ed esami di tutti i sistemi dell'università. *Plan my week* propone i blocchi di studio.
- 🔎 **Find exams** *(gratis)*: legge syllabus e slide dei corsi e trova esami, midterm, test, presentazioni e consegne. Ogni data mostra la frase del file e la pagina, e va nel calendario solo se lo studente la conferma. Meglio nessuna data che una sbagliata.
- 📥 **Inbox**: avvisi di UniLearn, email (Outlook) e post Teams dei docenti in un posto solo. L'AI segnala le scadenze scritte nel testo; i messaggi arrivano da soli entro mezzo minuto.
- 🎓 **Studies**: iscrizione ai corsi e agli appelli, voti con la scala ceca (1–4, 5 = fail), crediti.
- ✨ **AI** *(Premium)*: **Ask Bro**, una chat sulle proprie scadenze e lezioni; **Smart Notes**, appunti dalle slide e dalle registrazioni e una chat che risponde solo con il materiale del corso, citando le pagine.

## Prova la demo

Serve solo un doppio clic: il launcher installa tutto da solo dentro la cartella (Python, librerie, AI locale se serve) e apre il browser.

| Sistema | Con link pubblico e QR code *(consigliato per farla provare)* | Solo su questo computer |
|---|---|---|
| macOS | `run-share-mac.command` | `scripts/run-mac.command` |
| Windows | `run-share-windows.bat` | `scripts/run-windows.bat` |
| Linux | `./run-share-linux.sh` | `./scripts/run-linux.sh` |

- La prima volta chiede la **chiave di Google Gemini** (gratuita: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)). Premendo Invio senza chiave l'AI gira sul computer con Ollama: più lenta, ma nulla esce dal computer.
- Il link pubblico usa ngrok: la prima volta chiede il token gratuito di ngrok.
- Studentessa demo: **Giulia Esposito** · `student@demo.it` / `demo1234` (anche dal link pubblico). Le password dello staff sono in `data/STAFF-PASSWORDS.txt`, solo sul computer che avvia la demo.
- Guida passo passo per chi prova la demo (italiano e inglese): [`docs/START-HERE.txt`](docs/START-HERE.txt).

## Quattro servizi, un solo avvio

Remind Me Bro non inventa i dati: li legge da tre sistemi universitari simulati, avviati insieme a lui. Ognuno ha la sua area staff, raggiungibile solo dal computer che avvia la demo.

| Servizio | Porta | Ruolo | Come lo legge l'hub |
|---|---|---|---|
| **Remind Me Bro** | 8000 | l'app dello studente (e l'area docente) | — |
| **UniSIS** | 8100 | segreteria tipo InSIS: orario, appelli, iscrizioni, voti | OAuth 2.0 + PKCE |
| **UniLearn** | 8200 | LMS compatibile con Moodle: compiti, file dei corsi, avvisi | API web service di Moodle |
| **UniComms** | 8300 | posta (tipo Outlook) e Teams: i docenti scrivono a un corso o a uno studente | API con chiave |

Per mostrare la demo: si carica il syllabus in **UniLearn** → `/staff` → corso → *Lessons and materials*, si manda un messaggio da **UniComms** → `/staff`, si cambia un appello in **UniSIS** → `/staff`. Poi, come Giulia, si vede tutto arrivare nell'app.

## AI

L'AI si sceglie in `data/ai.env` (fuori da git; esempio commentato in [`config/ai.env.example`](config/ai.env.example)):

- **Gemini** (predefinito con la chiave): `gemini-3.8-flash`, con modelli di riserva se Google è sovraccarico;
- qualsiasi servizio **compatibile con OpenAI** (OpenRouter, OmniRoute, OpenAI, un indirizzo personalizzato);
- **Ollama + llama3.2** sul computer, anche come riserva quando manca internet.

Controllo veloce dell'AI configurata: `.runtime/venv/bin/python -m app.services.ai_remote`

## Struttura

```
RemindMeBro/
├── run-share-*            launcher con link pubblico (Mac, Windows, Linux)
├── app/                   hub: API FastAPI, AI, sincronizzazione (porta 8000)
├── web/                   sorgenti React + TypeScript dell'hub e delle aree staff
├── frontend/              interfaccia compilata (servita dall'hub)
├── unisis/                UniSIS, segreteria (porta 8100)
├── unilearn/              UniLearn, LMS compatibile con Moodle (porta 8200)
├── unicomms/              UniComms, posta e Teams dei docenti (porta 8300)
├── scripts/               launcher solo locali, Run & Go, zip per i collaboratori
├── config/                librerie Python da installare, esempio di configurazione dell'AI
├── tests/                 test Python (date d'esame)
├── docs/                  guida per chi prova la demo, architettura, sviluppo, stato del progetto
└── data/                  creata all'avvio: database, file, chiavi (mai in git)
```

## Documentazione

- [`docs/architettura.md`](docs/architettura.md): come sono fatti e collegati i servizi, le scelte tecniche
- [`docs/sviluppo.md`](docs/sviluppo.md): avvio a mano, test, build, configurazione, API, problemi comuni
- [`docs/stato-poc.md`](docs/stato-poc.md): a che punto siamo, decisioni, storia delle modifiche
- [`web/README.md`](web/README.md) · [`unisis/README.md`](unisis/README.md) · [`unilearn/README.md`](unilearn/README.md): dettagli di interfaccia, UniSIS e UniLearn

---

<sub>Prototipo per una presentazione all'università (VŠE, Praga) · tutti i dati della demo sono inventati.</sub>

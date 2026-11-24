# Remind Me Bro · web UI (React)

React 18 + TypeScript (strict) + Vite. One project, **three single-file builds**, all committed prebuilt
(the Run & Go launcher never needs Node.js):

| Build | Entry | Output | Served at |
|---|---|---|---|
| hub (students + lecturers) | `index.html` | `../frontend/app/index.html` | hub `/` (old UI: `/classic`) |
| UniLearn teaching area | `apps/unilearn/index.html` | `../unilearn/static/staff/index.html` | UniLearn `/staff` |
| UniSIS Student Office | `apps/unisis/index.html` | `../unisis/static/staff/index.html` | UniSIS `/staff` |

The three staff areas (hub lecturers, UniLearn teachers/admin, UniSIS registrar) share one minimal design
system: `src/staff/staff.css` + `src/staff/kit.tsx` (shell, login, tables, toasts, **Try a case** cards).

```bash
cd web
npm install
npm run dev        # http://localhost:5173, /api proxied to the backend on :8000
npm test           # Vitest + Testing Library (domain rules, API client, Ask Bro)
npm run build      # type-check + the three builds (vite build --mode hub | unilearn | unisis)
```

## Structure

| Path | What |
|---|---|
| `src/api/` | typed API client (`client.ts`) and types mirroring `app/api/schemas.py` |
| `src/state/` | `session` (auth, demo clock, offline), `student` / `lecturer` data, toasts |
| `src/lib/` | pure helpers: dates (DST-safe), domain rules (`planWeek`, urgency, colours), hash router, safe storage |
| `src/components/` | `Shell` (top tabs / bottom nav), `Assistant` (Ask Bro), UI primitives, icons |
| `src/views/student/` | Timeline, Inbox, Studies (UniSIS), Semester map, Connections |
| `src/views/lecturer/LecturerArea.tsx` | hub lecturer area (courses, announce, dates found by AI, try a case) |
| `src/staff/` | shared staff kit + `unilearn/` and `unisis/` staff apps (JSON APIs in `unilearn/staff.py`, `unisis/staff.py`) |

## UX principles used

- **One timeline per day** as the home: classes, deadlines, exams and planned study blocks in time order.
- **Progressive disclosure**: messages expand in place, raw AI JSON hidden behind a disclosure.
- **Explain the AI**: every AI date shows "found by AI", the original message and what it replaced.
- **Mobile first**: bottom navigation and Ask Bro as a bottom sheet under 900 px; docked assistant on wide screens.
- **Accessibility**: semantic landmarks, skip link, `aria-current`/`aria-pressed`/`aria-expanded`, focus moved to the page on navigation,
  visible focus rings, 40 px+ touch targets, `prefers-color-scheme` dark theme and `prefers-reduced-motion`.
- **Resilience**: error boundary (with a link to `/classic`), offline banner with automatic retry, optimistic "done" with rollback.

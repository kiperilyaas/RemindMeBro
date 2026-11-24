# UniSIS — Student Information System (demo)

UniSIS is our own, self-hosted **student information system** (the "InSIS / Esse3" of the demo
university). It is a separate service with its own database, its own web portal and a real,
key-protected API. Remind Me Bro connects to it exactly like it would connect to a university's
real SIS: an **OAuth 2.0 client registration** (client ID + secret), **API keys** and a
**student consent screen**.

```
 Student's browser                                   UniSIS (port 8100)
 ┌──────────────────┐ 1. Connect UniSIS              ┌──────────────────────────────┐
 │ Remind Me Bro    │──────────────────────────────▶ │ /oauth/authorize             │
 │ (hub, port 8000) │                                │  login + consent screen      │
 │                  │ ◀────────────── 2. ?code=…     │                              │
 │                  │                                │                              │
 │ hub backend ─────┼── 3. POST /oauth/token ──────▶ │ client_id + client_secret    │
 │                  │      (code + PKCE verifier)    │  + PKCE → access/refresh     │
 │                  │                                │                              │
 │                  │── 4. GET /api/v1/me/… ───────▶ │ Bearer token, scopes checked │
 │                  │── 5. POST …/registration ────▶ │ business rules enforced      │
 └──────────────────┘                                └──────────────────────────────┘
```

## What it manages

| Area | Details |
|---|---|
| Programme & credits | BSc in Economics and Finance (180 ECTS), credits earned, weighted average |
| Course catalogue | Core courses of the current term + electives of the next term, ECTS, lecturer, capacity |
| **Course registration** | Registration window per term (opens/closes), capacity, **waiting list** with automatic promotion when someone drops |
| Timetable | Weekly slots (lecture / tutorial / lab, room) expanded to concrete dates for the student's courses |
| **Exam registration** | Exam terms (finals and partial tests) with registration window, capacity, register / cancel |
| Grades & transcript | Czech scale 1–5 (1 excellent, 2 very good, 3 good, 4 satisfactory, 5 fail), pass/fail activities, weighted average (lower is better) |
| Apps & keys | Registered OAuth clients, client secret (shown once), API key, issued tokens, **API audit log** |

## Users (demo, password `demo1234`)

| Role | Login | What they can do |
|---|---|---|
| Student | `giulia.esposito` | Self-service portal: timetable, exams, course registration, transcript, connected apps |
| Registrar (Student Office) | `registrar` | Create/open/close exam terms and registration windows, enter grades, manage apps & keys |

60 more students are generated so that capacities, seats left and waiting lists are realistic.

## Data model

```
Programme 1─* User(student) *─* Course (via Enrollment: enrolled | waitlisted | completed)
Term 1─* Course 1─* TimetableSlot
Course 1─* ExamTerm 1─* ExamRegistration *─1 User
User 1─* GradeRecord *─1 Course
OAuthClient 1─* AuthorizationCode / Token (access | refresh) *─1 User
OAuthClient 1─* Consent *─1 User
AuditLog (every API / token call: client, user, method, path, status)
```

## Security model

* **Client registration**: Remind Me Bro is a confidential OAuth client (`remind-me-bro`).
  The secret and the API key are stored **hashed** (SHA-256). The plaintext is shown once and
  exported to `data/unisis/clients/remind-me-bro.json`, the file the hub reads (like downloading
  credentials from a developer portal).
* **Authorization Code + PKCE (S256)** for student data. Codes are single-use and expire in 5 minutes.
* Opaque random tokens, stored hashed: access token 1 hour, refresh token 30 days (rotated on use).
* **Scopes** (shown on the consent screen):

| Scope | Meaning |
|---|---|
| `profile` | Name, student number, programme, credits, average |
| `timetable` | Personal timetable |
| `enrollments` | Courses and course registration status |
| `enrollments:write` | Enroll in / drop courses during the registration window |
| `exams` | Exam terms and registration status |
| `exams:write` | Register for / cancel exam registrations |
| `grades` | Transcript |

* **Redirect URIs** are matched exactly, except for loopback hosts (`127.0.0.1`, `localhost`) where any
  port is accepted (RFC 8252), so the Run & Go scripts can choose a free port.
* Students can **revoke** an app from their portal; the registrar can revoke single tokens.
* Web portal: server-side sessions (signed cookie) and CSRF tokens on every form.

## REST API (v1)

Machine-readable docs: `http://127.0.0.1:8100/docs`. Discovery: `/.well-known/oauth-authorization-server`.

| Method | Path | Auth |
|---|---|---|
| GET | `/oauth/authorize` | browser (login + consent) |
| POST | `/oauth/token` | client credentials (`authorization_code`, `refresh_token`) |
| POST | `/oauth/revoke` | client credentials |
| GET | `/api/v1/catalogue/courses` | `X-API-Key` |
| GET | `/api/v1/me` | `profile` |
| GET | `/api/v1/me/timetable?from=&to=` | `timetable` |
| GET | `/api/v1/me/enrollments` | `enrollments` |
| GET | `/api/v1/me/course-registration` | `enrollments` |
| POST / DELETE | `/api/v1/me/course-registration/{course_code}` | `enrollments:write` |
| GET | `/api/v1/me/exams` | `exams` |
| POST / DELETE | `/api/v1/me/exams/{exam_id}/registration` | `exams:write` |
| GET | `/api/v1/me/grades` | `grades` |

## Business rules

* **Course registration**: only during the term's window; if the course is full the student joins
  the waiting list; dropping a course promotes the first waitlisted student.
* **Exam registration**: the student must be enrolled in the course and must not have passed it yet;
  only during the window; never above capacity; only one final exam term per course at a time;
  cancellation allowed until the window closes.
* **Grades**: entered by the registrar for final exams; a passing grade (1–4; 5 is a fail) closes the
  enrollment as *completed* and adds the credits.
* **Clock**: like the hub, UniSIS uses `DEMO_REFERENCE_DATE` (default `now`, the computer's clock)
  for windows and timetables. The registrar can open/close any window "now" during the presentation.
* **Starting data**: only the BSc programme, the two terms of the current academic year (computed from
  today) and the accounts `registrar` and `giulia.esposito`. The registrar creates courses (with weekly
  timetable), enrols students and creates exam dates in `/staff`.

## Run it

```bash
uvicorn unisis.main:app --port 8100        # from the project root
```
Portal: http://127.0.0.1:8100 · API docs: http://127.0.0.1:8100/docs.
The Run & Go scripts start UniSIS automatically next to the hub.

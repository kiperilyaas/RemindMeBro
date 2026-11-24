# UniLearn — Moodle-compatible LMS (design note)

UniLearn is the learning platform of the demo university. It is a separate FastAPI service
(port 8200, database `data/unilearn/unilearn.db`) that speaks a **real subset of the Moodle
web-service protocol**, so any Moodle client (including Remind Me Bro's `unilearn_client.py`)
works against it unchanged — and the same client works against a real Moodle site.

## Protocol

| Moodle endpoint | Behaviour |
|---|---|
| `POST /login/token.php` | `username`, `password`, `service=moodle_mobile_app` → `{"token": "<32 hex>", "privatetoken": null}`; errors `invalidlogin`, `servicenotavailable` |
| `POST /webservice/rest/server.php` | `wstoken`, `wsfunction`, `moodlewsrestformat=json` + parameters; array syntax `courseids[0]=1`; errors returned with HTTP 200 as `{"exception","errorcode","message"}` |

Functions: `core_webservice_get_site_info`, `core_enrol_get_users_courses`, `mod_assign_get_assignments`,
`mod_assign_get_submission_status`, `core_calendar_get_calendar_events`, `mod_forum_get_forums_by_courses`,
`mod_forum_get_forum_discussions`. Timestamps are Unix seconds, rich text is HTML, as in Moodle.

## Security

- Passwords: bcrypt. Tokens: only the SHA-256 hash is stored, plus the last 4 characters for display.
- Each token records the client name (`X-Client-Name` header or user agent) and last access.
- Students see and delete their tokens under **Security keys**; the admin sees all tokens and a
  live **function call log** under **Web services**.
- Web portal: session cookie (itsdangerous), CSRF token on every form.

## Web portal

| Role | Can do |
|---|---|
| Student (`giulia.esposito`) | dashboard + timeline, course pages, submit / remove a submission, security keys |
| Teacher (`chiara.neri`, `marco.rossi`, …) | post to the Announcements forum, add assignments, change due dates |
| Admin (`admin`) | everything above for every course, Web services page |

All demo passwords are `demo1234`. The clock (`DEMO_REFERENCE_DATE`, default `now`) is shared with the
hub and UniSIS. UniLearn starts with no courses: teachers (or the admin, for any teacher) create them in
`/staff` → New course, then add students, assignments, announcements and calendar events.

## How the hub uses it

1. Connections → UniLearn: username + password are exchanged once for a token (password not stored,
   token stored encrypted with Fernet).
2. Sync: assignments → deadlines (submitted ⇒ completed), course events → calendar,
   Announcements forum posts → inbox + vector store + llama3.2 deadline extraction (once per post).
3. A deleted token returns `invalidtoken`: the hub marks the connection expired and asks to reconnect.

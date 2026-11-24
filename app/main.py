"""
Entry point FastAPI.

Avvio:  uvicorn app.main:app --reload
Docs:   http://127.0.0.1:8000/docs
"""
import logging
import os
from contextlib import asynccontextmanager

# ChromaDB: disattiva la telemetria anonima (il PoC deve restare 100% locale)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse  # noqa: E402
from pathlib import Path  # noqa: E402

from app.api.auth import router as auth_router  # noqa: E402
from app.api.connections_endpoints import router as connections_router  # noqa: E402
from app.api.endpoints import router  # noqa: E402
from app.api.professor_endpoints import router as professor_router  # noqa: E402
from app.config import settings  # noqa: E402
from app.database.db import init_db, session_scope  # noqa: E402
from app.services.sync_service import bootstrap_demo_data  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("academic_hub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inizializza lo schema SQLite, i dati Moodle di base e gli account demo."""
    if init_db():
        try:  # DB rigenerato: azzera anche gli avvisi indicizzati in ChromaDB
            from app.services import vector_store
            vector_store.reset_collection()
        except Exception as exc:  # il vector DB non deve bloccare l'avvio
            logger.warning("Reset ChromaDB non riuscito: %s", exc)
    settings.jwt_secret()  # genera/carica la chiave JWT
    with session_scope() as db:
        info = bootstrap_demo_data(db, seed_users=settings.DEMO_SEED_USERS)
    if info["imported"]:
        logger.info("Catalogo corsi importato (compiti ed eventi arrivano collegando UniLearn; POST /api/sync per Teams + AI)")
    if info["demo_users_created"]:
        logger.info("Account demo creati: %s", ", ".join(info["demo_users_created"]))
    with session_scope() as db:
        from app.services.staff_accounts import rotate_lecturer_passwords
        rotate_lecturer_passwords(db)   # lecturers never keep the shared demo password
    logger.info("Database pronto: %s", settings.DATABASE_URL)
    logger.info("LLM: %s @ %s | data di riferimento: %s", settings.OLLAMA_MODEL, settings.OLLAMA_HOST, settings.reference_now().date())
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "100% local PoC that unifies Moodle, Teams and email into one schema, "
        "extracts deadlines from free text with **llama3.2 (Ollama)** and answers "
        "students' questions with a **RAG** assistant (ChromaDB + SQLite).\n\n"
        "**Authentication:** click *Authorize* and enter email/password "
        "(e.g. `student@demo.it` / `demo1234`; lecturers only on this computer, passwords in data/STAFF-PASSWORDS.txt).\n\n"
        "**Demo flow:** `POST /api/sync` → `GET /api/deadlines` → "
        "`POST /api/professor/announcements` → `POST /api/chat`"
    ),
    lifespan=lifespan,
)

# CORS aperto: pronto per un futuro frontend locale (React/Vue) durante la demo
# Gli errori 500 non gestiti verrebbero generati *fuori* dal CORSMiddleware (senza header CORS)
# e il browser li mostrerebbe come "backend non raggiungibile": li convertiamo qui in JSON.
# Questo middleware è registrato prima di CORS, quindi è più interno e le sue risposte ricevono gli header CORS.
@app.middleware("http")
async def json_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:  # pragma: no cover - rete di sicurezza
        logger.exception("Errore non gestito su %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": f"Internal server error: {exc.__class__.__name__}: {exc}"})


# Il token viaggia nell'header Authorization (niente cookie) -> allow_credentials=False
# è sufficiente e permette anche l'apertura di index.html da file:// (Origin "null").
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)
app.include_router(professor_router)
app.include_router(connections_router)


@app.get("/", include_in_schema=False)
def root():
    """Serve the React UI (frontend/app/index.html); fall back to the classic page, then to Swagger."""
    for candidate in (settings.FRONTEND_PATH, settings.CLASSIC_FRONTEND_PATH):
        page = Path(candidate)
        if page.is_file():
            return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return RedirectResponse(url="/docs")


@app.get("/media/intro.mp4", include_in_schema=False)
def intro_video():
    """3-second Remind Me Bro intro shown once after sign-in (frontend/brand/intro.mp4, no audio)."""
    video = Path(settings.FRONTEND_PATH).parent.parent / "brand" / "intro.mp4"
    if not video.is_file():
        return JSONResponse({"detail": "intro not found"}, status_code=404)
    return FileResponse(video, media_type="video/mp4", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/classic", include_in_schema=False)
def classic(request: Request):
    """The previous single-file interface, kept as a fallback for demos (only on this computer, not through the public link)."""
    from app.api.access import is_local_request
    if not is_local_request(request):
        return RedirectResponse(url="/")
    page = Path(settings.CLASSIC_FRONTEND_PATH)
    if page.is_file():
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return RedirectResponse(url="/")

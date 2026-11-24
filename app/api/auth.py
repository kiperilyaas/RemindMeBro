"""
Autenticazione e autorizzazione.

- Password: hash bcrypt tramite passlib.
- Sessione: JWT firmato HS256 (python-jose), inviato dal client come
  header `Authorization: Bearer <token>`.
- Ruoli: `student` e `professor` (dependency `require_professor`).

Endpoint:
  POST /api/auth/register   registrazione (email, password, nome completo, ruolo)
  POST /api/auth/login      login JSON -> access_token + profilo
  POST /api/auth/token      login form OAuth2 (usato dal pulsante "Authorize" di Swagger)
  GET  /api/auth/me         profilo dell'utente autenticato
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.access import STAFF_ONLY_LOCAL, is_local_request
from app.config import settings
from app.database.db import get_db
from app.database.models import Course, User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
# tokenUrl abilita il login direttamente dal pulsante "Authorize" di Swagger UI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing, invalid or expired token. Please sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def create_access_token(user: User, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def get_current_user(request: Request, token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Dependency: decodifica il Bearer token e carica l'utente."""
    if not token:
        raise CREDENTIALS_ERROR
    try:
        payload = jwt.decode(token, settings.jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise CREDENTIALS_ERROR
    user = db.get(User, user_id)
    if user is None:
        raise CREDENTIALS_ERROR
    if user.role == UserRole.PROFESSOR and not is_local_request(request):
        raise STAFF_ONLY_LOCAL   # a lecturer token never works through the public link
    return user


def require_professor(user: User = Depends(get_current_user)) -> User:
    """Dependency: consente l'accesso solo ai docenti."""
    if user.role != UserRole.PROFESSOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This feature is reserved for lecturers.")
    return user


# ---------------------------------------------------------------------------
# Utility di dominio
# ---------------------------------------------------------------------------
def _normalize_name(name: str) -> str:
    """'Prof.ssa Laura Bianchi' -> 'laura bianchi' (per collegare i corsi Moodle ai docenti)."""
    n = name.lower().strip()
    for prefix in ("prof.ssa", "prof.", "prof", "dott.ssa", "dott.", "dr."):
        if n.startswith(prefix + " "):
            n = n[len(prefix) + 1 :]
    return " ".join(n.split())


def link_professor_courses(db: Session, user: User) -> int:
    """Assegna al docente i corsi (non ancora assegnati) il cui docente Moodle ha lo stesso nome."""
    if user.role != UserRole.PROFESSOR:
        return 0
    target = _normalize_name(user.full_name)
    linked = 0
    for course in db.scalars(select(Course).where(Course.professor_id.is_(None))):
        if _normalize_name(course.professor) == target:
            course.professor_id = user.id
            linked += 1
    return linked


def link_all_professors(db: Session) -> int:
    """Collega tutti i docenti registrati ai rispettivi corsi (chiamata dopo la sync)."""
    total = 0
    for prof in db.scalars(select(User).where(User.role == UserRole.PROFESSOR)):
        total += link_professor_courses(db, prof)
    return total


def create_user(db: Session, email: str, password: str, full_name: str, role: UserRole) -> User:
    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        role=role,
    )
    db.add(user)
    db.flush()
    link_professor_courses(db, user)
    return user


def _token_response(user: User) -> schemas.TokenResponse:
    return schemas.TokenResponse(
        access_token=create_access_token(user),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=schemas.UserOut.model_validate(user),
    )


def _authenticate(request: Request, db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower().strip()))
    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")
    if user.role == UserRole.PROFESSOR and not is_local_request(request):
        raise STAFF_ONLY_LOCAL
    return user


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/register", response_model=schemas.TokenResponse, status_code=201, summary="Register a user")
def register(payload: schemas.RegisterRequest, request: Request, db: Session = Depends(get_db)) -> schemas.TokenResponse:
    """
    Creates a student account and returns the token right away (auto-login).
    The student also gets a UniSIS and a UniLearn account with the same email and password, already connected.
    Lecturer accounts can only be created on the computer that runs the demo.
    """
    if payload.role == UserRole.PROFESSOR and not is_local_request(request):
        raise HTTPException(status_code=403, detail="Only students can create an account here.")
    exists = db.scalar(select(User).where(func.lower(User.email) == payload.email.lower()))
    if exists:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = create_user(db, payload.email, payload.password, payload.full_name, payload.role)
    db.commit()
    db.refresh(user)
    logger.info("Nuovo utente registrato: %s (%s)", user.email, user.role.value)
    if user.role == UserRole.STUDENT:
        from app.services import provisioning   # local import: provisioning uses the connectors
        provisioning.create_student_accounts(db, user, payload.password)
    return _token_response(user)


@router.post("/login", response_model=schemas.TokenResponse, summary="Login (JSON)")
def login(payload: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)) -> schemas.TokenResponse:
    return _token_response(_authenticate(request, db, payload.email, payload.password))


@router.post("/token", response_model=schemas.TokenResponse, summary="Login (OAuth2 form, used by Swagger)")
def login_form(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> schemas.TokenResponse:
    """Put the email in the `username` field."""
    return _token_response(_authenticate(request, db, form.username, form.password))


@router.get("/me", response_model=schemas.UserOut, summary="Current user profile")
def me(user: User = Depends(get_current_user)) -> User:
    return user


# ---------------------------------------------------------------------------
# Account demo
# ---------------------------------------------------------------------------
DEMO_STUDENT = {"email": "student@demo.it", "full_name": "Giulia Esposito", "role": UserRole.STUDENT}
# Same lecturers as UniLearn (marco.rossi, ...): their courses are created from scratch
DEMO_LECTURERS = ["Prof. Marco Rossi", "Prof. Laura Bianchi", "Prof. Giovanni Verdi", "Prof. Chiara Neri", "Prof. Paolo Conti"]


def _slug(name: str) -> str:
    return ".".join(_normalize_name(name).split())


def seed_demo_users(db: Session) -> list[dict]:
    """
    Crea (se mancano) uno studente demo e un docente per ogni corso sincronizzato.
    Password comune: settings.DEMO_PASSWORD.
    """
    wanted = [DEMO_STUDENT] + [
        {"email": f"{_slug(name)}@demo.it", "full_name": name, "role": UserRole.PROFESSOR} for name in DEMO_LECTURERS
    ]
    created = []
    seen = set()
    for u in wanted:
        if u["email"] in seen:
            continue
        seen.add(u["email"])
        if db.scalar(select(User).where(User.email == u["email"])) is None:
            create_user(db, u["email"], settings.DEMO_PASSWORD, u["full_name"], u["role"])
            created.append(u["email"])
    link_all_professors(db)
    db.commit()
    return created


def list_demo_accounts(db: Session) -> list[dict]:
    """Account demo (only shown on the computer that runs the demo). Only the demo student keeps the demo password."""
    out = []
    for user in db.scalars(select(User).where(User.email.like("%@demo.it")).order_by(User.role.desc(), User.full_name)):
        one_click = user.role == UserRole.STUDENT and verify_password(settings.DEMO_PASSWORD, user.hashed_password)
        out.append({"email": user.email, "full_name": user.full_name, "role": user.role.value,
                    "password": settings.DEMO_PASSWORD if one_click else None})
    return out

"""Hashing, token generation, PKCE, client credentials and redirect URI checks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlsplit

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from unisis.config import settings
from unisis.models import OAuthClient

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SCOPES = {
    "profile": "Your name, student number, programme, credits and average",
    "timetable": "Your personal timetable",
    "enrollments": "Your courses and course registration status",
    "enrollments:write": "Enroll in and drop courses during the registration window",
    "exams": "Exam dates and your exam registrations",
    "exams:write": "Register for and cancel exam registrations",
    "grades": "Your transcript and grades",
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except (ValueError, TypeError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_secret(prefix: str = "", nbytes: int = 32) -> str:
    return prefix + secrets.token_urlsafe(nbytes)


def verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed, challenge)


def redirect_uri_allowed(client: OAuthClient, redirect_uri: str) -> bool:
    """Exact match, except loopback URIs where the port may differ (RFC 8252 §7.3)."""
    registered = [u.strip() for u in client.redirect_uris.splitlines() if u.strip()]
    if redirect_uri in registered:
        return True
    try:
        req = urlsplit(redirect_uri)
    except ValueError:
        return False
    for uri in registered:
        reg = urlsplit(uri)
        if (
            reg.hostname in {"127.0.0.1", "localhost"}
            and req.hostname in {"127.0.0.1", "localhost"}
            and reg.scheme == req.scheme
            and reg.path == req.path
        ):
            return True
    return False


def authenticate_client(db: Session, client_id: Optional[str], client_secret: Optional[str]) -> Optional[OAuthClient]:
    if not client_id or not client_secret:
        return None
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    if client and hmac.compare_digest(client.secret_hash, sha256(client_secret)):
        return client
    return None


def client_by_api_key(db: Session, api_key: Optional[str]) -> Optional[OAuthClient]:
    if not api_key:
        return None
    return db.scalar(select(OAuthClient).where(OAuthClient.api_key_hash == sha256(api_key)))


def parse_basic_auth(header: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not header or not header.lower().startswith("basic "):
        return None, None
    try:
        raw = base64.b64decode(header[6:]).decode()
        cid, _, secret = raw.partition(":")
        return cid, secret
    except (ValueError, UnicodeDecodeError):
        return None, None


def rotate_client_secret(client: OAuthClient) -> str:
    secret = new_secret("uss_")
    client.secret_hash = sha256(secret)
    client.secret_hint = secret[-4:]
    client.secret_rotated_at = datetime.now()
    return secret


def rotate_api_key(client: OAuthClient) -> str:
    key = new_secret("usk_", 24)
    client.api_key_hash = sha256(key)
    client.api_key_hint = key[-4:]
    return key


def export_credentials(client: OAuthClient, issuer: str, secret: Optional[str] = None, api_key: Optional[str] = None) -> None:
    """
    Writes the client's plaintext credentials to data/unisis/clients/<client_id>.json, like
    "Download credentials" in a developer portal. Only values passed in are updated.
    """
    settings.CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.CREDENTIALS_DIR / f"{client.client_id}.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            data = {}
    data.update({"client_id": client.client_id, "issuer": issuer, "updated_at": datetime.now().isoformat(timespec="seconds")})
    if secret:
        data["client_secret"] = secret
    if api_key:
        data["api_key"] = api_key
    path.write_text(json.dumps(data, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def exported_credentials_valid(client: OAuthClient) -> bool:
    path = settings.CREDENTIALS_DIR / f"{client.client_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return False
    return (
        sha256(data.get("client_secret", "")) == client.secret_hash
        and sha256(data.get("api_key", "")) == client.api_key_hash
    )


# ---------------------------------------------------------------------------
# CSRF for the web portal (token stored in the signed session cookie)
# ---------------------------------------------------------------------------
def csrf_token(session: dict) -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def csrf_valid(session: dict, token: Optional[str]) -> bool:
    expected = session.get("csrf")
    return bool(expected and token and hmac.compare_digest(expected, token))

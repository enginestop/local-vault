import asyncio
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import errors
from ..crypto.csprng import random_bytes
from ..domain.models import now_utc

GRACE_SECONDS = 10
TICKET_SECONDS = 10


class Session:
    def __init__(self, token: str, tab_instance_id: str, client_label: str, user_id: str | None = None) -> None:
        self.session_id = str(uuid.uuid4())
        self.token_digest = hashlib_sha256(token)
        self.tab_instance_id = tab_instance_id
        self.client_label = client_label
        self.user_id = user_id
        self.created_at = now_utc()
        now = datetime.now(timezone.utc)
        self.last_active_at = now
        self.ws_connected = False
        # The ten-second grace starts only after an established owner WebSocket
        # disconnects; there is no idle or absolute timeout for a healthy owner.
        self.disconnect_deadline: Optional[datetime] = None
        self.owner_ws: Optional[asyncio.Queue] = None

    def verify(self, token: str) -> bool:
        import hmac

        return hmac.compare_digest(self.token_digest, hashlib_sha256(token))


def hashlib_sha256(token: str) -> bytes:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).digest()


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._tab_owners: dict[str, str] = {}
        self._tickets: dict[str, tuple[str, datetime]] = {}
        self._lock = threading.RLock()

    def create_session(
        self, master_token: str, tab_instance_id: str, client_label: str, user_id: str | None = None
    ) -> Session:
        if not _is_uuid(tab_instance_id):
            raise errors.ValidationError("tab_instance_id must be a UUID")
        with self._lock:
            if tab_instance_id in self._tab_owners:
                raise errors.ProblemError(
                    "TAB_OWNERSHIP_CONFLICT",
                    "Tab ownership conflict",
                    "This tab instance already owns a session.",
                    409,
                )
            session = Session(master_token, tab_instance_id, client_label, user_id)
            self._sessions[session.session_id] = session
            self._tab_owners[tab_instance_id] = session.session_id
            return session

    def get_by_token(self, token: str) -> Optional[Session]:
        now = datetime.now(timezone.utc)
        with self._lock:
            for session in list(self._sessions.values()):
                if session.disconnect_deadline and now >= session.disconnect_deadline:
                    self._remove(session)
                    continue
                if session.verify(token):
                    session.last_active_at = now
                    return session
        return None

    def get_by_id(self, session_id: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(session_id)

    def has_sessions(self) -> bool:
        with self._lock:
            return bool(self._sessions)

    def active_session_ids(self) -> set[str]:
        with self._lock:
            return set(self._sessions)

    def issue_ticket(self, token: str) -> str:
        session = self.get_by_token(token)
        if session is None:
            raise errors.SessionInvalid()
        ticket = random_bytes(32).hex()
        with self._lock:
            self._tickets[ticket] = (
                session.session_id,
                datetime.now(timezone.utc) + timedelta(seconds=TICKET_SECONDS),
            )
        return ticket

    def consume_ticket(self, ticket: str) -> Optional[Session]:
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._tickets.pop(ticket, None)
            if record is None:
                return None
            session_id, expires_at = record
            if now >= expires_at:
                return None
            return self._sessions.get(session_id)

    def set_ws_connected(self, session: Session, queue: asyncio.Queue) -> None:
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is None:
                raise errors.SessionInvalid()
            if current.ws_connected and current.owner_ws is not queue:
                raise errors.ProblemError(
                    "TAB_OWNERSHIP_CONFLICT",
                    "Tab ownership conflict",
                    "This session already has an active owner connection.",
                    409,
                )
            current.ws_connected = True
            current.disconnect_deadline = None
            current.owner_ws = queue
            current.last_active_at = datetime.now(timezone.utc)

    def touch(self, session: Session) -> None:
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is not None:
                current.last_active_at = datetime.now(timezone.utc)

    def mark_disconnected(self, session: Session, queue: asyncio.Queue) -> None:
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is None or current.owner_ws is not queue:
                return
            current.ws_connected = False
            current.disconnect_deadline = datetime.now(timezone.utc) + timedelta(
                seconds=GRACE_SECONDS
            )

    def lock_session(self, token: str) -> None:
        with self._lock:
            session = self.get_by_token(token)
            if session is None:
                raise errors.SessionInvalid()
            self._send_to_session(session, _event("vault.locked"))
            self._remove(session)

    def lock_all(self) -> None:
        event = _event("vault.locked")
        with self._lock:
            for session in list(self._sessions.values()):
                self._send_to_session(session, event)
            self._sessions.clear()
            self._tab_owners.clear()
            self._tickets.clear()

    def lock_user(self, user_id: str) -> None:
        with self._lock:
            for session in list(self._sessions.values()):
                if session.user_id == user_id:
                    self._send_to_session(session, _event("vault.locked"))
                    self._remove(session)

    def _remove(self, session: Session) -> None:
        self._sessions.pop(session.session_id, None)
        self._tab_owners.pop(session.tab_instance_id, None)
        for ticket, (session_id, _) in list(self._tickets.items()):
            if session_id == session.session_id:
                self._tickets.pop(ticket, None)

    def broadcast(self, event: dict) -> None:
        with self._lock:
            for session in list(self._sessions.values()):
                self._send_to_session(session, event)

    @staticmethod
    def _send_to_session(session: Session, event: dict) -> None:
        if session.owner_ws is None:
            return
        try:
            session.owner_ws.put_nowait(dict(event))
        except Exception:
            pass

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        removed = 0
        with self._lock:
            for ticket, (_, expires_at) in list(self._tickets.items()):
                if now >= expires_at:
                    self._tickets.pop(ticket, None)
            for session in list(self._sessions.values()):
                if session.disconnect_deadline and now >= session.disconnect_deadline:
                    self._remove(session)
                    removed += 1
        return removed

def _event(event_type: str) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "entity_type": None,
        "entity_id": None,
        "entity_revision": None,
        "vault_revision": None,
        "occurred_at": now_utc(),
    }


def _is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False

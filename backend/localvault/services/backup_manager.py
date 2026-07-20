import hashlib
import os
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from .. import errors
from ..db import immediate_tx
from ..domain.envelope import (
    CONTAINER_VERSION,
    LEGACY_CONTAINER_VERSION,
    MAGIC,
    BackupManifest,
    VaultEnvelope,
    compute_checksum,
    pack_backup,
    serialize_envelope,
    unpack_backup_with_version,
)

MAX_BACKUP_BYTES = 512 * 1024 * 1024
VERSION_BUCKET_KEEP = 10
DAILY_BUCKET_DAYS = 30


def _now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class BackupTransaction:
    def __init__(self, manager: "BackupManager", tx, created_paths: list[str]) -> None:
        self.manager = manager
        self.tx = tx
        self.created_paths = created_paths

    def write_backup(
        self,
        env: VaultEnvelope,
        kind: str,
        operation: Optional[str] = None,
    ) -> str:
        return self.manager._write_backup(
            self.tx, self.created_paths, env, kind, operation
        )


class BackupManager:
    def __init__(self, data_dir: str, conn) -> None:
        self.data_dir = os.path.realpath(data_dir)
        self.backups_dir = os.path.join(self.data_dir, "backups")
        os.makedirs(self.backups_dir, exist_ok=True)
        self.conn = conn
        self.reconcile_index()

    @contextmanager
    def transaction(self):
        created_paths: list[str] = []
        try:
            with immediate_tx(self.conn) as tx:
                yield BackupTransaction(self, tx, created_paths)
        except Exception:
            for path in reversed(created_paths):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            raise

    def _write_backup(
        self,
        tx,
        created_paths: list[str],
        env: VaultEnvelope,
        kind: str,
        operation: Optional[str],
    ) -> str:
        if not tx.in_transaction:
            raise RuntimeError("backup write requires an active transaction")
        backup_id = str(uuid.uuid4())
        manifest = BackupManifest(
            format_version=CONTAINER_VERSION,
            backup_id=backup_id,
            vault_id=env.vault_id,
            schema_version=env.schema_version,
            vault_revision=env.vault_revision,
            created_at=_now(),
            kind=kind,
            operation=operation,
            envelope_sha256=hashlib.sha256(serialize_envelope(env)).hexdigest(),
            application_version="1.0.0",
        )
        data = pack_backup(manifest, env)
        # Validate the exact bytes before they become durable.
        self._parse(data)
        stamp = manifest.created_at.replace(":", "").replace("-", "").replace(".", "")
        fname = (
            f"lv-{env.vault_id[:8]}-r{env.vault_revision}-{stamp}-"
            f"{kind}-{backup_id}.lvbak"
        )
        rel = os.path.join("backups", fname)
        abs_path = os.path.join(self.backups_dir, fname)
        tmp = abs_path + ".tmp"
        try:
            with open(tmp, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, abs_path)
            created_paths.append(abs_path)
            bucket = "daily" if kind == "daily" else "version"
            tx.execute(
                """
                INSERT INTO backup_index(
                    backup_id, vault_id, schema_version, vault_revision, created_at,
                    kind, operation, envelope_sha256, application_version,
                    relative_path, bucket, valid
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)
                """,
                (
                    backup_id,
                    env.vault_id,
                    env.schema_version,
                    env.vault_revision,
                    manifest.created_at,
                    kind,
                    operation,
                    manifest.envelope_sha256,
                    manifest.application_version,
                    rel,
                    bucket,
                ),
            )
        finally:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
        return backup_id

    def apply_retention(self) -> None:
        paths_to_remove: list[str] = []
        with immediate_tx(self.conn) as tx:
            rows = tx.execute(
                "SELECT * FROM backup_index WHERE valid = 1 "
                "ORDER BY vault_revision DESC, created_at DESC, backup_id DESC"
            ).fetchall()
            keep_ids = {
                row["backup_id"]
                for row in [r for r in rows if r["bucket"] == "version"][:VERSION_BUCKET_KEEP]
            }
            seen_dates: set[str] = set()
            for row in sorted(
                [r for r in rows if r["bucket"] == "daily"],
                key=lambda item: (item["created_at"], item["backup_id"]),
                reverse=True,
            ):
                date = row["created_at"][:10]
                if date not in seen_dates and len(seen_dates) < DAILY_BUCKET_DAYS:
                    seen_dates.add(date)
                    keep_ids.add(row["backup_id"])
            for row in rows:
                if row["bucket"] in ("version", "daily") and row["backup_id"] not in keep_ids:
                    paths_to_remove.append(self._absolute_path(row["relative_path"]))
                    tx.execute(
                        "DELETE FROM backup_index WHERE backup_id = ?",
                        (row["backup_id"],),
                    )
        # A failed unlink leaves an unindexed orphan, never an index pointing to
        # a missing file. Reconciliation can remove it on a later startup.
        for path in paths_to_remove:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def reconcile_index(self) -> None:
        for name in os.listdir(self.backups_dir):
            if name.endswith(".tmp"):
                try:
                    os.remove(os.path.join(self.backups_dir, name))
                except OSError:
                    pass
        missing: list[str] = []
        for row in self.conn.execute(
            "SELECT backup_id, relative_path FROM backup_index WHERE valid = 1"
        ).fetchall():
            try:
                exists = os.path.isfile(self._absolute_path(row["relative_path"]))
            except ValueError:
                exists = False
            if not exists:
                missing.append(row["backup_id"])
        if missing:
            with immediate_tx(self.conn) as tx:
                tx.executemany(
                    "UPDATE backup_index SET valid = 0 WHERE backup_id = ?",
                    [(backup_id,) for backup_id in missing],
                )

    def list_manifests(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT backup_id, vault_id, schema_version, vault_revision, created_at, "
            "kind, operation, envelope_sha256, application_version, relative_path, "
            "bucket, valid FROM backup_index "
            "ORDER BY vault_revision DESC, created_at DESC, backup_id DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def _absolute_path(self, relative_path: str) -> str:
        candidate = os.path.realpath(os.path.join(self.data_dir, relative_path))
        if os.path.commonpath((candidate, self.backups_dir)) != self.backups_dir:
            raise ValueError("backup path escapes backup directory")
        return candidate

    def get_path(self, backup_id: str) -> str:
        row = self.conn.execute(
            "SELECT relative_path, valid FROM backup_index WHERE backup_id = ?",
            (backup_id,),
        ).fetchone()
        if row is None or not row["valid"]:
            raise errors.NotFoundError("backup not found")
        try:
            path = self._absolute_path(row["relative_path"])
        except ValueError as exc:
            raise errors.ValidationError(str(exc)) from exc
        if not os.path.isfile(path):
            raise errors.ValidationError("backup file is missing")
        return path

    def read_backup(self, backup_id: str) -> tuple[BackupManifest, VaultEnvelope]:
        path = self.get_path(backup_id)
        with open(path, "rb") as handle:
            data = handle.read(MAX_BACKUP_BYTES + 1)
        return self._parse(data)

    def parse_upload(self, data: bytes) -> tuple[BackupManifest, VaultEnvelope]:
        return self._parse(data)

    def _parse(self, data: bytes) -> tuple[BackupManifest, VaultEnvelope]:
        if len(data) > MAX_BACKUP_BYTES:
            raise errors.ValidationError("backup file too large")
        if not data.startswith(MAGIC):
            raise errors.ValidationError("invalid backup file")
        try:
            manifest, env, container_version = unpack_backup_with_version(data)
        except Exception as exc:
            raise errors.ValidationError("corrupt backup container") from exc
        if compute_checksum(env) != env.envelope_checksum:
            raise errors.ValidationError("envelope checksum mismatch")
        if container_version == CONTAINER_VERSION:
            expected = hashlib.sha256(serialize_envelope(env)).hexdigest()
        elif container_version == LEGACY_CONTAINER_VERSION:
            blank_manifest = replace(manifest, envelope_sha256="")
            expected = hashlib.sha256(
                pack_backup(blank_manifest, env, LEGACY_CONTAINER_VERSION)
            ).hexdigest()
        else:  # guarded by unpack_backup
            raise errors.ValidationError("unsupported backup version")
        if not manifest.envelope_sha256 or not _digest_equal(
            manifest.envelope_sha256, expected
        ):
            raise errors.ValidationError("backup manifest hash mismatch")
        return manifest, env


def _digest_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.lower(), right.lower())

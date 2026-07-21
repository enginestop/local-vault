import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..database.pool import get_pool
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
from .. import errors

MAX_BACKUP_BYTES = 512 * 1024 * 1024
VERSION_BUCKET_KEEP = 10
DAILY_BUCKET_DAYS = 30


def _now() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class BackupManager:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = os.path.realpath(data_dir)
        self.backups_dir = os.path.join(self.data_dir, "backups")
        os.makedirs(self.backups_dir, exist_ok=True)

    async def write_backup(
        self,
        user_id: str,
        env: VaultEnvelope,
        kind: str,
        operation: Optional[str] = None,
    ) -> str:
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
        self._parse(data)
        stamp = manifest.created_at.replace(":", "").replace("-", "").replace(".", "")
        fname = f"lv-{env.vault_id[:8]}-r{env.vault_revision}-{stamp}-{kind}-{backup_id}.lvbak"
        rel = os.path.join("backups", fname)
        abs_path = os.path.join(self.backups_dir, fname)
        tmp = abs_path + ".tmp"
        try:
            with open(tmp, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, abs_path)
        except Exception:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
            try:
                os.remove(abs_path)
            except FileNotFoundError:
                pass
            raise
        try:
            await self._index_backup(backup_id, user_id, manifest, rel)
        except Exception:
            try:
                os.remove(abs_path)
            except FileNotFoundError:
                pass
            raise
        return backup_id

    async def _index_backup(self, backup_id: str, user_id: str, manifest: BackupManifest, rel: str) -> None:
        pool = get_pool()
        bucket = "daily" if manifest.kind == "daily" else "version"
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO backup_index(
                    backup_id, user_id, vault_id, schema_version, vault_revision, created_at,
                    kind, operation, envelope_sha256, application_version,
                    relative_path, bucket, valid
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,1)
                """,
                backup_id, user_id, manifest.vault_id, manifest.schema_version,
                manifest.vault_revision, manifest.created_at, manifest.kind,
                manifest.operation, manifest.envelope_sha256,
                manifest.application_version, rel, bucket,
            )

    async def list_manifests(self, user_id: str) -> list[dict]:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT backup_id, vault_id, schema_version, vault_revision, created_at,
                       kind, operation, envelope_sha256, application_version, relative_path,
                       bucket, valid
                FROM backup_index
                WHERE user_id = $1::uuid AND valid = 1
                ORDER BY vault_revision DESC, created_at DESC, backup_id DESC
                """,
                user_id,
            )
        return [dict(row) for row in rows]

    async def get_path(self, backup_id: str, user_id: str) -> str:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT relative_path, valid FROM backup_index WHERE backup_id = $1 AND user_id = $2::uuid",
                backup_id, user_id,
            )
        if row is None or not row["valid"]:
            raise errors.NotFoundError("backup not found")
        try:
            path = self._absolute_path(row["relative_path"])
        except ValueError as exc:
            raise errors.ValidationError(str(exc)) from exc
        if not os.path.isfile(path):
            raise errors.ValidationError("backup file is missing")
        return path

    async def read_backup(self, backup_id: str, user_id: str) -> tuple[BackupManifest, VaultEnvelope]:
        path = await self.get_path(backup_id, user_id)
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
            blank_manifest = manifest.model_copy(update={"envelope_sha256": ""})
            expected = hashlib.sha256(
                pack_backup(blank_manifest, env, LEGACY_CONTAINER_VERSION)
            ).hexdigest()
        else:
            raise errors.ValidationError("unsupported backup version")
        if not manifest.envelope_sha256 or not _digest_equal(
            manifest.envelope_sha256, expected
        ):
            raise errors.ValidationError("backup manifest hash mismatch")
        return manifest, env

    async def apply_retention(self, user_id: str) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM backup_index
                WHERE user_id = $1::uuid AND valid = 1
                ORDER BY vault_revision DESC, created_at DESC, backup_id DESC
                """,
                user_id,
            )
            keep_ids = {row["backup_id"] for row in rows[:VERSION_BUCKET_KEEP]} if rows else set()
            seen_dates = set()
            for row in sorted(
                [r for r in rows if r["bucket"] == "daily"],
                key=lambda item: (item["created_at"], item["backup_id"]),
                reverse=True,
            ):
                date = row["created_at"][:10]
                if date not in seen_dates and len(seen_dates) < DAILY_BUCKET_DAYS:
                    seen_dates.add(date)
                    keep_ids.add(row["backup_id"])
            paths_to_remove = []
            for row in rows:
                if row["bucket"] in ("version", "daily") and row["backup_id"] not in keep_ids:
                    paths_to_remove.append(self._absolute_path(row["relative_path"]))
                    await conn.execute(
                        "DELETE FROM backup_index WHERE backup_id = $1",
                        row["backup_id"],
                    )
        for path in paths_to_remove:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _absolute_path(self, relative_path: str) -> str:
        candidate = os.path.realpath(os.path.join(self.data_dir, relative_path))
        if os.path.commonpath((candidate, self.backups_dir)) != self.backups_dir:
            raise ValueError("backup path escapes backup directory")
        return candidate


def _digest_equal(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left.lower(), right.lower())

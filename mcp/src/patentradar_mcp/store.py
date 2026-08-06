from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .models import PROVIDERS, ProviderName
from .security import SecretBox, new_workspace_token, token_hash


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path, secret_box: SecretBox) -> None:
        self.db_path = db_path
        self.secret_box = secret_box
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_keys (
                    workspace_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, provider),
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    publication_no TEXT NOT NULL,
                    search_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage_index INTEGER NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_cases_workspace ON cases(workspace_id, updated_at);
                """
            )

    def create_workspace(self) -> tuple[str, str]:
        workspace_id = "ws_" + uuid.uuid4().hex
        token = new_workspace_token()
        with self._connect() as db:
            db.execute(
                "INSERT INTO workspaces(id, token_hash, created_at) VALUES (?, ?, ?)",
                (workspace_id, token_hash(token), _now()),
            )
        return workspace_id, token

    def authenticate(self, token: str) -> str | None:
        if not token.startswith("prw_"):
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT id FROM workspaces WHERE token_hash = ?", (token_hash(token),)
            ).fetchone()
        return str(row["id"]) if row else None

    def key_status(self, workspace_id: str) -> dict[ProviderName, bool]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT provider FROM provider_keys WHERE workspace_id = ?", (workspace_id,)
            ).fetchall()
        configured = {str(row["provider"]) for row in rows}
        return {provider: provider in configured for provider in PROVIDERS}

    def update_keys(self, workspace_id: str, values: dict[ProviderName, str]) -> dict[ProviderName, bool]:
        with self._connect() as db:
            for provider, value in values.items():
                encrypted = self.secret_box.encrypt(value)
                db.execute(
                    """
                    INSERT INTO provider_keys(workspace_id, provider, encrypted_value, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(workspace_id, provider) DO UPDATE SET
                        encrypted_value = excluded.encrypted_value,
                        updated_at = excluded.updated_at
                    """,
                    (workspace_id, provider, encrypted, _now()),
                )
        return self.key_status(workspace_id)

    def delete_key(self, workspace_id: str, provider: ProviderName) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM provider_keys WHERE workspace_id = ? AND provider = ?",
                (workspace_id, provider),
            )

    def decrypted_keys(self, workspace_id: str) -> dict[ProviderName, str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT provider, encrypted_value FROM provider_keys WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchall()
        values = {
            str(row["provider"]): self.secret_box.decrypt(str(row["encrypted_value"]))
            for row in rows
        }
        return cast(dict[ProviderName, str], values)

    def create_case(self, workspace_id: str, publication_no: str) -> dict[str, Any]:
        case_id = "case_" + uuid.uuid4().hex
        now = _now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO cases(
                    id, workspace_id, publication_no, search_mode, status,
                    stage_index, artifacts_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', 0, '{}', '', ?, ?)
                """,
                (case_id, workspace_id, publication_no, "auto", now, now),
            )
        return self.get_case(workspace_id, case_id)

    def get_case(self, workspace_id: str, case_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM cases WHERE id = ? AND workspace_id = ?", (case_id, workspace_id)
            ).fetchone()
        if row is None:
            raise KeyError("案件不存在或不属于当前工作区")
        item = dict(row)
        item["artifacts"] = json.loads(item.pop("artifacts_json"))
        return item

    def save_artifact(
        self,
        workspace_id: str,
        case_id: str,
        *,
        stage: str,
        artifact: dict[str, Any],
        next_stage_index: int,
        completed: bool,
    ) -> dict[str, Any]:
        case = self.get_case(workspace_id, case_id)
        artifacts = case["artifacts"]
        artifacts[stage] = artifact
        status = "completed" if completed else "active"
        with self._connect() as db:
            db.execute(
                """
                UPDATE cases SET artifacts_json = ?, stage_index = ?, status = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ?
                """,
                (json.dumps(artifacts, ensure_ascii=False), next_stage_index, status, _now(), case_id, workspace_id),
            )
        return self.get_case(workspace_id, case_id)

    def save_search_results(
        self,
        workspace_id: str,
        case_id: str,
        results: dict[str, Any],
        *,
        stage: str,
    ) -> dict[str, Any]:
        case = self.get_case(workspace_id, case_id)
        artifacts = case["artifacts"]
        buckets = artifacts.setdefault("_provider_search", {})
        previous = buckets.get(stage) or {}
        merged_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in [*(previous.get("results") or []), *(results.get("results") or [])]:
            url = str(item.get("url") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged_results.append({**item, "result_id": f"R{len(merged_results) + 1:04d}"})
        buckets[stage] = {
            "queries": list(dict.fromkeys([*(previous.get("queries") or []), *(results.get("queries") or [])])),
            "query_plan": [*(previous.get("query_plan") or []), *(results.get("query_plan") or [])],
            "search_modes": list(
                dict.fromkeys([*(previous.get("search_modes") or []), *(results.get("search_modes") or [])])
            ),
            "configured_providers": list(
                dict.fromkeys(
                    [
                        *(previous.get("configured_providers") or []),
                        *(results.get("configured_providers") or []),
                    ]
                )
            ),
            "result_count": len(merged_results),
            "results": merged_results,
            "errors": [*(previous.get("errors") or []), *(results.get("errors") or [])],
            "routing": [*(previous.get("routing") or []), *(results.get("routing") or [])],
            "attempted_providers": list(
                dict.fromkeys([*(previous.get("attempted_providers") or []), *(results.get("attempted_providers") or [])])
            ),
            "successful_providers": list(
                dict.fromkeys([*(previous.get("successful_providers") or []), *(results.get("successful_providers") or [])])
            ),
            "quota_limited_providers": list(
                dict.fromkeys(
                    [*(previous.get("quota_limited_providers") or []), *(results.get("quota_limited_providers") or [])]
                )
            ),
        }
        buckets[stage]["usable"] = bool(merged_results)
        buckets[stage]["fallback_reason"] = (
            "" if merged_results else results.get("fallback_reason") or previous.get("fallback_reason") or "provider_no_results"
        )
        with self._connect() as db:
            db.execute(
                "UPDATE cases SET artifacts_json = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
                (json.dumps(artifacts, ensure_ascii=False), _now(), case_id, workspace_id),
            )
        return self.get_case(workspace_id, case_id)

    def save_search_audit(
        self,
        workspace_id: str,
        case_id: str,
        *,
        stage: str,
        codex_builtin_queries: list[str],
    ) -> dict[str, Any]:
        case = self.get_case(workspace_id, case_id)
        artifacts = case["artifacts"]
        audits = artifacts.setdefault("_search_audits", {})
        audits[stage] = {
            "codex_builtin_attempted": bool(codex_builtin_queries),
            "codex_builtin_queries": list(dict.fromkeys(codex_builtin_queries)),
        }
        with self._connect() as db:
            db.execute(
                "UPDATE cases SET artifacts_json = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
                (json.dumps(artifacts, ensure_ascii=False), _now(), case_id, workspace_id),
            )
        return self.get_case(workspace_id, case_id)

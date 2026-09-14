"""Small, local-only case records for reproducible vNext experiments.

This module deliberately does not touch the production SQLite store, upload
files, or GitHub.  It writes one JSON and one human-readable Markdown file per
case so a later experiment can be reviewed without relying on application
state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Literal


CaseResult = Literal["success", "failure", "partial", "blocked"]
_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|cookie|invite[_-]?code|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|cookie|invite[_-]?code|password|private[_-]?key|secret|token)\s*[:=]\s*[^\s,;]+"
)
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\(?:[^\\/\s]+\\)*[^\\/\s]+")


def _redact_text(value: str) -> str:
    redacted = _SENSITIVE_TEXT.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    return _WINDOWS_PATH.sub(lambda match: f"<local>/{Path(match.group(0)).name}", redacted)


def _safe_value(value: Any) -> Any:
    """Return JSON-compatible, non-secret case metadata.

    Absolute local paths are reduced to a local marker plus filename.  A case
    should point at a reviewed local artifact, but must not leak a Windows
    username or workspace path when the metadata is later shared.
    """

    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    if isinstance(value, Path):
        return _safe_value(str(value))
    if isinstance(value, str):
        text = _redact_text(value)
        path = Path(text)
        if path.is_absolute():
            return f"<local>/{path.name}"
        return text
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass(slots=True)
class CaseRecord:
    """The minimum metadata required to reproduce one experiment."""

    case_id: str
    result: CaseResult
    title: str
    expected: str
    actual: str
    code_version: str = "unknown"
    model_versions: dict[str, Any] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    reproduce_steps: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = "1.0"

    def validate(self) -> None:
        if not _CASE_ID.fullmatch(self.case_id):
            raise ValueError("case_id must be 3-64 lowercase letters, numbers, '.', '_' or '-'")
        if self.result not in {"success", "failure", "partial", "blocked"}:
            raise ValueError("result must be success, failure, partial, or blocked")
        for name in ("title", "expected", "actual"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return _safe_value(asdict(self))


def write_case(root: Path, record: CaseRecord) -> Path:
    """Write an independent case directory and return its path.

    Existing case directories are not silently overwritten.  The caller may
    explicitly choose a new case id for a rerun, preserving both records.
    """

    payload = record.payload()
    root = Path(root)
    case_dir = root / record.case_id
    if case_dir.exists():
        raise FileExistsError(f"case already exists: {case_dir}")
    case_dir.mkdir(parents=True)
    (case_dir / "evidence").mkdir()
    (case_dir / "input").mkdir()
    (case_dir / "case.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evidence_lines = "\n".join(f"- `{item}`" for item in payload["evidence"]) or "- 暂无（仅保留文字结果）"
    steps = "\n".join(f"{index}. {item}" for index, item in enumerate(payload["reproduce_steps"], 1)) or "1. 暂无复现步骤；补充后再共享。"
    readme = (
        f"# {payload['title']}\n\n"
        f"- 案例 ID：`{payload['case_id']}`\n"
        f"- 结果：`{payload['result']}`\n"
        f"- 创建时间：`{payload['created_at']}`\n\n"
        f"## 预期\n\n{payload['expected']}\n\n"
        f"## 实际\n\n{payload['actual']}\n\n"
        f"## 复现步骤\n\n{steps}\n\n"
        f"## 证据\n\n{evidence_lines}\n\n"
        f"## 版本与资源\n\n"
        f"- 代码：`{payload['code_version']}`\n"
        f"- 模型：`{json.dumps(payload['model_versions'], ensure_ascii=False)}`\n"
        f"- 硬件：`{json.dumps(payload['hardware'], ensure_ascii=False)}`\n"
        f"- 耗时（毫秒）：`{json.dumps(payload['timings_ms'], ensure_ascii=False)}`\n\n"
        f"## 备注\n\n{payload['notes'] or '无'}\n"
    )
    (case_dir / "README.md").write_text(_redact_text(readme), encoding="utf-8")
    return case_dir


def read_case(case_dir: Path) -> dict[str, Any]:
    """Read and validate a case JSON without executing its text fields."""

    path = Path(case_dir) / "case.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "case_id", "result", "title", "expected", "actual"}
    missing = required.difference(payload)
    if missing:
        raise ValueError(f"case is missing fields: {', '.join(sorted(missing))}")
    if not _CASE_ID.fullmatch(str(payload["case_id"])):
        raise ValueError("invalid case_id in case.json")
    return payload

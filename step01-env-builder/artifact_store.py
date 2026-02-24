"""Step 01: Azure Env Builder — 成果物保存・ログ追記

_write_text / _write_json: ファイル書き込み
_append_deploy_log: deploy.log 追記
_build_result_md: result.md 生成
_build_spec_md: spec.md 生成
_timestamp_compact: タイムスタンプ文字列
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from az_runner import RepairHint


def _timestamp_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: object) -> None:
    _write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _append_deploy_log(log_path: Path, result: "AzResult") -> None:  # noqa: F821
    from az_runner import AzResult  # noqa: PLC0415

    parts: list[str] = []
    parts.append("=" * 88)
    parts.append(f"cmd: {' '.join(result.argv)}")
    parts.append(f"exit: {result.returncode}   duration_ms: {result.duration_ms}")
    parts.append("--- stdout ---")
    parts.append(result.stdout.rstrip("\n"))
    parts.append("--- stderr ---")
    parts.append(result.stderr.rstrip("\n"))
    parts.append("")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")


def _build_result_md(
    *,
    status: str,
    phase: str,
    attempt: int | None = None,
    max_attempts: int | None = None,
    hint: RepairHint | None = None,
    az_returncode: int | None = None,
    outputs: dict[str, object] | None = None,
) -> str:
    lines: list[str] = ["# Result", "", f"- status: {status}", f"- phase: {phase}"]
    if attempt is not None and max_attempts is not None:
        lines.append(f"- attempt: {attempt}/{max_attempts}")
    if az_returncode is not None:
        lines.append(f"- az_exit: {az_returncode}")
    if hint is not None:
        lines.append(f"- category: {hint.category}")
        lines.append(f"- summary: {hint.summary}")
        if hint.next_actions:
            lines.append("- next_actions:")
            for action in hint.next_actions:
                lines.append(f"  - {action}")
    if outputs is not None:
        lines.append("- outputs:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(outputs, ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _build_spec_md(
    *,
    prompt: str,
    subscription: str | None,
    resource_group: str,
    location: str,
    what_if: bool,
    az_commands: Iterable[Sequence[str]],
) -> str:
    lines: list[str] = []
    lines.append("# Azure Env Builder Spec")
    lines.append("")
    lines.append(f"- generated_at: {datetime.now().isoformat()}")
    lines.append(f"- python: {sys.version.split()[0]}")
    lines.append(f"- platform: {platform.platform()}")
    lines.append("")
    lines.append("## Input")
    lines.append("")
    lines.append("```text")
    lines.append(prompt)
    lines.append("```")
    lines.append("")
    lines.append("## Target")
    lines.append("")
    lines.append(f"- subscription: {subscription or '(az default)'}")
    lines.append(f"- resource_group: {resource_group}")
    lines.append(f"- location: {location}")
    lines.append(f"- what_if: {what_if}")
    lines.append("")
    lines.append("## az commands")
    lines.append("")
    for cmd in az_commands:
        lines.append(f"- az {' '.join(cmd)}")
    lines.append("")
    return "\n".join(lines)

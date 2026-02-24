"""Step 01: Azure Env Builder — az CLI ラッパー + エラー分類

AzResult: az 実行結果データクラス
RepairHint: エラー修復ヒントデータクラス
_az(): az コマンド実行
_classify_az_error(): エラーカテゴリ分類（10カテゴリ）
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class AzResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass(frozen=True)
class RepairHint:
    category: str
    retryable: bool
    summary: str
    next_actions: list[str]


def _parse_json_maybe(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_deployment_outputs(stdout: str) -> dict[str, object] | None:
    payload = _parse_json_maybe(stdout)
    if not isinstance(payload, dict):
        return None
    props = payload.get("properties")
    if not isinstance(props, dict):
        return None
    outputs = props.get("outputs")
    if not isinstance(outputs, dict):
        return None
    return outputs


def _classify_az_error(*, stdout: str, stderr: str, returncode: int) -> RepairHint:
    text = f"{stdout}\n{stderr}".lower()

    def hint(category: str, *, retryable: bool, summary: str, next_actions: list[str]) -> RepairHint:
        return RepairHint(category=category, retryable=retryable, summary=summary, next_actions=next_actions)

    if returncode == 124 or "timeout" in text:
        return hint("timeout", retryable=True, summary="az command timed out",
                    next_actions=["再実行する（時間をおいて）", "必要なら AZ_TIMEOUT_SEC を延ばす"])
    if "authorizationfailed" in text or "insufficient privileges" in text or "does not have authorization" in text:
        return hint("authorization", retryable=False, summary="insufficient Azure permissions",
                    next_actions=["権限（RBAC）を確認する", "別のサブスク/テナントで試す", "az account show でサブスクを再確認"])
    if "login" in text and ("run 'az login'" in text or "az login" in text):
        return hint("not_logged_in", retryable=False, summary="not logged in",
                    next_actions=["az login を実行する", "az account show が通るか確認する"])
    if "resourcegroupnotfound" in text or ("could not be found" in text and "resource group" in text):
        return hint("resource_group_not_found", retryable=False, summary="resource group not found",
                    next_actions=["--resource-group の指定を確認する", "az group list -o table で存在確認する"])
    if "missingsubscriptionregistration" in text or "is not registered to use namespace" in text:
        ns_match = re.search(r"namespace '([^']+)'", stderr, flags=re.IGNORECASE)
        ns = ns_match.group(1) if ns_match else "<providerNamespace>"
        return hint("provider_not_registered", retryable=False, summary=f"provider not registered: {ns}",
                    next_actions=[f"az provider register -n {ns}",
                                  f"az provider show -n {ns} --query registrationState -o tsv",
                                  "登録が完了してから再実行する"])
    if "locationnotavailableforresourcetype" in text or ("the provided location" in text and "is not available" in text):
        return hint("location_not_available", retryable=False, summary="location not available",
                    next_actions=["--location を別リージョンに変更する（例: japaneast）"])
    if "skunotavailable" in text:
        return hint("sku_not_available", retryable=False, summary="SKU not available in this region/subscription",
                    next_actions=["SKU/リージョンを変更する"])
    if "quotaexceeded" in text or "exceeding quota" in text:
        return hint("quota_exceeded", retryable=False, summary="quota exceeded",
                    next_actions=["クォータを確認する", "リージョン/SKU/サイズを下げる", "別サブスクで試す"])
    if "toomanyrequests" in text or "throttle" in text or "rate limit" in text or "temporarily" in text:
        return hint("throttling_or_transient", retryable=True, summary="transient error (throttling/temporary)",
                    next_actions=["少し待って再試行する"])
    if "bcp" in text and "bicep" in text:
        return hint("bicep_compile_error", retryable=False, summary="bicep compile/type error",
                    next_actions=["main.bicep を修正する", "deploy.log の BCP エラー行を確認する"])
    return hint("unknown", retryable=False, summary="unknown az error",
                next_actions=["deploy.log を確認して原因を特定する"])


def _resolve_az_exe() -> str:
    candidates = ("az.cmd", "az.exe", "az") if sys.platform == "win32" else ("az", "az.cmd", "az.exe")
    for c in candidates:
        found = shutil.which(c)
        if found:
            return found
    return "az"


def _az(argv: Sequence[str], *, cwd: "Path", timeout_sec: int) -> AzResult:  # type: ignore[name-defined]
    from pathlib import Path  # noqa: PLC0415

    display_argv = ["az", *argv]
    az_exe = _resolve_az_exe()
    if sys.platform == "win32" and az_exe.lower().endswith((".cmd", ".bat")):
        exec_cmd: list[str] = ["cmd.exe", "/d", "/s", "/c", az_exe, *argv]
    else:
        exec_cmd = [az_exe, *argv]

    start = time.monotonic()
    try:
        completed = subprocess.run(
            exec_cmd, cwd=str(cwd), shell=False, text=True, encoding="utf-8",
            errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_sec, check=False,
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return AzResult(argv=display_argv, returncode=127, stdout="",
                        stderr=f"az CLI not found: {exc}", duration_ms=duration_ms)
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout: str = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr: str = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return AzResult(argv=display_argv, returncode=124, stdout=stdout,
                        stderr=f"{stderr}\n[timeout] exceeded {timeout_sec}s",
                        duration_ms=duration_ms)

    duration_ms = int((time.monotonic() - start) * 1000)
    return AzResult(argv=display_argv, returncode=completed.returncode,
                    stdout=completed.stdout, stderr=completed.stderr, duration_ms=duration_ms)

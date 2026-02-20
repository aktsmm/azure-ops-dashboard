from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_LOCATION = "japaneast"
DEFAULT_MAX_ATTEMPTS = 3
AZ_TIMEOUT_SEC = 600


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
        return hint(
            "timeout",
            retryable=True,
            summary="az command timed out",
            next_actions=["再実行する（時間をおいて）", "必要なら AZ_TIMEOUT_SEC を延ばす"],
        )

    if "authorizationfailed" in text or "insufficient privileges" in text or "does not have authorization" in text:
        return hint(
            "authorization",
            retryable=False,
            summary="insufficient Azure permissions",
            next_actions=["権限（RBAC）を確認する", "別のサブスク/テナントで試す", "az account show でサブスクを再確認"],
        )

    if "login" in text and ("run 'az login'" in text or "az login" in text):
        return hint(
            "not_logged_in",
            retryable=False,
            summary="not logged in",
            next_actions=["az login を実行する", "az account show が通るか確認する"],
        )

    if "resourcegroupnotfound" in text or "could not be found" in text and "resource group" in text:
        return hint(
            "resource_group_not_found",
            retryable=False,
            summary="resource group not found",
            next_actions=["--resource-group の指定を確認する", "az group list -o table で存在確認する"],
        )

    if "missingsubscriptionregistration" in text or "is not registered to use namespace" in text:
        ns_match = re.search(r"namespace '([^']+)'", stderr, flags=re.IGNORECASE)
        ns = ns_match.group(1) if ns_match else "<providerNamespace>"
        return hint(
            "provider_not_registered",
            retryable=False,
            summary=f"provider not registered: {ns}",
            next_actions=[
                f"az provider register -n {ns}",
                f"az provider show -n {ns} --query registrationState -o tsv",
                "登録が完了してから再実行する",
            ],
        )

    if "locationnotavailableforresourcetype" in text or "the provided location" in text and "is not available" in text:
        return hint(
            "location_not_available",
            retryable=False,
            summary="location not available",
            next_actions=["--location を別リージョンに変更する（例: japaneast）"],
        )

    if "skunotavailable" in text:
        return hint(
            "sku_not_available",
            retryable=False,
            summary="SKU not available in this region/subscription",
            next_actions=["SKU/リージョンを変更する"],
        )

    if "quotaexceeded" in text or "exceeding quota" in text:
        return hint(
            "quota_exceeded",
            retryable=False,
            summary="quota exceeded",
            next_actions=["クォータを確認する", "リージョン/SKU/サイズを下げる", "別サブスクで試す"],
        )

    if "toomanyrequests" in text or "throttle" in text or "rate limit" in text or "temporarily" in text:
        return hint(
            "throttling_or_transient",
            retryable=True,
            summary="transient error (throttling/temporary)",
            next_actions=["少し待って再試行する"],
        )

    if "bcp" in text and "bicep" in text:
        return hint(
            "bicep_compile_error",
            retryable=False,
            summary="bicep compile/type error",
            next_actions=["main.bicep を修正する", "deploy.log の BCP エラー行を確認する"],
        )

    return hint(
        "unknown",
        retryable=False,
        summary="unknown az error",
        next_actions=["deploy.log を確認して原因を特定する"],
    )


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


def _timestamp_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, obj: object) -> None:
    _write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _az(argv: Sequence[str], *, cwd: Path, timeout_sec: int) -> AzResult:
    display_argv = ["az", *argv]

    if sys.platform == "win32":
        exec_cmd: str | list[str] = subprocess.list2cmdline(display_argv)
        use_shell = True
    else:
        exec_cmd = display_argv
        use_shell = False

    start = time.monotonic()
    try:
        completed = subprocess.run(
            exec_cmd,
            cwd=str(cwd),
            shell=use_shell,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False,
        )
    except FileNotFoundError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return AzResult(
            argv=display_argv,
            returncode=127,
            stdout="",
            stderr=f"az CLI not found: {exc}",
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return AzResult(
            argv=display_argv,
            returncode=124,
            stdout=stdout,
            stderr=stderr + f"\n[timeout] exceeded {timeout_sec}s",
            duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    return AzResult(
        argv=display_argv,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=duration_ms,
    )


def _append_deploy_log(log_path: Path, result: AzResult) -> None:
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


def _bicep_stub() -> str:
    return """targetScope = 'resourceGroup'

@description('Deployment location. Defaults to the resource group location.')
param location string = resourceGroup().location

var suffix = uniqueString(resourceGroup().id)
var storageAccountName = toLower('st${suffix}')

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

output storageAccountName string = storage.name
"""


def _empty_parameters_json() -> dict:
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {},
    }


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


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="azure-env-builder",
        description="Natural language -> Bicep -> az deploy (Step01).",
    )
    parser.add_argument("prompt", help="Natural language requirements")
    parser.add_argument("--subscription", help="Azure subscription id (optional)")
    parser.add_argument("--resource-group", help="Resource group name (optional)")
    parser.add_argument("--location", default=DEFAULT_LOCATION, help=f"Azure location (default: {DEFAULT_LOCATION})")
    parser.add_argument("--what-if", action="store_true", help="Run az deployment group what-if and exit")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    timestamp = _timestamp_compact()
    out_dir = Path("out") / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt = args.prompt
    location = args.location
    resource_group = args.resource_group or f"envb-{timestamp}"
    resource_group_explicit = bool(args.resource_group)

    az_plan: list[list[str]] = []

    subscription_id: str | None = args.subscription

    def write_spec() -> None:
        _write_text(
            out_dir / "spec.md",
            _build_spec_md(
                prompt=prompt,
                subscription=subscription_id,
                resource_group=resource_group,
                location=location,
                what_if=bool(args.what_if),
                az_commands=az_plan,
            ),
        )

    deploy_log_path = out_dir / "deploy.log"

    write_spec()

    if args.subscription:
        az_plan.append(["account", "set", "--subscription", args.subscription])
        res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, res)
        write_spec()
        if res.returncode != 0:
            hint = _classify_az_error(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
            _write_text(
                out_dir / "result.md",
                _build_result_md(
                    status="failed",
                    phase="account_set",
                    hint=hint,
                    az_returncode=res.returncode,
                ),
            )
            return 1

    az_plan.append(["account", "show", "--query", "id", "-o", "tsv"])
    sub_res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
    _append_deploy_log(deploy_log_path, sub_res)
    if sub_res.returncode == 0:
        subscription_id = sub_res.stdout.strip()
    else:
        hint = _classify_az_error(stdout=sub_res.stdout, stderr=sub_res.stderr, returncode=sub_res.returncode)
        _write_text(
            out_dir / "result.md",
            _build_result_md(
                status="failed",
                phase="account_show",
                hint=hint,
                az_returncode=sub_res.returncode,
            ),
        )
        return 1
    write_spec()

    _write_text(out_dir / "main.bicep", _bicep_stub())
    _write_json(out_dir / "main.parameters.json", _empty_parameters_json())

    if resource_group_explicit:
        az_plan.append(["group", "show", "--name", resource_group, "-o", "json"])
        group_res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, group_res)
        write_spec()
        if group_res.returncode != 0:
            hint = _classify_az_error(stdout=group_res.stdout, stderr=group_res.stderr, returncode=group_res.returncode)
            _write_text(
                out_dir / "result.md",
                _build_result_md(
                    status="failed",
                    phase="group_show",
                    hint=hint,
                    az_returncode=group_res.returncode,
                ),
            )
            return 1
    else:
        az_plan.append(["group", "create", "--name", resource_group, "--location", location, "-o", "json"])
        group_res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, group_res)
        write_spec()
        if group_res.returncode != 0:
            hint = _classify_az_error(stdout=group_res.stdout, stderr=group_res.stderr, returncode=group_res.returncode)
            _write_text(
                out_dir / "result.md",
                _build_result_md(
                    status="failed",
                    phase="group_create",
                    hint=hint,
                    az_returncode=group_res.returncode,
                ),
            )
            return 1

    deployment_name = f"envb-{timestamp}"

    if args.what_if:
        az_plan.append(
            [
                "deployment",
                "group",
                "what-if",
                "--name",
                deployment_name,
                "--resource-group",
                resource_group,
                "--template-file",
                "main.bicep",
                "--parameters",
                "@main.parameters.json",
                "-o",
                "json",
            ]
        )
        res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, res)
        write_spec()
        if res.returncode == 0:
            _write_text(
                out_dir / "result.md",
                _build_result_md(
                    status="what-if ok",
                    phase="what-if",
                    az_returncode=res.returncode,
                ),
            )
            return 0

        hint = _classify_az_error(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
        _write_text(
            out_dir / "result.md",
            _build_result_md(
                status="failed",
                phase="what-if",
                hint=hint,
                az_returncode=res.returncode,
            ),
        )
        return 1

    for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
        az_plan.append(
            [
                "deployment",
                "group",
                "create",
                "--name",
                deployment_name,
                "--resource-group",
                resource_group,
                "--template-file",
                "main.bicep",
                "--parameters",
                "@main.parameters.json",
                "-o",
                "json",
            ]
        )
        res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, res)
        write_spec()

        if res.returncode == 0:
            outputs = _extract_deployment_outputs(res.stdout)
            _write_text(
                out_dir / "result.md",
                _build_result_md(
                    status="deployed",
                    phase="deploy",
                    attempt=attempt,
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                    az_returncode=res.returncode,
                    outputs=outputs,
                ),
            )
            return 0

        hint = _classify_az_error(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
        if hint.retryable and attempt < DEFAULT_MAX_ATTEMPTS:
            wait_sec = min(30, 2 ** attempt)
            _write_text(
                out_dir / "result.md",
                _build_result_md(
                    status=f"retrying (wait {wait_sec}s)",
                    phase="deploy",
                    attempt=attempt,
                    max_attempts=DEFAULT_MAX_ATTEMPTS,
                    hint=hint,
                    az_returncode=res.returncode,
                ),
            )
            time.sleep(wait_sec)
            continue

        _write_text(
            out_dir / "result.md",
            _build_result_md(
                status="failed",
                phase="deploy",
                attempt=attempt,
                max_attempts=DEFAULT_MAX_ATTEMPTS,
                hint=hint,
                az_returncode=res.returncode,
            ),
        )
        return 1

    _write_text(out_dir / "result.md", "# Result\n\n- status: failed\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

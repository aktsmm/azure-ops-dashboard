"""Step 01: Azure Env Builder CLI — オーケストレーター（薄いエントリポイント）

モジュール構成:
- az_runner.py      : az CLI 実行・エラー分類
- artifact_store.py : 成果物保存・ログ追記
- bicep_generator.py: Bicep 生成・修復（Copilot SDK 統合）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from artifact_store import (
    _append_deploy_log,
    _build_result_md,
    _build_spec_md,
    _timestamp_compact,
    _write_json,
    _write_text,
)
from az_runner import _az, _classify_az_error, _extract_deployment_outputs
from bicep_generator import _bicep_stub, _empty_parameters_json, _generate_bicep_with_sdk, _repair_bicep_with_sdk

DEFAULT_LOCATION = "japaneast"
DEFAULT_MAX_ATTEMPTS = 3
AZ_TIMEOUT_SEC = 600


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
    deploy_log_path = out_dir / "deploy.log"

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

    write_spec()

    # --- subscription set ---
    if args.subscription:
        az_plan.append(["account", "set", "--subscription", args.subscription])
        res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, res)
        write_spec()
        if res.returncode != 0:
            hint = _classify_az_error(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
            _write_text(out_dir / "result.md",
                        _build_result_md(status="failed", phase="account_set", hint=hint, az_returncode=res.returncode))
            return 1

    # --- account show ---
    az_plan.append(["account", "show", "--query", "id", "-o", "tsv"])
    sub_res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
    _append_deploy_log(deploy_log_path, sub_res)
    if sub_res.returncode == 0:
        subscription_id = sub_res.stdout.strip()
    else:
        hint = _classify_az_error(stdout=sub_res.stdout, stderr=sub_res.stderr, returncode=sub_res.returncode)
        _write_text(out_dir / "result.md",
                    _build_result_md(status="failed", phase="account_show", hint=hint, az_returncode=sub_res.returncode))
        return 1
    write_spec()

    # --- Bicep 生成 ---
    _write_text(out_dir / "main.bicep", _generate_bicep_with_sdk(prompt))
    _write_json(out_dir / "main.parameters.json", _empty_parameters_json())

    # --- resource group ---
    if resource_group_explicit:
        az_plan.append(["group", "show", "--name", resource_group, "-o", "json"])
        group_res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, group_res)
        write_spec()
        if group_res.returncode != 0:
            hint = _classify_az_error(stdout=group_res.stdout, stderr=group_res.stderr, returncode=group_res.returncode)
            _write_text(out_dir / "result.md",
                        _build_result_md(status="failed", phase="group_show", hint=hint, az_returncode=group_res.returncode))
            return 1
    else:
        az_plan.append(["group", "create", "--name", resource_group, "--location", location, "-o", "json"])
        group_res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, group_res)
        write_spec()
        if group_res.returncode != 0:
            hint = _classify_az_error(stdout=group_res.stdout, stderr=group_res.stderr, returncode=group_res.returncode)
            _write_text(out_dir / "result.md",
                        _build_result_md(status="failed", phase="group_create", hint=hint, az_returncode=group_res.returncode))
            return 1

    deployment_name = f"envb-{timestamp}"

    # --- what-if ---
    if args.what_if:
        az_plan.append([
            "deployment", "group", "what-if",
            "--name", deployment_name,
            "--resource-group", resource_group,
            "--template-file", "main.bicep",
            "--parameters", "@main.parameters.json",
            "-o", "json",
        ])
        res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, res)
        write_spec()
        if res.returncode == 0:
            _write_text(out_dir / "result.md",
                        _build_result_md(status="what-if ok", phase="what-if", az_returncode=res.returncode))
            return 0
        hint = _classify_az_error(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)
        _write_text(out_dir / "result.md",
                    _build_result_md(status="failed", phase="what-if", hint=hint, az_returncode=res.returncode))
        return 1

    # --- deploy ループ（最大 DEFAULT_MAX_ATTEMPTS 回） ---
    for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
        az_plan.append([
            "deployment", "group", "create",
            "--name", deployment_name,
            "--resource-group", resource_group,
            "--template-file", "main.bicep",
            "--parameters", "@main.parameters.json",
            "-o", "json",
        ])
        res = _az(az_plan[-1], cwd=out_dir, timeout_sec=AZ_TIMEOUT_SEC)
        _append_deploy_log(deploy_log_path, res)
        write_spec()

        if res.returncode == 0:
            outputs = _extract_deployment_outputs(res.stdout)
            _write_text(out_dir / "result.md",
                        _build_result_md(status="deployed", phase="deploy", attempt=attempt,
                                         max_attempts=DEFAULT_MAX_ATTEMPTS, az_returncode=res.returncode, outputs=outputs))
            return 0

        hint = _classify_az_error(stdout=res.stdout, stderr=res.stderr, returncode=res.returncode)

        # SDK で Bicep を修復してリトライ
        if attempt < DEFAULT_MAX_ATTEMPTS and (hint.category == "bicep_compile_error" or hint.retryable):
            import time as _time  # noqa: PLC0415
            wait_sec = min(30, 2 ** attempt)
            error_detail = f"{res.stdout}\n{res.stderr}".strip()
            if hint.category in ("bicep_compile_error", "unknown"):
                bicep_path = out_dir / "main.bicep"
                current_bicep = bicep_path.read_text(encoding="utf-8")
                repaired = _repair_bicep_with_sdk(current_bicep, error_detail)
                if repaired != current_bicep:
                    _write_text(bicep_path, repaired)
                    print(f"[sdk] Bicep を修復しました（attempt {attempt}）", file=sys.stderr)
            _write_text(out_dir / "result.md",
                        _build_result_md(status=f"retrying (wait {wait_sec}s)", phase="deploy", attempt=attempt,
                                         max_attempts=DEFAULT_MAX_ATTEMPTS, hint=hint, az_returncode=res.returncode))
            _time.sleep(wait_sec)
            continue

        _write_text(out_dir / "result.md",
                    _build_result_md(status="failed", phase="deploy", attempt=attempt,
                                     max_attempts=DEFAULT_MAX_ATTEMPTS, hint=hint, az_returncode=res.returncode))
        return 1

    _write_text(out_dir / "result.md", "# Result\n\n- status: failed\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

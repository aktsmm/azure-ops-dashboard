"""Step 01: Azure Env Builder — Bicep 生成・修復

_generate_bicep_with_sdk(prompt): 自然言語 → Bicep（SDK あればGPT生成、なければstub）
_repair_bicep_with_sdk(bicep, error_text): デプロイエラー → 修復 Bicep
_bicep_stub(): Storage Account のシンプルなスタブ
_empty_parameters_json(): 空パラメータ JSON
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

# optional: Copilot SDK（U1/U2 準拠）
try:
    from copilot import CopilotClient  # type: ignore[import-not-found]
    from copilot import PermissionHandler  # type: ignore[import-not-found]
    _SDK_AVAILABLE = True
except ImportError:
    CopilotClient = None  # type: ignore[assignment,misc]
    PermissionHandler = None  # type: ignore[assignment,misc]
    _SDK_AVAILABLE = False


_BICEP_SYSTEM_PROMPT = (
    "You are an Azure Bicep expert. Generate valid Azure Bicep templates. "
    "Return ONLY the Bicep code with no markdown fences, no explanation, no comments outside the template. "
    "Start the output directly with 'targetScope' or the first Bicep statement."
)


async def _run_sdk_prompt(user_prompt: str) -> str:
    """Copilot SDK でプロンプトを送信して応答テキストを返す（asyncio.run() から呼ぶ）。"""
    if CopilotClient is None:
        raise RuntimeError("copilot SDK が未インストールです")

    collected: list[str] = []

    async with CopilotClient() as raw_client:
        await raw_client.start()
        session_config: dict[str, Any] = {
            "model": "gpt-4.1",
            "streaming": True,
            "system_prompt": _BICEP_SYSTEM_PROMPT,
        }
        if PermissionHandler is not None:
            session_config["on_permission_request"] = PermissionHandler.approve_all

        session = await raw_client.create_session(session_config)

        complete_event = asyncio.Event()

        def _handle(event: Any) -> None:
            event_type = event.type.value if hasattr(event.type, "value") else str(event.type)
            if event_type == "assistant.message_delta":
                delta = getattr(event.data, "delta_content", "")
                if delta:
                    collected.append(delta)
            elif event_type == "assistant.message":
                content = getattr(event.data, "content", "")
                if content and not collected:
                    collected.append(content)
                complete_event.set()
            elif event_type == "session.idle":
                complete_event.set()

        session.on(_handle)
        await session.send_and_wait({"prompt": user_prompt}, timeout=120)
        complete_event.set()  # 念のため

        await session.delete()

    return "".join(collected).strip()


def _generate_bicep_with_sdk(prompt: str) -> str:
    """自然言語要件から Bicep を生成。SDK 未インストール/失敗時は _bicep_stub() を返す。"""
    if not _SDK_AVAILABLE or CopilotClient is None:
        print("[sdk] SDK 未インストール → stub Bicep を使用", file=sys.stderr)
        return _bicep_stub()

    user_prompt = (
        f"Generate a complete Azure Bicep template for the following requirement:\n\n{prompt}\n\n"
        "Requirements:\n"
        "- Use targetScope = 'resourceGroup'\n"
        "- Include location parameter defaulting to resourceGroup().location\n"
        "- Add uniqueString suffix to resource names to avoid conflicts\n"
        "- Follow Azure security best practices\n"
        "Return ONLY the Bicep code."
    )
    try:
        print("[sdk] Bicep 生成中...", file=sys.stderr)
        result = asyncio.run(_run_sdk_prompt(user_prompt))
        if result and "resource" in result.lower():
            print("[sdk] ✅ Bicep 生成成功", file=sys.stderr)
            return result
        print("[sdk] ⚠️ SDK 応答が不完全 → stub Bicep を使用", file=sys.stderr)
        return _bicep_stub()
    except Exception as e:  # noqa: BLE001
        print(f"[sdk] ❌ Bicep 生成失敗: {e} → stub Bicep を使用", file=sys.stderr)
        return _bicep_stub()


def _repair_bicep_with_sdk(bicep: str, error_text: str) -> str:
    """デプロイエラーを元に Bicep を修復。失敗時は元の Bicep をそのまま返す。"""
    if not _SDK_AVAILABLE or CopilotClient is None:
        return bicep

    user_prompt = (
        "Fix the following Azure Bicep template based on the deployment error.\n\n"
        f"=== ERROR ===\n{error_text[:2000]}\n\n"
        f"=== CURRENT BICEP ===\n{bicep}\n\n"
        "Return ONLY the corrected Bicep code with no explanation."
    )
    try:
        print("[sdk] Bicep 修復中...", file=sys.stderr)
        result = asyncio.run(_run_sdk_prompt(user_prompt))
        if result and "resource" in result.lower():
            print("[sdk] ✅ Bicep 修復成功", file=sys.stderr)
            return result
        print("[sdk] ⚠️ SDK 修復応答が不完全 → 元の Bicep を使用", file=sys.stderr)
        return bicep
    except Exception as e:  # noqa: BLE001
        print(f"[sdk] ❌ Bicep 修復失敗: {e} → 元の Bicep を使用", file=sys.stderr)
        return bicep


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

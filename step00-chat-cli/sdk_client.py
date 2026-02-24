"""Step 0: SDK Chat CLI — CopilotClient ラッパー

CopilotClient のライフサイクルを管理し、
async context manager で確実なクリーンアップを保証する。
接続失敗時は指数バックオフでリトライ。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, cast

from copilot import CopilotClient
from copilot.types import CopilotClientOptions

from config import MAX_RETRY, PREFIX_ERROR, PREFIX_SYSTEM, RETRY_BACKOFF


class SDKClient:
    """CopilotClient のライフサイクル管理ラッパー。

    Usage::

        async with SDKClient() as client:
            session = await client.client.create_session({...})
            ...
        # ← 自動的に client.stop() が呼ばれる

    Voice Agent 統合時は client_options に
    github_token, log_level 等を渡す。
    """

    def __init__(self, **client_options: Any) -> None:
        self._client_options = client_options
        self._client: CopilotClient | None = None

    # --- ライフサイクル ---

    async def start(self) -> None:
        """CopilotClient を起動。指数バックオフでリトライ。"""
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRY + 1):
            try:
                opts: CopilotClientOptions | None = (
                    cast(CopilotClientOptions, self._client_options) if self._client_options else None
                )
                client = CopilotClient(options=opts)
                self._client = client
                await client.start()
                print(f"{PREFIX_SYSTEM} CopilotClient started (attempt {attempt})")
                return
            except Exception as e:  # noqa: BLE001
                last_error = e
                wait = RETRY_BACKOFF ** attempt
                print(
                    f"{PREFIX_ERROR} SDK 接続失敗 (attempt {attempt}/{MAX_RETRY}): {e}",
                    file=sys.stderr,
                )
                if attempt < MAX_RETRY:
                    print(f"  → {wait:.1f}s 後にリトライ...", file=sys.stderr)
                    await asyncio.sleep(wait)

        msg = f"SDK 接続に {MAX_RETRY} 回失敗しました: {last_error}"
        raise RuntimeError(msg)

    async def stop(self) -> None:
        """CopilotClient を停止。"""
        client = self._client
        if client is not None:
            try:
                await client.stop()
                print(f"{PREFIX_SYSTEM} CopilotClient stopped")
            except Exception as e:  # noqa: BLE001
                print(f"{PREFIX_ERROR} Client 停止時エラー: {e}", file=sys.stderr)

    # --- コンテキストマネージャ ---

    async def __aenter__(self) -> SDKClient:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # --- プロパティ ---

    @property
    def client(self) -> CopilotClient:
        """内部の CopilotClient インスタンスを返す。"""
        if self._client is None:
            msg = "SDKClient が start されていません。async with を使用してください。"
            raise RuntimeError(msg)
        return self._client

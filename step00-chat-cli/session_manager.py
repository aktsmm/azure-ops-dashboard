"""Step 0: SDK Chat CLI — Session 管理

SDK Session のライフサイクルと送受信を管理。
create_session 時に必ず on_permission_request を設定し、
v0.1.25 の deny-by-default 問題を回避する。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

from copilot import PermissionHandler

from config import DEFAULT_MODEL, DEFAULT_TIMEOUT, PREFIX_ERROR, PREFIX_SYSTEM
from event_handler import EventHandler
from sdk_client import SDKClient


class SessionManager:
    """SDK Session のライフサイクルと送受信を管理。

    Usage::

        mgr = SessionManager(client, handler)
        await mgr.create()
        reply = await mgr.send("Hello")
        await mgr.destroy()

    Voice Agent 統合時は session_config に
    skill_directories, mcpServers, system_message 等を渡す。
    """

    def __init__(
        self,
        client: SDKClient,
        event_handler: EventHandler,
        model: str = DEFAULT_MODEL,
        session_config: Optional[dict[str, Any]] = None,
    ) -> None:
        self._client = client
        self._event_handler = event_handler
        self._model = model
        self._session_config = session_config or {}
        self._session: Any = None

    # --- ライフサイクル ---

    async def create(self) -> None:
        """セッションを作成し、イベントハンドラを登録。"""
        base_config: dict[str, Any] = {
            "model": self._model,
            "streaming": True,
            "on_permission_request": PermissionHandler.approve_all,
        }
        # session_config で上書き可能（on_permission_request のカスタマイズ等）
        final_config = {**base_config, **self._session_config}

        self._session = await self._client.client.create_session(final_config)
        self._session.on(self._event_handler.handle)
        print(f"{PREFIX_SYSTEM} Session created (model: {self._model})")

    async def send(self, prompt: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
        """プロンプトを送信し、完了を待って応答テキストを返す。

        戻り値: 応答テキスト。応答なし or タイムアウト時は None。
        """
        if self._session is None:
            msg = "Session が作成されていません。create() を先に呼んでください。"
            raise RuntimeError(msg)

        try:
            reply = await self._session.send_and_wait(
                {"prompt": prompt},
                timeout=timeout,
            )
            return reply.data.content if reply else None
        except (asyncio.TimeoutError, TimeoutError):
            print(f"{PREFIX_ERROR} タイムアウト ({timeout}s)", file=sys.stderr)
            return None
        except Exception as e:  # noqa: BLE001
            print(f"{PREFIX_ERROR} 送信エラー: {e}", file=sys.stderr)
            return None

    async def destroy(self) -> None:
        """セッションを破棄。"""
        if self._session is not None:
            try:
                await self._session.destroy()
                print(f"{PREFIX_SYSTEM} Session destroyed")
            except Exception as e:  # noqa: BLE001
                print(f"{PREFIX_ERROR} Session 破棄時エラー: {e}", file=sys.stderr)
            finally:
                self._session = None

    # --- プロパティ ---

    @property
    def session(self) -> Any:
        """内部の Session インスタンスを返す（拡張・テスト用）。"""
        return self._session

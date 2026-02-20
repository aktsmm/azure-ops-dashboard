"""Step 0: SDK Chat CLI — イベントルーター

SDK セッションイベントを処理する。
コールバック注入で出力先を自由に差し替え可能:
  - Step 0 GUI: ChatWindow にストリーミング表示
    - Step 3: delta → TTS キューへ送信
"""

from __future__ import annotations

from typing import Callable, Optional

from config import (
    DIM,
    PREFIX_TOOL,
    RESET,
)


class EventHandler:
    """SDK セッションイベントを処理するルーター。

    コールバックを注入することで、出力先を自由に差し替え可能。
    - GUI モード: ChatWindow.append_delta / append_tool 等
    - CLI モード: print() でコンソール出力（デフォルト）
    - Voice Agent: delta → TTS キューへ送信
    """

    def __init__(
        self,
        on_delta: Optional[Callable[[str], None]] = None,
        on_message_complete: Optional[Callable[[str], None]] = None,
        on_tool_start: Optional[Callable[[str], None]] = None,
        on_reasoning_delta: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        on_idle: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_delta = on_delta or self._default_on_delta
        self._on_message_complete = on_message_complete or self._default_on_message_complete
        self._on_tool_start = on_tool_start or self._default_on_tool_start
        self._on_reasoning_delta = on_reasoning_delta or self._default_on_reasoning_delta
        self._on_reasoning = on_reasoning or self._default_on_reasoning
        self._on_idle = on_idle or self._default_on_idle

    # --- メインハンドラ（session.on() に渡す） ---

    def handle(self, event) -> None:  # noqa: ANN001
        """session.on() に渡すメインハンドラ。

        event.type.value で文字列分岐する。
        SDK の SessionEventType enum は将来変更される可能性があるため、
        文字列比較で吸収する。
        """
        event_type = event.type.value if hasattr(event.type, "value") else str(event.type)

        if event_type == "assistant.message_delta":
            delta = getattr(event.data, "delta_content", "")
            if delta:
                self._on_delta(delta)

        elif event_type == "assistant.message":
            content = getattr(event.data, "content", "")
            self._on_message_complete(content)

        elif event_type == "assistant.reasoning_delta":
            delta = getattr(event.data, "delta_content", "")
            if delta:
                self._on_reasoning_delta(delta)

        elif event_type == "assistant.reasoning":
            content = getattr(event.data, "content", "")
            self._on_reasoning(content)

        elif event_type == "tool.execution_start":
            tool_name = getattr(event.data, "tool_name", "unknown")
            self._on_tool_start(tool_name)

        elif event_type == "session.idle":
            self._on_idle()

    # --- デフォルトコールバック（CLI フォールバック） ---

    @staticmethod
    def _default_on_delta(delta: str) -> None:
        print(delta, end="", flush=True)

    @staticmethod
    def _default_on_message_complete(content: str) -> None:  # noqa: ARG004
        print()

    @staticmethod
    def _default_on_tool_start(tool_name: str) -> None:
        print(f"{PREFIX_TOOL} {tool_name}")

    @staticmethod
    def _default_on_reasoning_delta(delta: str) -> None:
        print(f"{DIM}{delta}{RESET}", end="", flush=True)

    @staticmethod
    def _default_on_reasoning(content: str) -> None:  # noqa: ARG004
        print()

    @staticmethod
    def _default_on_idle() -> None:
        pass

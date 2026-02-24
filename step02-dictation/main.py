"""Step 2: ディクテーションツール

Azure Speech STT + pyautogui で音声→テキスト入力。
SDK は使わない（Voice Agent の音声レイヤー先行実装）。

この Step はオプション依存（extras: speech）を使うため、依存未導入でも
import 時に落ちないように遅延 import（動的 import）にしている。

ホットキー: Ctrl+Shift+D で STT ON/OFF トグル（pynput が必要）
"""

from __future__ import annotations

import importlib
import os
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

# optional: pynput によるグローバルホットキー（U1 準拠）
try:
    from pynput import keyboard as _pynput_keyboard  # type: ignore[import-not-found]
    _PYNPUT_AVAILABLE = True
except ImportError:
    _pynput_keyboard = None  # type: ignore[assignment]
    _PYNPUT_AVAILABLE = False


def _install_hint() -> str:
    return (
        "必要な依存パッケージが見つかりません。\n"
        "この Step を使う場合は extras を入れてください:\n"
        "  uv pip install -e \".[speech]\"\n"
    )


def _import_optional(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(_install_hint()) from exc


def create_recognizer(speechsdk: ModuleType):
    """Azure Speech 認識エンジンを作成"""
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        raise RuntimeError(
            "AZURE Speech の環境変数が未設定です。\n"
            "- AZURE_SPEECH_KEY\n"
            "- AZURE_SPEECH_REGION\n"
            "を設定してから再実行してください。"
        )

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.speech_recognition_language = "ja-JP"

    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    return speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)


def on_recognized(evt: Any, *, typewrite: Callable[..., Any]) -> None:
    """音声認識結果をアクティブウィンドウに入力"""
    text = getattr(getattr(evt, "result", None), "text", "")
    if isinstance(text, str) and text.strip():
        print(f"🎤 {text}")
        typewrite(text, interval=0.02)


class HotkeyToggle:
    """Ctrl+Shift+D でディクテーションを ON/OFF するグローバルホットキーマネージャ。

    pynput が未インストールの場合は何もしない（Ctrl+C のみ）。
    """

    def __init__(self, recognizer: Any) -> None:
        self._recognizer = recognizer
        self._is_recognizing = False
        self._lock = threading.Lock()
        self._pressed: set = set()
        self._listener: Optional[Any] = None

    def _toggle(self) -> None:
        with self._lock:
            if self._is_recognizing:
                print("⏹️  ディクテーション停止（ホットキー）")
                self._recognizer.stop_continuous_recognition()
                self._is_recognizing = False
            else:
                print("▶️  ディクテーション開始（ホットキー）")
                self._recognizer.start_continuous_recognition()
                self._is_recognizing = True

    def _on_press(self, key: Any) -> None:
        if not _PYNPUT_AVAILABLE:
            return
        # キーを正規化（文字キーは小文字 str として追加）
        if hasattr(key, "char") and key.char:
            self._pressed.add(key.char.lower())
        else:
            self._pressed.add(key)

        # Ctrl+Shift+D 判定
        ctrl = (
            _pynput_keyboard.Key.ctrl_l in self._pressed
            or _pynput_keyboard.Key.ctrl_r in self._pressed
        )
        shift = (
            _pynput_keyboard.Key.shift in self._pressed
            or _pynput_keyboard.Key.shift_r in self._pressed
        )
        d_key = "d" in self._pressed
        if ctrl and shift and d_key:
            self._pressed.clear()  # デバウンス用にクリア
            self._toggle()

    def _on_release(self, key: Any) -> None:
        if hasattr(key, "char") and key.char:
            self._pressed.discard(key.char.lower())
        else:
            self._pressed.discard(key)

    def start(self) -> None:
        """ホットキーリスナを起動（デーモンスレッドで実行）。"""
        if not _PYNPUT_AVAILABLE or _pynput_keyboard is None:
            return
        self._listener = _pynput_keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True  # type: ignore[attr-defined]
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    @property
    def is_recognizing(self) -> bool:
        with self._lock:
            return self._is_recognizing


def main() -> None:
    print("🎙️ ディクテーションツール起動")
    print("   話しかけるとアクティブウィンドウにテキスト入力されます")
    if _PYNPUT_AVAILABLE:
        print("   Ctrl+Shift+D で STT ON/OFF トグル")
    else:
        print("   ⚠️  pynput 未インストール — ホットキー無効 (`uv pip install pynput` で有効化)")
    print("   Ctrl+C で終了")
    print()

    speechsdk = _import_optional("azure.cognitiveservices.speech")
    pyautogui = _import_optional("pyautogui")

    recognizer = create_recognizer(speechsdk)
    recognizer.recognized.connect(lambda evt: on_recognized(evt, typewrite=pyautogui.typewrite))

    toggle = HotkeyToggle(recognizer)

    if _PYNPUT_AVAILABLE:
        # ホットキーモード: 最初は停止状態で待機
        toggle.start()
        print("⏸️  待機中... Ctrl+Shift+D で開始してください")
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n👋 停止中...")
            if toggle.is_recognizing:
                recognizer.stop_continuous_recognition()
            toggle.stop()
            print("✅ 停止完了")
    else:
        # フォールバック: 即開始して Ctrl+C で停止
        recognizer.start_continuous_recognition()
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n👋 停止中...")
            recognizer.stop_continuous_recognition()
            print("✅ 停止完了")


if __name__ == "__main__":
    main()

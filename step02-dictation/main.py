"""Step 2: ディクテーションツール

Azure Speech STT + pyautogui で音声→テキスト入力。
SDK は使わない（Voice Agent の音声レイヤー先行実装）。

この Step はオプション依存（extras: speech）を使うため、依存未導入でも
import 時に落ちないように遅延 import（動的 import）にしている。
"""

from __future__ import annotations

import importlib
import os
import time
from types import ModuleType
from typing import Any, Callable


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


def main() -> None:
    print("🎙️ ディクテーションツール起動")
    print("   話しかけるとアクティブウィンドウにテキスト入力されます")
    print("   Ctrl+C で終了")
    print()

    speechsdk = _import_optional("azure.cognitiveservices.speech")
    pyautogui = _import_optional("pyautogui")

    recognizer = create_recognizer(speechsdk)
    recognizer.recognized.connect(lambda evt: on_recognized(evt, typewrite=pyautogui.typewrite))
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

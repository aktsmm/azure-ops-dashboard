"""
Step 2: ディクテーションツール
Azure Speech STT + pyautogui で音声→テキスト入力。
SDK は使わない（Voice Agent の音声レイヤー先行実装）。
"""
import os
import pyautogui
import azure.cognitiveservices.speech as speechsdk


def create_recognizer():
    """Azure Speech 認識エンジンを作成"""
    speech_config = speechsdk.SpeechConfig(
        subscription=os.environ["AZURE_SPEECH_KEY"],
        region=os.environ["AZURE_SPEECH_REGION"]
    )
    speech_config.speech_recognition_language = "ja-JP"

    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    return speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config
    )


def on_recognized(evt):
    """音声認識結果をアクティブウィンドウに入力"""
    text = evt.result.text
    if text.strip():
        print(f"🎤 {text}")
        pyautogui.typewrite(text, interval=0.02)


def main():
    print("🎙️ ディクテーションツール起動")
    print("   話しかけるとアクティブウィンドウにテキスト入力されます")
    print("   Ctrl+C で終了")
    print()

    recognizer = create_recognizer()
    recognizer.recognized.connect(on_recognized)
    recognizer.start_continuous_recognition()

    try:
        import time
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n👋 停止中...")
        recognizer.stop_continuous_recognition()
        print("✅ 停止完了")


if __name__ == "__main__":
    main()

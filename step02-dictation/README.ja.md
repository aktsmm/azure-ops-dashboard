English: [README.md](README.md)

# Step 02: ディクテーションツール

Azure Speech STT + `pyautogui` で、音声を **アクティブウィンドウ** へテキスト入力します。
（SDK は使わず、Voice Agent 統合に向けた音声レイヤーの先行実装です）

## 前提

- Windows
- Python 3.11+
- `uv` が利用できること
- 環境変数
  - `AZURE_SPEECH_KEY`
  - `AZURE_SPEECH_REGION`

※ 認識言語は現状 `ja-JP` 固定です（[main.py](main.py)）。

## セットアップ（共通）

ワークスペースルートで:

```powershell
uv venv
uv pip install -e .
```

## 実行

```powershell
cd .\step02-dictation
uv run python .\main.py
```

## 停止

- `Ctrl+C`

## 注意

- 入力先は「現在フォーカスされているウィンドウ」です（意図しない場所に入力される可能性があります）。

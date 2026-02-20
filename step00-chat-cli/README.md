# Step 0: SDK Chat CLI

GitHub Copilot SDK（Python）の動作確認用チャットアプリ。
**System Tray 常駐 + Alt ダブルタップでポップアップ**する GUI 形式。
Voice Agent（Step 3）の SDK レイヤー + GUI レイヤー基盤として再利用できる設計。

## 前提条件

- Python 3.11+
- `copilot` CLI インストール済み & `copilot auth login` 完了
- Windows（System Tray + グローバルホットキー）

## セットアップ

```bash
# ワークスペースルートで
uv venv
uv pip install -e .
```

## 実行

```bash
cd step00-chat-cli
uv run python main.py
```

## 使い方

1. 起動すると **System Tray にアイコンが表示**され、SDK に接続
2. **Alt キーを素早く2回押す** → チャットウィンドウがポップアップ
3. テキストを入力して **Enter** で送信 → ストリーミングで応答表示
4. **Escape** でウィンドウを非表示（会話履歴は保持）
5. 再度 Alt×2 でウィンドウを再表示
6. トレイアイコン右クリック → 「Exit」でアプリ終了

- SDK 接続に失敗した場合は、右クリック → 「Reconnect」で再接続できます

## ホットキーの変更

`settings.json` を編集してホットキーを変更できます：

※ 型不一致や範囲外などの **不正な値は無視**され、デフォルト値が使用されます。

```json
{
  "hotkey_key": "alt",
  "hotkey_interval": 0.35,
  "model": "gpt-4.1"
}
```

| 設定              | 説明                       | デフォルト  |
| ----------------- | -------------------------- | ----------- |
| `hotkey_key`      | ダブルタップで検出するキー | `"alt"`     |
| `hotkey_interval` | ダブルタップ判定間隔（秒） | `0.35`      |
| `model`           | 使用する AI モデル         | `"gpt-4.1"` |
| `window_width`    | ウィンドウ幅               | `500`       |
| `window_height`   | ウィンドウ高さ             | `600`       |
| `font_size`       | フォントサイズ             | `11`        |

## ファイル構成

| ファイル             | 責務                                             |
| -------------------- | ------------------------------------------------ |
| `main.py`            | エントリポイント（スレッド統合・App クラス）     |
| `chat_window.py`     | tkinter チャットウィンドウ（ストリーミング表示） |
| `tray_app.py`        | pystray System Tray 管理                         |
| `sdk_client.py`      | CopilotClient ラッパー（接続管理・リトライ）     |
| `session_manager.py` | Session 作成・イベント購読・送受信               |
| `event_handler.py`   | イベントルーター（コールバック注入対応）         |
| `config.py`          | 設定定数 + settings.json 読み込み                |
| `settings.json`      | ユーザー設定（ホットキー・モデル等）             |
| `DESIGN.md`          | 基本設計 + 詳細設計                              |

## Voice Agent 統合時の拡張ポイント

| モジュール       | 差し替え内容                                                 |
| ---------------- | ------------------------------------------------------------ |
| `EventHandler`   | `on_delta` を TTS キューへの送信に差し替え                   |
| `SessionManager` | `session_config` に `skill_directories`, `mcpServers` を注入 |
| `ChatWindow`     | 音声入力ボタン追加 / ホットキーで音声モード切替              |
| `TrayApp`        | Skills 更新・設定・ログ表示等のメニュー追加                  |

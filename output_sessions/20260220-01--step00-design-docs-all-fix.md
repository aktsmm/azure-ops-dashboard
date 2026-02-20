---
type: design
exported_at: 2026-02-20T06:42:28
tools_used:
  [
    read_file,
    apply_patch,
    create_file,
    create_directory,
    grep_search,
    list_dir,
    file_search,
    run_in_terminal,
  ]
outcome_status: success
---

# Step00 安定化 + 設計書整備（Step命名統一含む）

## Summary

Step00のGUI常駐チャットを安定化しつつ、Step00/01/02/03のドキュメントをフォルダ命名に合わせて整備して、次の実装（特にStep01）へ進める状態にしました。

## Timeline

### Phase 1 - Step00レビューと安定化修正

- 実装レビューで「送信失敗/SDK未接続時に入力が戻らない」などの実害を修正
- タイムアウト例外の取りこぼし・destroy後のセッション参照の事故を抑止
- GUIシャットダウン中にSDKイベントが来ても落ちないようにガード
- Modified: [step00-chat-cli/main.py](../step00-chat-cli/main.py)
- Modified: [step00-chat-cli/session_manager.py](../step00-chat-cli/session_manager.py)
- Modified: [step00-chat-cli/chat_window.py](../step00-chat-cli/chat_window.py)

### Phase 2 - settings.jsonバリデーション導入

- settings.jsonの上書きに型/範囲チェックを追加し、不正値は無視してデフォルト維持
- Modified: [step00-chat-cli/config.py](../step00-chat-cli/config.py)
- Modified: [step00-chat-cli/README.md](../step00-chat-cli/README.md)

### Phase 3 - 接続状態UIと再接続（Tray）

- SDK接続完了まで入力欄/Sendを無効化し、ステータス表示（Connecting/Connected/Error）を追加
- TrayにReconnectを追加し、セッション/クライアントを作り直して再接続できるようにした
- Modified: [step00-chat-cli/chat_window.py](../step00-chat-cli/chat_window.py)
- Modified: [step00-chat-cli/main.py](../step00-chat-cli/main.py)
- Modified: [step00-chat-cli/tray_app.py](../step00-chat-cli/tray_app.py)
- Modified: [step00-chat-cli/README.md](../step00-chat-cli/README.md)

### Phase 4 - Step命名（step00/01/02/03）に合わせたドキュメント整備

- ロードマップ表記をフォルダ構成に合わせて「Step0/1/2/3」に統一（0.5表記を排除）
- Step00設計書を現行実装（Reconnect/Status/設定上書き方針）に追従させた
- Step01に最小の設計書を追加し、実装開始できる粒度にした
- Step02にREADMEを追加し、Step番号表記を統一
- Step03 READMEに「設計書→実装配置」の対応を追加
- Modified: [README.md](../README.md)
- Modified: [step00-chat-cli/DESIGN.md](../step00-chat-cli/DESIGN.md)
- Modified: [step01-env-builder/DESIGN.md](../step01-env-builder/DESIGN.md)
- Modified: [step01-env-builder/README.md](../step01-env-builder/README.md)
- Modified: [step02-dictation/main.py](../step02-dictation/main.py)
- Modified: [step02-dictation/README.md](../step02-dictation/README.md)
- Modified: [step03-voice-agent/README.md](../step03-voice-agent/README.md)
- Modified: [step00-chat-cli/event_handler.py](../step00-chat-cli/event_handler.py)

## Key Learnings

- GUI（tkinter）とSDK（asyncioスレッド）を分離した場合、エラー/タイムアウト時にUIが「送信中」のまま戻らない事故が一番起きやすいので、失敗時も確実にUI復帰する経路が必要。
- `settings.json` の上書きは便利だが、不正値を許すと起動不能になりやすいので「無視してデフォルト維持」が安全。
- デモ/運用で詰まるのはSDK接続の揺れなので、TrayからのReconnectは費用対効果が高い。
- フォルダ命名（step00/01/02/03）とドキュメントのStep表記がズレると、実装フェーズで確実に迷子になる。

## Commands & Code

```powershell
# exported_at 取得
Get-Date -Format "yyyy-MM-ddTHH:mm:ss"

# 構文チェック
python -m py_compile (Get-ChildItem .\step00-chat-cli -Filter *.py | ForEach-Object FullName)
python -m py_compile (Get-ChildItem .\step02-dictation -Filter *.py | ForEach-Object FullName)
```

## References

- [Voice-first Enterprise Copilot 設計](../docs/design.md)
- [Copilot SDK 技術リファレンス](../docs/tech-reference.md)
- [Step00 設計](../step00-chat-cli/DESIGN.md)
- [Step01 設計](../step01-env-builder/DESIGN.md)

## Next Steps

- [ ] Step01の `main.py` 骨格を作成（引数、out/保存、az実行ラッパ）
- [ ] Step01のデプロイ先（subscription / resource group / location）を確定
- [ ] Step01で「最小デプロイ成功」→ 次に「失敗修復ループ」まで通す
- [ ] Step03の `src/` を作り、Step00/01/02の移植先（モジュール境界）を確定

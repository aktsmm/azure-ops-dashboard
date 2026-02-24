# 🚀 Challenge Dashboard

> Last Updated: **2026-02-24 (Session 09)** | Deadline: **2026-03-07 22:00 PST** (FY26 SDK Enterprise Challenge) | 残り **11 日**

---

## 📊 全体進捗

| Track                            | ステータス  | 進捗 | 備考                                                                          |
| -------------------------------- | ----------- | ---- | ----------------------------------------------------------------------------- |
| Step 0: SDK Chat CLI             | ✅ 完了     | 100% | トレイ常駐 + Alt×2 ポップアップ                                               |
| Step 1: Env Builder CLI          | 🔧 実装中   | 75%  | az動作○、SDK Bicep生成・修復ループ実装済み                                    |
| Step 2: Dictation                | 🟡 最小完成 | 80%  | STT+pyautogui動作、ホットキー未                                               |
| Step 3: Voice Agent 統合（本命） | 🔧 実装中   | 40%  | src/app.py 骨格・SDK・Speech モジュール実装済み、app.py 統合済み              |
| Azure Ops Dashboard              | ✅ 完成     | 100% | レビュー修正済（スレッド安全/タイムアウト/API整理）・統合レポート・テスト39件 |
| 提出物準備（docs/video/deck）    | ✅ 提出済   | 100% | 2/24 提出完了（PPTX 2スライド + 動画 + SDK Feedback）                         |

**🎯 総合: 約 70%** ／ **本命 (Voice Agent) 単体: 70%**

---

## 🏃 現スプリント（2/24 週）

### NOW ― 今日やること

- 👁 [code-review] Azure Ops Dashboard tests.py 品質ゲートテスト追加・ import 整理（43 tests）
- [x] Step1: 自然言語→Bicep 生成（Copilot SDK 呼び出し）実装
- [x] Step3: `src/app.py` 骨格（トレイ常駐 + モード切替）
- 🔨 [hard-builder] Step3 src/sdk/ + src/speech/ 移植・app.py 統合実装済み

### NEXT ― 今週中

- [x] Step1: 失敗修復ループ（エラー分類→SDK 修正→再デプロイ）実装
- [ ] Step3: `src/sdk/` Step0 移植
- [ ] Step3: `src/speech/` Step2 移植（STT/TTS 疎通確認）
- [ ] 提出物: README / デモシナリオ骨格
- [ ] **WA Assessment チームへアウトリーチメール送信**（[docs/wa-assessment-outreach-email.md](docs/wa-assessment-outreach-email.md)）

---

## ✅ 全タスク詳細

### Step 0: SDK Chat CLI ✅

- [x] CopilotClient → create_session → send_and_wait 動作確認
- [x] System Tray 常駐 + Alt×2 ポップアップ
- [x] ストリーミング表示
- [x] settings.json でホットキー/モデル変更対応

---

### Step 1: Azure Env Builder CLI 🔧

- [x] argparse CLI 骨格（prompt / --rg / --location / --what-if）
- [x] az CLI ラッパー（stdout / stderr / タイムアウト 600s）
- [x] エラー分類（`_classify_az_error` — 10カテゴリ）
- [x] out/\<timestamp\>/ 成果物保存（spec.md / main.bicep / deploy.log / result.md）
- [x] what-if / 実デプロイ実行（Storage 実デプロイ成功ログあり）
- [x] 自然言語→Bicep 生成（Copilot SDK 呼び出し） ← ★最優先
- [x] 失敗修復ループ（SDK でエラー解析→Bicep 修正→再デプロイ） ← ★最優先
- [x] モジュール分割（az_runner / artifact_store / bicep_generator — main.py 174行に圧縮）

---

### Step 2: Dictation 🟡

- [x] Azure Speech STT + pyautogui でアクティブウィンドウへ入力
- [x] Ctrl+C で停止
- [x] Ctrl+Shift+D ホットキーで ON/OFF 切替（pynput + HotkeyToggle クラス）

---

### Step 3: Voice-first Enterprise Copilot ⬜（本命）

- [x] `src/app.py` ― トレイ常駐 + モード切替（dictation / agent）
- [x] `src/sdk/` ― Step0 Copilot SDK ラッパー移植
- [x] `src/speech/` ― Step2 Azure Speech STT/TTS 移植
- [x] `src/skills/` ― SkillManager 実装（git pull + skill_directories 注入、3スキル検出確認）
- [x] `src/tools/` ― ToolApproval 実装（SAFE / INTERACTIVE / ALLOW_ALL モード、onPreToolUse フック）
- [x] Work IQ MCP 連携（MCPConfig クラス、GitHub MCP + Work IQ MCP設定注入）
- [x] `src/app.py` 完全統合（skills/tools/mcp → session_config に自動注入）
- [ ] デモシナリオ通し動作確認（Azure Speech キー設定後）

---

### Azure Ops Dashboard ✅（完成・レビュー修正済）

- [x] tkinter GUI（inventory / network / security / cost 4ビュー）
- [x] Draw.io .drawio 生成（inventory / network）
- [x] Security / Cost AI レポート自動生成
- [x] テンプレートカスタマイズ（4種 + セクション ON/OFF）
- [x] 追加指示の保存・呼び出し
- [x] Word / PDF エクスポート
- [x] i18n（日本語/英語ランタイム切替）
- [x] PyInstaller exe 化（onedir / onefile 両対応）
- [x] bundled + user override テンプレート（%APPDATA%）
- [x] Service Principal ログイン対応（Secret 非保存）
- [x] 収集スクリプト（collect-azure-env.ps1）
- [x] ユニットテスト 39 件（Azure CLI / SDK 接続不要）
- [x] 差分レポート（-diff.md）の UI 連携強化
- [x] network view レイアウト改善（PublicIP / NIC / Subnet 固定並び）
- [x] スレッド安全性改善（Lock 整理・Thread 起動遅延・cancel 伝搬）
- [x] タイムアウト改善（drawio 60min / report 10min / 個別 timeout_s）
- [x] API 整理（run_az_command ラッパー・run_integrated_report 公開）
- [x] 複数ビュー統合レポート自動生成

---

### 提出物準備 ✅（提出済 2026-02-24）

- [x] プロジェクト概要（150 words max）
- [x] デモ動画（en/ja、OneDrive Stream）
- [x] README（問題→解決策、アーキテクチャ図、セットアップ）
- [x] プレゼンデック（AzureOpsDashboard_TatsumiYamamoto.pptx、2スライド）
- [x] `AGENTS.md` 最終確認
- [x] `mcp.json` 作成
- [x] `/src` or `/app` 配置確認（flat layout、README で説明）
- [x] ボーナス: SDK プロダクトフィードバック投稿（Teams + スクショ済）

---

## 🗓 マイルストーン

| 日付    | タスク                                    | 状態      |
| ------- | ----------------------------------------- | --------- |
| 2/23    | **Step1 SDK統合（Bicep生成）完成目標**    | ⬜        |
| 2/26    | Office Hours #2                           | ⬜        |
| 3/1     | **Step3 Voice Agent MVP**                 | ⬜        |
| 3/5     | Office Hours #3                           | ⬜        |
| 3/6     | デモ動画撮影 + デック作成                 | ⬜        |
| **3/7** | **🏁 提出期限 22:00 PST (3/8 15:00 JST)** | ✅ 提出済 |

---

## ⚠️ リスク・ブロッカー

| リスク                             | 影響度  | 対策                                      |
| ---------------------------------- | ------- | ----------------------------------------- |
| Step3 統合が 0% のまま進む         | 🔴 高   | 2/24 から先行着手。Step1 完成後すぐ移行   |
| Azure Speech キー/リージョン未設定 | 🟡 中   | 早めに `AZURE_SPEECH_KEY` 確認・設定      |
| 提出物（Azure Ops Dashboard）      | 🟢 解消 | 2/24 に提出完了（動画/デック/README）     |
| Step1 SDK統合が長引く              | 🟠 中   | 2/24 中に方針決定。長引けば保険提出に切替 |

---

## 🔄 このファイルの更新方法

```
Copilot Chat で:  update-dashboard を呼ぶ（@dashboard-updater）
または `.github/prompts/update-dashboard.prompt.md` をチャットに送信
```

> **ルール**: 実際に動くコードがある場合のみ ✅ / [x] にする。根拠なく進捗率を上げない。

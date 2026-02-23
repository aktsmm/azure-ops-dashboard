# 🚀 Challenge Dashboard

> Last Updated: **2026-02-23** | Deadline: **2026-03-07 22:00 PST** | 残り **13日**

---

## 📊 全体進捗

| Track                            | ステータス  | 進捗 | 備考                                           |
| -------------------------------- | ----------- | ---- | ---------------------------------------------- |
| Step 0: SDK Chat CLI             | ✅ 完了     | 100% | トレイ常駐 + Alt×2 ポップアップ                |
| Step 1: Env Builder CLI          | 🔧 実装中   | 45%  | az動作○、SDK統合・修復ループ未                 |
| Step 2: Dictation                | 🟡 最小完成 | 80%  | STT+pyautogui動作、ホットキー未                |
| Step 3: Voice Agent 統合（本命） | ⬜ 未着手   | 0%   | src/ は空                                      |
| Azure Ops Dashboard              | ✅ 完成     | 100% | GUI・i18n・exe・テスト済・diff UI・Subnet view |
| 提出物準備（docs/video/deck）    | ⬜ 未着手   | 0%   | 3/6以降着手予定                                |

**🎯 総合: 約 40%** ／ **本命 (Voice Agent) 単体: 25%**

---

## 🏃 現スプリント（2/23 週）

### NOW ― 今日やること

- [ ] Step1: 自然言語→Bicep 生成（Copilot SDK 呼び出し）実装
- [ ] Step1: 失敗修復ループ（エラー分類→SDK 修正→再デプロイ）実装

### NEXT ― 今週中

- [ ] Step3: `src/app.py` 骨格（トレイ常駐 + モード切替）
- [ ] Step3: `src/sdk/` Step0 移植
- [ ] Step3: `src/speech/` Step2 移植（STT/TTS 疎通確認）

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
- [ ] **自然言語→Bicep 生成（Copilot SDK 呼び出し）** ← ★最優先
- [ ] **失敗修復ループ（SDK でエラー解析→Bicep 修正→再デプロイ）** ← ★最優先
- [ ] モジュール分割（orchestrator / bicep_generator / artifact_store）

---

### Step 2: Dictation 🟡

- [x] Azure Speech STT + pyautogui でアクティブウィンドウへ入力
- [x] Ctrl+C で停止
- [ ] ホットキーで ON/OFF 切替（Step3 統合に向けて）

---

### Step 3: Voice-first Enterprise Copilot ⬜（本命）

- [ ] `src/app.py` ― トレイ常駐 + モード切替（dictation / agent）
- [ ] `src/sdk/` ― Step0 Copilot SDK ラッパー移植
- [ ] `src/speech/` ― Step2 Azure Speech STT/TTS 移植
- [ ] `src/skills/` ― Agent-Skills 自動同期（git pull + skill_directories 注入）
- [ ] `src/tools/` ― onPreToolUse（許可/拒否/確認）
- [ ] Work IQ MCP 連携
- [ ] デモシナリオ通し動作確認

---

### Azure Ops Dashboard ✅（ほぼ完成）

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
- [x] ユニットテスト 20 件（Azure CLI / SDK 接続不要）
- [x] 差分レポート（-diff.md）の UI 連携強化
- [x] network view レイアウト改善（PublicIP / NIC / Subnet 固定並び）

---

### 提出物準備 ⬜

- [ ] プロジェクト概要（150 words max）
- [ ] デモ動画（3分以内）
- [ ] README（問題→解決策、アーキテクチャ図、セットアップ）
- [ ] プレゼンデック（.pptx）
- [ ] `AGENTS.md` 最終確認
- [ ] `mcp.json` 作成
- [ ] `/src` or `/app` 配置確認（審査要件）
- [ ] ボーナス: SDK プロダクトフィードバック投稿

---

## 🗓 マイルストーン

| 日付    | タスク                                    | 状態 |
| ------- | ----------------------------------------- | ---- |
| 2/23    | **Step1 SDK統合（Bicep生成）完成目標**    | 🔧   |
| 2/26    | Office Hours #2                           | ⬜   |
| 3/1     | **Step3 Voice Agent MVP**                 | ⬜   |
| 3/5     | Office Hours #3                           | ⬜   |
| 3/6     | デモ動画撮影 + デック作成                 | ⬜   |
| **3/7** | **🏁 提出期限 22:00 PST (3/8 15:00 JST)** | ⬜   |

---

## ⚠️ リスク・ブロッカー

| リスク                             | 影響度 | 対策                                      |
| ---------------------------------- | ------ | ----------------------------------------- |
| Step3 統合が 0% のまま進む         | 🔴 高  | 2/24 から先行着手。Step1 完成後すぐ移行   |
| Azure Speech キー/リージョン未設定 | 🟡 中  | 早めに `AZURE_SPEECH_KEY` 確認・設定      |
| デモ動画/デック未着手              | 🟡 中  | 3/5 以降に集中。シナリオは今から固める    |
| Step1 SDK統合が長引く              | 🟠 中  | 2/24 中に方針決定。長引けば保険提出に切替 |

---

## 🔄 このファイルの更新方法

```
Copilot Chat で:  update-dashboard を呼ぶ（@dashboard-updater）
または `.github/prompts/update-dashboard.prompt.md` をチャットに送信
```

> **ルール**: 実際に動くコードがある場合のみ ✅ / [x] にする。根拠なく進捗率を上げない。

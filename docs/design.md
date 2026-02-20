# Voice-first Enterprise Copilot — 詳細設計

> 作成日: 2026-02-20  
> 推定スコア: **131/135**  
> ステータス: 🏆 本命

---

## コンセプト

**「声で何でもできる」デスクトップ常駐エージェント**

音声I/Oレイヤー + Copilot SDK + Agent Skills 自動同期 で、話しかけるだけで
Azure 環境構築、PPTX生成、Web調査、顧客レポート、コード操作、何でもできる。
スキルは外部リポジトリ（aktsmm/Agent-Skills）から自動取得され、
新スキルを push するだけで Voice Agent の能力が自動拡張される。

### SDK の必然性

> 「VS Code を開かずに、声で話しかけるだけで Copilot の全能力を使える。
> 開発者だけでなく、営業も経理も人事も使える。
> これは VS Code Extension では実現不可能で、SDK だからこそ可能。」

| やりたいこと                 | スクリプト | VS Code Extension | SDK |
| ---------------------------- | ---------- | ----------------- | --- |
| 音声 I/O                     | ❌         | ❌                | ✅  |
| 非エンジニアが使える         | △          | ❌（VS Code必須） | ✅  |
| 24/7 自動実行                | ✅         | ❌                | ✅  |
| カスタム I/O                 | △          | ❌                | ✅  |
| 自律ループ（計画→実行→修正） | ❌         | △                 | ✅  |

---

## できること一覧

```
🎤 ディクテーション      「メモ取って」→ テキスト入力
💬 自由対話              「これどう思う？」→ 考えて音声回答
📧 Work IQ 連携         「今日の会議は？」→ メール/予定を読み上げ
📊 M365 情報            「Teamsの新機能は？」→ ロードマップ検索
🔧 Azure 操作           「検証環境作って」→ Bicep デプロイ（azure-env-builder スキル）
📑 PPTX 生成            「会議資料まとめて」→ PowerPoint 自動生成（powerpoint-automation スキル）
🌐 Web 操作             「このページ調べて」→ Playwright 自動操作（browser-max-automation スキル）
🖼️ 図面生成             「アーキテクチャ図描いて」→ draw.io 生成（drawio-diagram-forge スキル）
👁️ OCR                 「この画像の文字読んで」→ OCR（ocr-super-surya スキル）
💻 コード操作            「このPR見て」→ GitHub MCP でレビュー
🔄 スキル更新           「スキル更新して」→ Agent-Skills リポから最新同期
```

---

## アーキテクチャ

```
┌──────────────────────────────────────────────────────────────────┐
│              Voice-first Enterprise Copilot                      │
│              (Python Desktop App / System Tray)                  │
│                                                                  │
│  [マイク] ── Azure Speech STT (continuous) ──→ [Router]          │
│                                                  │               │
│                                      ┌───────────┴──────────┐    │
│                                   ホットキー            それ以外  │
│                                   Ctrl+Shift+D         (全部SDK) │
│                                      │                    │      │
│                                 ディクテーション    Copilot SDK   │
│                                 (直接ペースト)      Session       │
│                                                        │         │
│                              ┌─────────────────────────┼──────┐  │
│                              │            │            │      │  │
│                          MCP Servers   Skills      Custom   Built│
│                              │         (自動同期)    Tools    -in │
│                         ┌────┼────┐       │          │      │    │
│                         │    │    │       │          │      │    │
│                       Work  M365  GH   azure-env   Bing  ファイル│
│                       IQ   MCP   MCP   pptx-auto   検索  Git    │
│                                        browser              操作 │
│                                        drawio                    │
│                                        ocr                       │
│                                        code-simp                 │
│                              └─────────────────────────┼──────┘  │
│                                                        │         │
│                                              assistant.message   │
│                                              _delta              │
│                                                        │         │
│                                                  Azure Speech    │
│                                                  TTS (streaming) │
│                                                        │         │
│                                                    [スピーカー]   │
└──────────────────────────────────────────────────────────────────┘

                    ┌──────────────────────────┐
                    │ aktsmm/Agent-Skills      │
                    │ (GitHub リポジトリ)       │
                    │ = SSOT                   │
                    └────────────┬─────────────┘
                                 │
                      起動時 git pull / 音声「スキル更新して」
                                 │
                                 ▼
                          ./skills/ (ローカル)
                                 │
                      glob("*/SKILL.md") で自動検出
                                 │
                                 ▼
                       SDK session.skill_directories
```

---

## 技術スタック

| レイヤー     | 技術                                                           |
| ------------ | -------------------------------------------------------------- |
| ランタイム   | Python 3.11+                                                   |
| AI エンジン  | `github-copilot-sdk` (Python)                                  |
| 音声入力     | `azure-cognitiveservices-speech` (STT: continuous_recognition) |
| 音声出力     | `azure-cognitiveservices-speech` (TTS: ストリーミング)         |
| テキスト入力 | `pyautogui` / `pynput` (ディクテーションモード)                |
| UI           | `pystray` + `tkinter` (システムトレイ常駐)                     |
| スキル管理   | `aktsmm/Agent-Skills` リポ自動同期 (git pull)                  |
| MCP          | Work IQ / M365 UPDATE / GitHub                                 |

---

## 既存リポジトリ資産マップ（aktsmm）

| リポジトリ                                                | 活用方法                                        |
| --------------------------------------------------------- | ----------------------------------------------- |
| **`Agent-Skills`**                                        | **SSOT。全スキルを自動同期して SDK に読み込み** |
| `vscode-M365-Update` / `d365-update` / `powerplat-update` | MCP Server として接続                           |
| `copilot-browser-bridge`                                  | Web fetch ロジック転用                          |
| `FY26_techconnect_saiten`                                 | Orchestrator-Workers パターン参考               |
| `Iac` / `azure-devsecops-demo`                            | azure-env-builder スキルの Bicep テンプレート   |
| `biz-ops-calendar-agent`                                  | M365 Copilot 連携パターン参考                   |
| `Ag-ppt-create`                                           | powerpoint-automation スキルの参考実装          |

---

## コアコード設計

> **参考実装**: kinfey/GenGitHubRepoPPT（動作実証済みのSDKパターン）

### Agent Skills 自動同期

```python
import subprocess, glob, os

SKILLS_REPO = "https://github.com/aktsmm/Agent-Skills.git"
SKILLS_DIR = "./skills"

def sync_skills():
    """起動時に Agent-Skills リポを自動同期"""
    if os.path.exists(f"{SKILLS_DIR}/.git"):
        result = subprocess.run(
            ["git", "-C", SKILLS_DIR, "pull", "--ff-only"],
            capture_output=True, text=True
        )
        print(f"Skills updated: {result.stdout.strip()}")
    else:
        subprocess.run(["git", "clone", SKILLS_REPO, SKILLS_DIR])
        print("Skills cloned")

def discover_skills():
    """skills/ 配下の全 SKILL.md を自動検出"""
    return glob.glob(f"{SKILLS_DIR}/*/SKILL.md")
```

### メインクラス

```python
from copilot import CopilotClient
from copilot.generated.session_events import SessionEventType

class VoiceAgent:
    def __init__(self):
        self.mode = "dictation"  # or "agent"
        self.copilot = CopilotClient()
        self.recognizer = speechsdk.SpeechRecognizer(...)
        self.synthesizer = speechsdk.SpeechSynthesizer(...)

    async def start(self):
        sync_skills()
        skill_paths = discover_skills()

        await self.copilot.start()
        self.session = await self.copilot.create_session({
            "model": "gpt-4.1",
            "streaming": True,
            "skill_directories": skill_paths,
            "mcpServers": {
                "workiq": {"type": "http", "url": os.environ["WORK_IQ_ENDPOINT"]},
                "m365":   {"type": "stdio", "command": "node", "args": ["./mcp-servers/m365/index.js"]},
                "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
            },
            "tools": [update_skills_tool, bing_search_tool, teams_notify_tool],
            "hooks": {
                "onPreToolUse": self._check_tool_permission,
            },
        })

        self.session.on(lambda e: self._speak_chunk(e)
                        if e.type == SessionEventType.ASSISTANT_MESSAGE_DELTA else None)
        self.session.on(lambda e: self._on_idle()
                        if e.type == SessionEventType.SESSION_IDLE else None)

        self.recognizer.recognized.connect(self._on_recognized)
        self.recognizer.start_continuous_recognition_async()

    def _on_recognized(self, evt):
        text = evt.result.text
        if not text.strip():
            return
        if self.mode == "dictation":
            pyautogui.typewrite(text)
        else:
            asyncio.create_task(
                self.session.send_and_wait({"prompt": text}, timeout=600)
            )

    def _speak_chunk(self, event):
        self.synthesizer.speak_text_async(event.data.delta_content)

    def _on_idle(self):
        pass

    def toggle_mode(self):
        self.mode = "agent" if self.mode == "dictation" else "dictation"

    async def _check_tool_permission(self, input, invocation):
        allowed_tools = ["read_file", "write_file", "list_dir", "search_news", "send_teams", "update_skills"]
        dangerous_tools = ["run_command", "bash", "shell"]
        if input.tool_name in dangerous_tools:
            return {"permissionDecision": "deny"}
        if input.tool_name in allowed_tools:
            return {"permissionDecision": "allow"}
        return {"permissionDecision": "ask"}
```

---

## mcp.json

```json
{
  "mcpServers": {
    "work-iq": { "type": "http", "url": "${WORK_IQ_ENDPOINT}" },
    "m365-update": {
      "type": "stdio",
      "command": "node",
      "args": ["./mcp-servers/m365/index.js"]
    },
    "github": { "type": "http", "url": "https://api.githubcopilot.com/mcp/" },
    "azure-tools": { "type": "http", "url": "${AZURE_MCP_ENDPOINT}" }
  }
}
```

---

## Azure Functions MCP Server（Azure 統合強化）

> 参考実装: kinfey/AzureMCPDemo

```
Voice Agent (SDK Session)
    │
    ├─ Work IQ MCP (HTTP)       ← 既存
    ├─ GitHub MCP (HTTP)        ← 既存
    ├─ M365 MCP (stdio)         ← 既存
    └─ Azure Tools MCP (HTTP)   ← 新規: Azure Functions 上
          ├─ deploy_bicep:  Azure 環境構築
          ├─ query_logs:    Log Analytics KQL
          ├─ get_costs:     Cost Management API
          └─ list_resources: リソース一覧
```

---

## セキュリティ / RAI 設計

> SDK v0.1.25 で `deny all permissions by default` に変更（#509）

- `--allow-all` は使わない → `onPreToolUse` フックで明示的に許可
- 音声データ非保存（STT 結果のテキストのみ処理）
- TTS 出力前に機密パターン（IP, パスワード, トークン）をマスク
- Fine-grained PAT（Copilot Requests: Read のみ）
- ツール実行履歴を JSON で監査ログ（`onPostToolUse` フック）

---

## Agent Skills 一覧（自動同期対象）

| スキル                     | Voice Agent での活用                      |
| -------------------------- | ----------------------------------------- |
| **azure-env-builder**      | 「検証環境作って」→ Bicep 生成・デプロイ  |
| **powerpoint-automation**  | 「会議資料まとめて」→ PPTX 自動生成       |
| **browser-max-automation** | 「このページ調べて」→ Playwright Web 操作 |
| **drawio-diagram-forge**   | 「アーキテクチャ図描いて」→ draw.io 生成  |
| **ocr-super-surya**        | 「この画像の文字読んで」→ GPU OCR         |
| **code-simplifier**        | 「このコード整理して」→ リファクタリング  |
| **customer-workspace**     | 「顧客レポート出して」→ 顧客対応支援      |
| **（今後追加するスキル）** | push するだけで自動で使える               |

---

## デモシナリオ（3分動画）

```
00:00 起動 → 「Skills synced: 10 skills loaded」トレイアイコン表示
00:15 「おはよう、今日の予定を教えて」→ Work IQ で会議一覧を読み上げ
00:45 「Contoso の最新ニュースを調べて」→ Bing + Work IQ で統合報告
01:15 「午後の会議資料をまとめて」→ PPTX 自動生成
01:45  Ctrl+Shift+D → ディクテーションモード → メール口述
02:15 「Azure に検証用 VM を立てて」→ Bicep デプロイ → 接続情報報告
02:45 「スキル更新して」→ 新スキル追加 → 能力拡張を報告
```

---

## スコア試算: 131/135

| 基準               | 配点 | 見込   | 理由                                                     |
| ------------------ | ---- | ------ | -------------------------------------------------------- |
| エンプラ適用性     | 35   | **34** | 全社員が使える＋スキル追加で無限拡張＋アクセシビリティ   |
| Azure統合          | 25   | **25** | Speech STT/TTS + Azure Functions MCP + Bicep + Cost Mgmt |
| 運用準備           | 15   | **13** | exe/installer 配布。スキル自動同期で運用負荷最小         |
| セキュリティ/RAI   | 15   | **14** | onPreToolUse フック + deny-by-default + 監査ログ         |
| ストーリーテリング | 15   | **15** | 3分デモで声→Azure→PPTX→スキル更新                        |
| IQボーナス         | 15   | **15** | Work IQ がコアに組み込まれている                         |
| SDKフィードバック  | 10   | **10** | 確実に実施                                               |
| 顧客バリデーション | 10   | **5**  | 社内メンバーフィードバック                               |

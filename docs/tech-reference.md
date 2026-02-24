# Copilot SDK 技術リファレンス

> 最終更新: 2026-02-20  
> コンテスト実装に必要な技術情報を集約

---

## 1. SDK 基本情報

| 項目           | 内容                                      |
| -------------- | ----------------------------------------- |
| リポジトリ     | https://github.com/github/copilot-sdk     |
| ステータス     | **Technical Preview**（本番利用は非推奨） |
| 最新バージョン | v0.1.25（2026-02-18 時点）                |
| 対応言語       | Node.js/TypeScript, Python, Go, .NET      |

### インストール

```bash
uv venv
uv pip install github-copilot-sdk
```

> **import 注意**: パッケージ名は `github-copilot-sdk` だが import は `from copilot import CopilotClient`

---

## 2. アーキテクチャ

```
アプリケーション（自分が作るもの）
    ↓
SDK Client
    ↓ JSON-RPC
Copilot CLI (server mode)
    ↓
Provider（モデル）
```

- **SDK ≠ モデル API ラッパー** → エージェント runtime を組み込む SDK
- Copilot CLI のエージェント実行環境をプログラムから呼び出す仕組み
- GitHub が認証・モデル管理・MCP・セッション管理を処理

---

## 3. コアコンセプト: Client / Session / Events

### Client → Session → Events の流れ

```python
from copilot import CopilotClient
from copilot.generated.session_events import SessionEventType

client = CopilotClient()
await client.start()

session = await client.create_session({
    "model": "gpt-4.1",
    "streaming": True,
    "skill_directories": ["./.copilot_skills/"]
})

# 型安全なイベント購読
session.on(lambda e: print(e.data.delta_content)
           if e.type == SessionEventType.ASSISTANT_MESSAGE_DELTA else None)

await session.send_and_wait({"prompt": "Hello"}, timeout=600)
await client.stop()
```

### Events

| Event タイプ                               | 説明                       |
| ------------------------------------------ | -------------------------- |
| `SessionEventType.ASSISTANT_MESSAGE_DELTA` | ストリーミング出力         |
| tool 実行開始/完了                         | ツール呼び出しの開始と結果 |
| `SessionEventType.SESSION_IDLE`            | ひと区切り完了通知         |
| error / retry / abort                      | エラー・リトライ・中断     |

**設計思想**: 「send → await response」ではなく「send → events を描画、idle を完了として扱う」

---

## 4. 認証方式

| 方式                  | 説明                                               |
| --------------------- | -------------------------------------------------- |
| GitHub signed-in user | CLI ログインの OAuth 資格情報                      |
| 環境変数              | `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` |
| Fine-grained PAT      | Copilot Requests: Read 権限のみ（推奨）            |
| BYOK                  | 自前 API Key（GitHub 認証不要）                    |

---

## 5. セキュリティ重要事項

### Breaking Change（v0.1.25）

> **#509: deny all permissions by default**

- `--allow-all` はデフォルトで全ツール許可 → **本番/社内ツールでは NG**
- `onPreToolUse` フックでツール実行前に権限チェックを挿入可能
- ツール許可リスト、固定作業ディレクトリ、URL ドメイン制限を設定すること

---

## 6. MCP Server 接続

```python
session = await client.create_session({
    "mcpServers": {
        "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
        "work-iq": {"type": "http", "url": "${WORK_IQ_ENDPOINT}"},
        "m365": {"type": "stdio", "command": "node", "args": ["./mcp-servers/m365/index.js"]},
    }
})
```

---

## 7. Cookbook レシピ一覧

| レシピ                   | 概要                                                              |
| ------------------------ | ----------------------------------------------------------------- |
| **Ralph Loop**           | 自律 AI コーディングループ（計画/実行モード, バックプレッシャー） |
| **Error Handling**       | 接続失敗, タイムアウト, クリーンアップ                            |
| **Multiple Sessions**    | 複数の独立した会話を同時管理                                      |
| **PR Visualization**     | GitHub MCP Server で PR エイジチャート生成                        |
| **Persisting Sessions**  | セッションの保存と再開                                            |
| **Accessibility Report** | Playwright MCP で WCAG レポート                                   |

Cookbook: https://github.com/github/awesome-copilot/tree/main/cookbook/copilot-sdk

---

## 8. 参考実装一覧

### kinfey 実装（Microsoft）

| リポジトリ                                                                                   | 内容                          | 活用ポイント                          |
| -------------------------------------------------------------------------------------------- | ----------------------------- | ------------------------------------- |
| [agent-framework-update-everyday](https://github.com/kinfey/agent-framework-update-everyday) | 日次 PR 分析 + ブログ自動生成 | GitHub Actions cron + SDK パターン    |
| [GenGitHubRepoPPT](https://github.com/kinfey/GenGitHubRepoPPT)                               | SDK Python で PPTX 自動生成   | **SDK Python の完全動作コード**       |
| [Multi-AI-Agents-Cloud-Native](https://github.com/kinfey/Multi-AI-Agents-Cloud-Native)       | A2A マルチエージェント        | 複数 Session 並行、SSE ストリーミング |
| [AzureMCPDemo](https://github.com/kinfey/AzureMCPDemo)                                       | Azure Functions MCP Server    | VNet 統合、Remote MCP 実装            |

### shinyay 実装（Microsoft DGBB Tokyo）

| リポジトリ                                                                                      | 内容                   | 活用ポイント                  |
| ----------------------------------------------------------------------------------------------- | ---------------------- | ----------------------------- |
| [getting-started-with-copilot-cli](https://github.com/shinyay/getting-started-with-copilot-cli) | SDK アーキテクチャ解説 | 認証方式4種、セキュリティ設計 |

### kinfey ベストプラクティス

1. **Copilot Skills を効果的に活用**: 入出力フォーマット・エッジケース・品質基準を明確化
2. **モデルを適材適所で選択**: 探索=GPT-5, 実行=Claude Sonnet
3. **堅牢なエラーハンドリング**: タイムアウト・レートリミット・出力検証
4. **安全な認証管理**: Fine-grained PAT + GitHub Secrets

---

## 9. 公式リソース

| リソース          | URL                                                                                                     |
| ----------------- | ------------------------------------------------------------------------------------------------------- |
| SDK リポジトリ    | https://github.com/github/copilot-sdk                                                                   |
| Getting Started   | https://github.com/github/copilot-sdk/blob/main/docs/getting-started.md                                 |
| 認証ドキュメント  | https://github.com/github/copilot-sdk/blob/main/docs/auth/index.md                                      |
| MCP ドキュメント  | https://github.com/github/copilot-sdk/blob/main/docs/mcp/overview.md                                    |
| Cookbook          | https://github.com/github/awesome-copilot/tree/main/cookbook/copilot-sdk                                |
| 公式ブログ        | https://github.blog/news-insights/company-news/build-an-agent-into-any-app-with-the-github-copilot-sdk/ |
| GitHub MCP Server | https://github.com/github/github-mcp-server                                                             |
| CLI インストール  | https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli                                   |

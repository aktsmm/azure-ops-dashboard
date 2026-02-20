# 知見サマリー（Research WS からの抽出）

> 元ワークスペース: `D:\03.5_GHC_Research`  
> 抽出日: 2026-02-20

---

## 1. SDK アーキテクチャの本質

- SDK は「モデル API ラッパー」ではない。**エージェント runtime を組み込む SDK**
- Copilot CLI のエージェント実行環境をプログラムから呼び出す仕組み
- Client（接続管理）→ Session（エージェント会話）→ Events（ストリーム）の3層構造
- Session は「1スレッドの agent」として理解する
- イベントドリブン設計: `send → events 描画 → session.idle を完了として扱う`

## 2. Python SDK の import 注意事項

```python
# パッケージ名: github-copilot-sdk
# import は:
from copilot import CopilotClient
from copilot.generated.session_events import SessionEventType
# ↑ パッケージ名と異なるので注意
```

## 3. kinfey ベストプラクティス（実証済み）

1. **Copilot Skills を効果的に活用**: 入出力フォーマット・エッジケース・品質基準を明確化
2. **モデルを適材適所で選択**: 探索=GPT-5, 実行=Claude Sonnet, コスト重視=バランス
3. **堅牢なエラーハンドリング**: タイムアウト・レートリミット・出力検証
4. **安全な認証管理**: Fine-grained PAT + GitHub Secrets
5. **バージョン管理とトレーサビリティ**: 実行ログ・履歴保存・変更追跡

## 4. セキュリティ知見（shinyay）

- `--allow-all` のリスク: デフォルトで全ツール許可は NG
- SDK v0.1.25 で `deny all permissions by default` に変更（#509）
- `onPreToolUse` フック: ツール実行前に権限チェックを挿入可能
- 認証は Fine-grained PAT（Copilot Requests: Read）推奨

## 5. azure-autodeploy 実績（20260208）

- AI Search + Cosmos DB + Container Apps を自律デプロイ成功
- Orchestrator-Workers × Evaluator-Optimizer ハイブリッドパターン
- Microsoft Docs MCP で REST API プロパティ名を動的に調査しながらデプロイ
- エラー → 原因分析 → 修正 → リトライの自律ループが機能

## 6. ExportDialogue パターン

- セッション中の重要な対話・知見を構造化して Markdown にエクスポート
- `_output-knowledge/` に日付・カテゴリでファイリング
- `knowledge-index.json` でインデックス管理

## 7. コンテスト FAQ

- **複数応募可**: 1チームで複数エントリ可
- **言語**: 英語推奨だが必須ではない
- **既存コード**: 出発点と自分の貢献を明確に文書化すること
- **同点時**: スクリーナーが再採点して判定

---

## 元ワークスペース参照パス（必要時のみ）

| 知見                      | パス                                                                       |
| ------------------------- | -------------------------------------------------------------------------- |
| SDK 実装パターン          | `_output-knowledge/copilot/20260220-kinfey-shinyay-sdk-patterns.md`        |
| SDK アーキテクチャ詳細    | `_output-knowledge/copilot/20260219-copilot-sdk-architecture-deep-dive.md` |
| Enterprise Challenge 概要 | `_output-knowledge/copilot/20260219-copilot-sdk-enterprise-challenge.md`   |
| kinfey/shinyay リポ調査   | `research/copilot/20260220-shinyay-kinfey-repo-research.md`                |
| AI エディタ + SDK 自動化  | `research/other-tools/2026-01-31-ai-editor-scheduled-execution.md`         |

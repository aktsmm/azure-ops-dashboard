# Copilot Instructions

このワークスペース共通のルール。

## Repositories

アプリ単位で独立した公開リポジトリを運用する。

| App                 | Public Repo                                           | Description                                                |
| ------------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| azure-ops-dashboard | https://github.com/aktsmm/azure-ops-dashboard         | Azure 環境可視化 + AI レポート (tkinter desktop)           |
| (monorepo)          | https://github.com/aktsmm/Ag-sdk-enterprise-challenge | SDK Challenge 全体（設計ドキュメント・セッションログ含む） |

## Python

- パッケージ管理は `uv venv` + `uv pip`（pip 直は NG）
- ワークスペースごとに `.venv` を作成
- Windows は spawn: worker 関数はモジュールレベル定義、`if __name__ == "__main__"` ガード必須
- 起動時は `.venv\Scripts\python.exe` を絶対パスで呼ぶ（`uv` の `.local\bin` が PATH で優先され Activate.ps1 が効かない場合がある）（L8）

## Git

- コミットメッセージは Conventional Commits（`feat:`, `fix:`, `docs:`, `chore:`）
- 明示的な指示がない限り `git push` は禁止
- ファイルパスは相対パスで記述（絶対パスを埋め込まない）
- monorepo → 公開リポの subtree push が non-fast-forward で失敗した場合: `git subtree split --prefix=<dir> HEAD` で SHA を取得し `git push <remote> <sha>:refs/heads/master --force` で解決（L14）

## Azure

- 読み取り専用コマンドに限定（`az graph query`, `az account show` 等）
- 破壊的操作（削除/停止/変更）は明示的な許可なしに実行しない
- 出力に秘密情報（キー/接続文字列等）を含めない

## PyInstaller / exe 配布

- リソース参照は `app_paths.py` 等のヘルパーに集約し、`Path(__file__).parent` 直参照を避ける（L2）
- 設定/テンプレートは「bundled + user override」二段構え（L3）
- frozen dataclass のフィールド名と呼び出し側キーワード引数の一致を確認する（L1）

## Workflows (Prompts)

| Prompt             | 用途                                  | トリガー                                 |
| ------------------ | ------------------------------------- | ---------------------------------------- |
| `session-close`    | コミット・公開リポ同期・DASHBOARD更新 | セッション終了時・「閉じる」「まとめて」 |
| `submission-prep`  | 提出物作成（スペック確認→作成→検証）  | コンテスト/フォーム提出時                |
| `update-dashboard` | DASHBOARD.md 更新                     | `@dashboard-updater`                     |

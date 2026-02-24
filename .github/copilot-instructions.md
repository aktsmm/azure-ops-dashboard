# Copilot Instructions

このワークスペース共通のルール。

## Python

- パッケージ管理は `uv venv` + `uv pip`（pip 直は NG）
- ワークスペースごとに `.venv` を作成
- Windows は spawn: worker 関数はモジュールレベル定義、`if __name__ == "__main__"` ガード必須
- 起動時は `.venv\Scripts\python.exe` を絶対パスで呼ぶ（`uv` の `.local\bin` が PATH で優先され Activate.ps1 が効かない場合がある）（L8）

## Git

- コミットメッセージは Conventional Commits（`feat:`, `fix:`, `docs:`, `chore:`）
- 明示的な指示がない限り `git push` は禁止
- ファイルパスは相対パスで記述（絶対パスを埋め込まない）

## Azure

- 読み取り専用コマンドに限定（`az graph query`, `az account show` 等）
- 破壊的操作（削除/停止/変更）は明示的な許可なしに実行しない
- 出力に秘密情報（キー/接続文字列等）を含めない

## PyInstaller / exe 配布

- リソース参照は `app_paths.py` 等のヘルパーに集約し、`Path(__file__).parent` 直参照を避ける（L2）
- 設定/テンプレートは「bundled + user override」二段構え（L3）
- frozen dataclass のフィールド名と呼び出し側キーワード引数の一致を確認する（L1）

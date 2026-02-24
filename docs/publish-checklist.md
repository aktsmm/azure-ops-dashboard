# 公開チェックリスト

このリポジトリを GitHub 等で「公開」する前に確認する項目です（破壊的操作は含めません）。

## 1) 秘密情報

- `.env` / `.venv` / 接続文字列 / API キー / Private Key が **コミットされていない**
- README やログは `<CLIENT_SECRET>` のような **プレースホルダ表記のみ**（実値は不可）

## 2) 公開する範囲

- ワークスペース全体を公開するか、`azure-ops-dashboard/` のみを別リポジトリにするか決める

## 3) ライセンス

- どの範囲にどのライセンスを適用するか決める（例: repo root に LICENSE を置く）
  - `azure-ops-dashboard/` は `CC-BY-NC-SA-4.0` 記載あり

## 4) 生成物・ログ

- `dist/`, `build/`, `dist-build-*/`, `*.egg-info/` が Git 管理から除外されている
- `output_sessions/` は現在 Git 管理対象のため、公開するか除外するか判断する

## 5) 動作確認

- `azure-ops-dashboard/` のテスト: `uv run python -m unittest tests -v`
- exe ビルド: `pwsh .\build_exe.ps1 -Mode onedir`

## 6) リリース

- `azure-ops-dashboard/CHANGELOG.md` を更新し、`azure-ops-dashboard/pyproject.toml` の version と整合させる
- 配布物は onedir の場合 `dist/.../` フォルダ丸ごと zip 配布

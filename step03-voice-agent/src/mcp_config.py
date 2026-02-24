"""Step 03: Voice Agent — Work IQ MCP 連携設定

GitHub Copilot SDK セッションに MCP サーバー設定を注入する。

対応 MCP サーバー:
- Work IQ (m365): Microsoft 365 データ（メール/会議/ファイル）
- GitHub MCP: PR/Issue/リポジトリ操作
- microsoft_docs: Microsoft ドキュメント検索

設定は mcp.json から読み込むか、デフォルト設定を使用。

使い方::

    from mcp_config import MCPConfig

    mcp = MCPConfig()
    session_config = mcp.inject_into_config(session_config)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


# MCP サーバー設定テンプレート
_DEFAULT_MCP_SERVERS: dict[str, Any] = {
    # GitHub MCP Server（HTTPS）
    "github": {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
    },
}

# Work IQ MCP は stdio 接続（workiq-mcp パッケージが必要）
_WORKIQ_MCP_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "workiq_mcp"],
    "env": {
        "WORKIQ_LOG_LEVEL": "WARNING",
    },
}


class MCPConfig:
    """SDK セッション設定への MCP サーバー注入を担当。

    Parameters
    ----------
    mcp_json_path:
        外部 mcp.json へのパス。存在する場合はそこから設定を読む。
        None の場合はデフォルト設定を使用。
    enable_workiq:
        Work IQ MCP（Microsoft 365）を有効化するか。
        workiq_mcp パッケージが未インストールの場合は自動的に False。
    enable_github:
        GitHub MCP を有効化するか（default: True）。
    """

    def __init__(
        self,
        mcp_json_path: Optional[Path] = None,
        enable_workiq: bool = True,
        enable_github: bool = True,
    ) -> None:
        self._custom_json_path = mcp_json_path
        self._enable_workiq = enable_workiq and self._check_workiq_available()
        self._enable_github = enable_github

    # ------------------------------------------------------------------ #
    # 可用性チェック
    # ------------------------------------------------------------------ #

    @staticmethod
    def _check_workiq_available() -> bool:
        """workiq_mcp / work-iq-mcp がインストール済みか確認。"""
        try:
            import importlib
            importlib.import_module("workiq_mcp")
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------ #
    # 設定生成
    # ------------------------------------------------------------------ #

    def mcp_servers(self) -> dict[str, Any]:
        """MCP サーバー設定 dict を返す。

        mcp.json が存在する場合はそこから読み込み、
        存在しない場合はデフォルト設定を生成する。
        """
        # 外部 mcp.json が指定されている場合
        if self._custom_json_path is not None:
            return self._load_mcp_json(self._custom_json_path)

        # デフォルトの mcp.json を探す
        # src/ → step03/ → workspace_root/ の順で探す
        candidates = [
            Path(__file__).parent / "mcp.json",
            Path(__file__).parent.parent / "mcp.json",
            Path(__file__).parent.parent.parent / "mcp.json",
        ]
        for candidate in candidates:
            if candidate.is_file():
                loaded = self._load_mcp_json(candidate)
                if loaded:
                    return loaded

        # mcp.json が見つからなければデフォルト設定を構築
        return self._build_default_servers()

    def _load_mcp_json(self, path: Path) -> dict[str, Any]:
        """mcp.json を読み込んで mcpServers セクションを返す。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            servers: dict[str, Any] = data.get("mcpServers", data)
            print(f"[mcp] mcp.json を読み込みました: {path}", file=sys.stderr)
            return servers
        except Exception as e:  # noqa: BLE001
            print(f"[mcp] mcp.json 読み込み失敗: {e}", file=sys.stderr)
            return {}

    def _build_default_servers(self) -> dict[str, Any]:
        """デフォルトの MCP サーバー設定を構築。"""
        servers: dict[str, Any] = {}

        if self._enable_github:
            servers["github"] = _DEFAULT_MCP_SERVERS["github"]
            print("[mcp] GitHub MCP: 有効", file=sys.stderr)

        if self._enable_workiq:
            servers["workiq"] = _WORKIQ_MCP_SERVER
            print("[mcp] Work IQ MCP: 有効", file=sys.stderr)
        else:
            print("[mcp] Work IQ MCP: 無効（workiq_mcp 未インストール）", file=sys.stderr)

        return servers

    # ------------------------------------------------------------------ #
    # セッション設定注入
    # ------------------------------------------------------------------ #

    def inject_into_config(self, session_config: dict[str, Any]) -> dict[str, Any]:
        """セッション設定 dict に mcpServers を注入して返す（コピー）。

        既存の mcpServers がある場合はマージする。

        Parameters
        ----------
        session_config:
            SDK create_session に渡す設定 dict。

        Returns
        -------
        dict[str, Any]
            mcpServers が追加された設定 dict。
        """
        servers = self.mcp_servers()
        if not servers:
            return session_config

        existing = dict(session_config.get("mcpServers", {}))
        merged = {**servers, **existing}  # 既存設定を優先
        return {**session_config, "mcpServers": merged}

    def print_summary(self) -> None:
        """MCP サーバー設定の概要を表示。"""
        servers = self.mcp_servers()
        if not servers:
            print("[mcp] MCP サーバーが設定されていません。")
            return
        print(f"[mcp] {len(servers)} 件の MCP サーバーが設定されています:")
        for name, cfg in servers.items():
            server_type = cfg.get("type", "unknown")
            url = cfg.get("url", cfg.get("command", ""))
            print(f"  - {name}: {server_type}  {url}")


if __name__ == "__main__":
    # 動作確認用
    mcp = MCPConfig()
    mcp.print_summary()

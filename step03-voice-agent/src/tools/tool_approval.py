"""Step 03: Voice Agent — onPreToolUse ハンドラ

SDK セッションの ``hooks.on_pre_tool_use`` に登録する
ツール実行前許可/拒否/確認ロジック。

設計方針（docs/design.md より）:
- dangerous_tools（bash, shell 等）は即 deny
- allowlist 内のツールは即 allow
- それ以外は confirmation_mode 設定に従い ask または deny

使い方::

    from tools import ApprovalMode, ToolApproval

    approval = ToolApproval(mode=ApprovalMode.SAFE)
    session_config = {
        ...
        "hooks": {"on_pre_tool_use": approval.on_pre_tool_use},
    }
"""

from __future__ import annotations

import json
import sys
from enum import Enum, auto
from typing import Any, Callable, Optional


class ApprovalMode(Enum):
    """ツール承認の動作モード。"""
    ALLOW_ALL = auto()    # 全ツール許可（開発用）
    SAFE = auto()         # allowlist のみ許可、その他は deny
    INTERACTIVE = auto()  # allowlist 以外は TUI で確認


# ---------------------------------------------------------------------------
# デフォルトのツール分類
# ---------------------------------------------------------------------------

# 明示的に許可するツール（読み取り・通知系）
DEFAULT_ALLOWED_TOOLS: frozenset[str] = frozenset({
    # 読み取り系
    "read_file",
    "list_dir",
    "file_search",
    "grep_search",
    "semantic_search",
    # ドキュメント・検索
    "microsoft_docs_search",
    "microsoft_docs_fetch",
    "microsoft_code_sample_search",
    # Azure（読み取りのみ）
    "az_graph_query",
    # GitHub（読み取りのみ）
    "github_get_repo",
    "github_list_prs",
    # ブラウザ（参照のみ）
    "browser_navigate",
    "browser_snapshot",
})

# 危険なツール（即 deny）
DEFAULT_DANGEROUS_TOOLS: frozenset[str] = frozenset({
    "bash",
    "shell",
    "run_command",
    "exec",
    "execute",
    "python_repl",
    "delete_file",
    "rm",
    "rmdir",
    "az_delete",
    "az_stop",
})


class ToolApproval:
    """onPreToolUse フックの実装。

    Parameters
    ----------
    mode:
        ApprovalMode.ALLOW_ALL / SAFE / INTERACTIVE
    allowed_tools:
        許可ツール名のセット（None で DEFAULT_ALLOWED_TOOLS を使用）
    dangerous_tools:
        拒否ツール名のセット（None で DEFAULT_DANGEROUS_TOOLS を使用）
    audit_log:
        呼び出し履歴をためる list（外部から渡せばログ取得が容易）
    confirm_callback:
        INTERACTIVE モードで ``ask`` の代わりに呼ぶコールバック。
        ``callback(tool_name: str, args: dict) -> bool`` で
        True なら allow、False なら deny を返す。
        None の場合は TUI（標準入力）で確認する。
    """

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.SAFE,
        allowed_tools: Optional[frozenset[str]] = None,
        dangerous_tools: Optional[frozenset[str]] = None,
        audit_log: Optional[list[dict[str, Any]]] = None,
        confirm_callback: Optional[Callable[[str, dict], bool]] = None,
    ) -> None:
        self._mode = mode
        self._allowed = allowed_tools if allowed_tools is not None else DEFAULT_ALLOWED_TOOLS
        self._dangerous = dangerous_tools if dangerous_tools is not None else DEFAULT_DANGEROUS_TOOLS
        self._audit_log = audit_log if audit_log is not None else []
        self._confirm_callback = confirm_callback

    # ------------------------------------------------------------------ #
    # フックエントリポイント
    # ------------------------------------------------------------------ #

    async def on_pre_tool_use(
        self,
        input_data: Any,
        invocation: Any,
    ) -> dict[str, Any]:
        """SDK の ``hooks.on_pre_tool_use`` に渡す非同期ハンドラ。

        Parameters
        ----------
        input_data:
            ツール入力情報。dict の場合 ``toolName`` / ``toolArgs`` キーを参照。
            オブジェクトの場合 ``tool_name`` / ``tool_args`` 属性を参照。
        invocation:
            SDK の invocation オブジェクト（現在は未使用）。

        Returns
        -------
        dict
            ``{"permissionDecision": "allow" | "deny", "modifiedArgs": ...}``
        """
        # tool_name と tool_args を両方の形式で取得
        if isinstance(input_data, dict):
            tool_name: str = input_data.get("toolName", input_data.get("tool_name", "unknown"))
            tool_args: dict = input_data.get("toolArgs", input_data.get("tool_args", {}))
        else:
            tool_name = getattr(input_data, "tool_name", getattr(input_data, "toolName", "unknown"))
            tool_args = getattr(input_data, "tool_args", getattr(input_data, "toolArgs", {}))

        decision = self._decide(tool_name, tool_args)

        # 監査ログに記録
        self._audit_log.append({
            "tool": tool_name,
            "decision": decision,
            "args_preview": str(tool_args)[:200],
        })
        print(
            f"[tools] {decision.upper():5s} → {tool_name}",
            file=sys.stderr,
        )

        return {
            "permissionDecision": decision,
            "modifiedArgs": tool_args,
        }

    # ------------------------------------------------------------------ #
    # 判定ロジック
    # ------------------------------------------------------------------ #

    def _decide(self, tool_name: str, tool_args: dict) -> str:
        """ツール名に基づいて "allow" / "deny" を返す。"""
        # 常に deny（危険ツール）
        if tool_name in self._dangerous:
            return "deny"

        # ALLOW_ALL モード: 危険ツール以外は全許可
        if self._mode == ApprovalMode.ALLOW_ALL:
            return "allow"

        # allowlist にある場合は許可
        if tool_name in self._allowed:
            return "allow"

        # SAFE モード: allowlist 外は deny
        if self._mode == ApprovalMode.SAFE:
            return "deny"

        # INTERACTIVE モード: コールバックまたは TUI で確認
        if self._mode == ApprovalMode.INTERACTIVE:
            return self._confirm(tool_name, tool_args)

        return "deny"

    def _confirm(self, tool_name: str, tool_args: dict) -> str:
        """INTERACTIVE モードのユーザー確認。"""
        if self._confirm_callback is not None:
            allowed = self._confirm_callback(tool_name, tool_args)
            return "allow" if allowed else "deny"

        # TUI フォールバック（コンソールで確認）
        args_str = json.dumps(tool_args, ensure_ascii=False)[:100]
        try:
            ans = input(
                f"\n[tools] ⚠️ ツール実行確認\n"
                f"  ツール: {tool_name}\n"
                f"  引数:   {args_str}\n"
                f"  許可しますか? [y/N]: "
            ).strip().lower()
            return "allow" if ans in ("y", "yes") else "deny"
        except (EOFError, KeyboardInterrupt):
            return "deny"

    # ------------------------------------------------------------------ #
    # セッション設定ヘルパー
    # ------------------------------------------------------------------ #

    def inject_into_config(self, session_config: dict[str, Any]) -> dict[str, Any]:
        """セッション設定 dict に ``hooks.on_pre_tool_use`` を注入して返す（コピー）。

        Parameters
        ----------
        session_config:
            SDK create_session に渡す設定 dict。

        Returns
        -------
        dict[str, Any]
            ``hooks`` に ``on_pre_tool_use`` が追加された設定 dict。
        """
        hooks = dict(session_config.get("hooks", {}))
        hooks["on_pre_tool_use"] = self.on_pre_tool_use
        return {**session_config, "hooks": hooks}

    # ------------------------------------------------------------------ #
    # ユーティリティ
    # ------------------------------------------------------------------ #

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """ツール呼び出し履歴。"""
        return self._audit_log

    def clear_audit_log(self) -> None:
        """監査ログをクリア。"""
        self._audit_log.clear()

    def print_audit_log(self) -> None:
        """監査ログを標準出力に表示。"""
        if not self._audit_log:
            print("[tools] 監査ログは空です。")
            return
        print(f"[tools] 監査ログ ({len(self._audit_log)} 件):")
        for i, entry in enumerate(self._audit_log, 1):
            print(f"  {i:3d}. [{entry['decision'].upper():5s}] {entry['tool']}")

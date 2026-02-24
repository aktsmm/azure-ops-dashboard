"""Step 03: Voice Agent — SkillManager

Agent-Skills の自動同期と skill_directories 設定を担当。

機能:
- ローカルの .github/skills/ を走査してスキル一覧を取得
- git pull で最新スキル定義を取得（optional）
- SDK セッション設定用の skill_directories リストを生成

使い方::

    mgr = SkillManager(workspace_root=Path("..."))
    mgr.sync()  # git pull（スキップ可）
    dirs = mgr.skill_directories()
    session_config = {"skill_directories": dirs, ...}
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


class SkillManager:
    """Agent-Skills 自動同期と skill_directories 注入。

    Parameters
    ----------
    workspace_root:
        モノレポのルートディレクトリ（.github/skills/ を含むパス）。
        None の場合は src/app.py の 3 階層上を自動推定。
    skills_subdir:
        スキルが格納されたサブディレクトリ名（default: ".github/skills"）。
    auto_pull:
        インスタンス生成時に git pull を実行するか（default: False）。
    """

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        skills_subdir: str = ".github/skills",
        auto_pull: bool = False,
    ) -> None:
        if workspace_root is None:
            # src/skills/skill_manager.py → src/ → step03/ → workspace_root
            workspace_root = Path(__file__).parent.parent.parent.parent
        self._root = Path(workspace_root).resolve()
        self._skills_dir = self._root / skills_subdir
        self._pull_done = False

        if auto_pull:
            self.sync()

    # ------------------------------------------------------------------ #
    # 公開 API
    # ------------------------------------------------------------------ #

    def sync(self, *, timeout: int = 30) -> bool:
        """git pull でスキル定義を最新化する。

        Returns
        -------
        bool
            pull に成功すれば True。失敗（git なし等）は False で続行。
        """
        if not self._root.is_dir():
            print("[skills] workspace_root が見つかりません", file=sys.stderr)
            return False

        print(f"[skills] git pull ({self._root}) ...", file=sys.stderr)
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode == 0:
                print(f"[skills] ✅ git pull 完了: {result.stdout.strip()}", file=sys.stderr)
                self._pull_done = True
                return True
            else:
                print(
                    f"[skills] ⚠️ git pull 失敗 (exit {result.returncode}): {result.stderr.strip()}",
                    file=sys.stderr,
                )
                return False
        except FileNotFoundError:
            print("[skills] git が見つかりません。スキル同期をスキップ。", file=sys.stderr)
            return False
        except subprocess.TimeoutExpired:
            print(f"[skills] git pull タイムアウト ({timeout}s)", file=sys.stderr)
            return False
        except Exception as e:  # noqa: BLE001
            print(f"[skills] git pull エラー: {e}", file=sys.stderr)
            return False

    def list_skills(self) -> list[dict[str, Any]]:
        """利用可能なスキルの一覧を返す。

        各エントリは {"name": str, "path": str, "has_skill_md": bool} の dict。
        .github/skills/ の直下ディレクトリを走査する。
        """
        if not self._skills_dir.is_dir():
            print(
                f"[skills] スキルディレクトリが見つかりません: {self._skills_dir}",
                file=sys.stderr,
            )
            return []

        skills: list[dict[str, Any]] = []
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                skill_md = entry / "SKILL.md"
                skills.append({
                    "name": entry.name,
                    "path": str(entry),
                    "has_skill_md": skill_md.is_file(),
                })
        return skills

    def skill_directories(self) -> list[str]:
        """SDK セッション設定の ``skill_directories`` 用パスリストを返す。

        SKILL.md が存在するディレクトリのみを対象とする。

        Returns
        -------
        list[str]
            絶対パスの文字列リスト。スキルが無ければ空リスト。
        """
        return [
            s["path"]
            for s in self.list_skills()
            if s["has_skill_md"]
        ]

    def inject_into_config(self, session_config: dict[str, Any]) -> dict[str, Any]:
        """セッション設定 dict に skill_directories を注入して返す（コピー）。

        既存の skill_directories がある場合はマージする。

        Parameters
        ----------
        session_config:
            SDK create_session に渡す設定 dict。

        Returns
        -------
        dict[str, Any]
            skill_directories が追加された設定 dict。
        """
        dirs = self.skill_directories()
        if not dirs:
            return session_config

        existing = list(session_config.get("skill_directories", []))
        merged = existing + [d for d in dirs if d not in existing]
        return {**session_config, "skill_directories": merged}

    # ------------------------------------------------------------------ #
    # デバッグ表示
    # ------------------------------------------------------------------ #

    def print_summary(self) -> None:
        """利用可能なスキルの概要を標準出力に表示。"""
        skills = self.list_skills()
        if not skills:
            print("[skills] スキルが見つかりません。")
            return

        print(f"[skills] {len(skills)} 件のスキルが利用可能:")
        for s in skills:
            mark = "✅" if s["has_skill_md"] else "⚠️ SKILL.md なし"
            print(f"  {mark} {s['name']}  ({s['path']})")


if __name__ == "__main__":
    # 動作確認用
    mgr = SkillManager()
    mgr.print_summary()
    print("skill_directories:", mgr.skill_directories())

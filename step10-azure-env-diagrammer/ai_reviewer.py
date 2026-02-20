"""Step10: Azure Ops Dashboard — AI レビュー & レポート (GitHub Copilot SDK)

Collect したリソース一覧を Copilot SDK に送り、
構成のレビュー結果や各種レポート（日本語）をストリーミングで返す。
テンプレート設定とカスタム指示に対応。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from copilot import CopilotClient

from app_paths import bundled_templates_dir, ensure_user_dirs, template_search_dirs
from docs_enricher import (
    cost_search_queries,
    enrich_with_docs,
    security_search_queries,
)


def _approve_all(request: object) -> dict:
    """全てのパーミッションリクエストを承認する。"""
    return {"kind": "approved", "rules": []}

# ============================================================
# テンプレート管理
# ============================================================

TEMPLATES_DIR = bundled_templates_dir()


def list_templates(report_type: str) -> list[dict[str, Any]]:
    """指定レポート種別のテンプレート一覧を返す。"""
    ensure_user_dirs()

    # user → bundled の順で集め、同名ファイルは user を優先
    seen: set[str] = set()
    templates: list[dict[str, Any]] = []

    for base in template_search_dirs():
        if not base.exists():
            continue
        for f in sorted(base.glob(f"{report_type}-*.json")):
            key = f.name.lower()
            if key in seen:
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["_path"] = str(f)
                templates.append(data)
                seen.add(key)
            except (json.JSONDecodeError, OSError):
                pass

    return templates


def load_template(path: str) -> dict[str, Any]:
    """テンプレートJSONを読み込む。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_template(path: str, data: dict[str, Any]) -> None:
    """テンプレートJSONを保存する。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_template_instruction(template: dict[str, Any], custom_instruction: str = "") -> str:
    """テンプレート設定からAI向けの指示テキストを構築する。"""
    sections = template.get("sections", {})
    options = template.get("options", {})

    enabled = [f"- {v['label']}: {v.get('description', '')}"
               for k, v in sections.items() if v.get("enabled")]
    disabled = [f"- {v['label']}" for k, v in sections.items() if not v.get("enabled")]

    lines = []
    lines.append("## レポート構成指示")
    lines.append("")
    lines.append("### 含めるセクション（必ず出力すること）:")
    lines.extend(enabled)
    lines.append("")
    if disabled:
        lines.append("### 含めないセクション（出力しないこと）:")
        lines.extend(disabled)
        lines.append("")

    # オプション
    opt_lines = []
    if options.get("show_resource_ids"):
        opt_lines.append("- リソースIDをフル表示する")
    else:
        opt_lines.append("- リソースIDは省略し、リソース名のみ表示")
    if options.get("show_mermaid_charts"):
        opt_lines.append("- Mermaid チャートを含める")
    else:
        opt_lines.append("- Mermaid チャートは含めない")
    if options.get("include_remediation"):
        opt_lines.append("- 修復手順を含める")
    if options.get("redact_subscription"):
        opt_lines.append("- サブスクリプションIDはマスクする（例: xxxxxxxx-xxxx-...）")
    max_items = options.get("max_detail_items", 10)
    opt_lines.append(f"- 詳細項目は最大 {max_items} 件まで")
    currency = options.get("currency_symbol", "")
    if currency:
        opt_lines.append(f"- 通貨記号: {currency}")

    if opt_lines:
        lines.append("### 出力オプション:")
        lines.extend(opt_lines)
        lines.append("")

    # カスタム指示
    if custom_instruction.strip():
        lines.append("### ユーザーからの追加指示:")
        lines.append(custom_instruction.strip())
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 定数
# ============================================================

MODEL = "gpt-4.1"
MAX_RETRY = 2
RETRY_BACKOFF = 2.0
SEND_TIMEOUT = 120  # sec

SYSTEM_PROMPT_REVIEW = """\
あなたは Azure インフラストラクチャのレビュー専門家です。
ユーザーから Azure Resource Graph で取得したリソース一覧が提供されます。

以下の観点でレビューし、日本語で簡潔にまとめてください:

1. **構成概要** — 何のシステムか推測し、2-3行で説明
2. **リソース構成の妥当性** — 冗長性・HA構成の有無、足りないリソースの指摘
3. **セキュリティ** — NSG, Key Vault, Private Endpoint の有無
4. **コスト最適化** — 不要に見えるリソース（NetworkWatcher の重複等）
5. **図にする際のヒント** — グループ化の提案

回答は Markdown で、全体 500文字以内に収めてください。
"""

SYSTEM_PROMPT_SECURITY_BASE = """\
あなたは Azure セキュリティ監査の専門家です。
Azure Security Center / Microsoft Defender for Cloud のデータが提供されます。
日本語の Markdown 形式でセキュリティレポートを生成してください。
表やリストを活用して読みやすく。
参考ドキュメントが提供された場合は、推奨事項に公式ドキュメントの URL を脚注として付けてください。
"""

SYSTEM_PROMPT_COST_BASE = """\
あなたは Azure コスト最適化の専門家です。
Azure Cost Management のデータ（サービス別・RG別コスト）が提供されます。
日本語の Markdown 形式でコストレポートを生成してください。
金額は通貨記号付きで、表を活用して読みやすく。
参考ドキュメントが提供された場合は、推奨事項に公式ドキュメントの URL を脚注として付けてください。
"""


# ============================================================
# Reviewer クラス
# ============================================================

class AIReviewer:
    """Copilot SDK を使ったリソースレビュー / レポート生成。

    Usage::
        reviewer = AIReviewer(on_delta=print)
        result = await reviewer.review(resource_summary_text)
        result = await reviewer.generate(prompt, system_prompt)
    """

    def __init__(
        self,
        on_delta: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_delta = on_delta or (lambda s: print(s, end="", flush=True))
        self._on_status = on_status or (lambda s: print(f"[reviewer] {s}"))

    async def review(self, resource_text: str) -> str | None:
        """リソースサマリをレビューし、結果テキストを返す。"""
        prompt = (
            "以下のAzureリソース一覧をレビューしてください:\n\n"
            f"```\n{resource_text}\n```"
        )
        return await self.generate(prompt, SYSTEM_PROMPT_REVIEW)

    async def generate(self, prompt: str, system_prompt: str) -> str | None:
        """汎用: 任意のプロンプトとシステムプロンプトで生成。"""
        client: CopilotClient | None = None
        try:
            # 1. SDK 接続
            self._on_status("Copilot SDK に接続中...")
            client = CopilotClient()
            await client.start()
            self._on_status("Copilot SDK 接続 OK")

            # 2. セッション作成
            session = await client.create_session({
                "model": MODEL,
                "streaming": True,
                "on_permission_request": _approve_all,
                "system_message": system_prompt,
            })

            # 3. ストリーミングイベント収集
            collected: list[str] = []

            def _handler(event: Any) -> None:
                etype = event.type.value if hasattr(event.type, "value") else str(event.type)
                if etype == "assistant.message_delta":
                    delta = getattr(event.data, "delta_content", "")
                    if delta:
                        collected.append(delta)
                        self._on_delta(delta)

            session.on(_handler)

            # 4. 送信
            self._on_status("AI 処理実行中...")
            reply = await session.send_and_wait(
                {"prompt": prompt},
                timeout=SEND_TIMEOUT,
            )

            # send_and_wait の戻り値 or ストリーム収集結果
            if reply and hasattr(reply, "data") and hasattr(reply.data, "content"):
                result = reply.data.content
            else:
                result = "".join(collected) if collected else None

            # 5. クリーンアップ
            await session.destroy()

            return result

        except Exception as e:
            self._on_status(f"AI レビューエラー: {e}")
            return None
        finally:
            if client:
                try:
                    await client.stop()
                except Exception:
                    pass


# ============================================================
# 同期ラッパー（tkinter スレッドから呼ぶ用）
# ============================================================


def _extract_resource_types(resource_text: str) -> list[str]:
    """リソーステキストから type 列を抽出する（ベストエフォート）。"""
    types: set[str] = set()
    for line in resource_text.splitlines():
        parts = line.split()
        for p in parts:
            if "/" in p and p.lower().startswith("microsoft."):
                types.add(p.strip().lower())
    return list(types)


def run_ai_review(
    resource_text: str,
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> str | None:
    """同期的にAIレビューを実行して結果を返す。"""
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status)
    return _run_async(reviewer.review(resource_text))


def run_security_report(
    security_data: dict,
    resource_text: str,
    template: dict | None = None,
    custom_instruction: str = "",
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> str | None:
    """セキュリティレポートを生成。"""
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status)
    log = on_status or (lambda s: None)

    # テンプレートがあればシステムプロンプトに反映
    if template:
        tmpl_instruction = build_template_instruction(template, custom_instruction)
        system_prompt = SYSTEM_PROMPT_SECURITY_BASE + "\n\n" + tmpl_instruction
    else:
        system_prompt = SYSTEM_PROMPT_SECURITY_BASE
        if custom_instruction.strip():
            system_prompt += f"\n\n### ユーザーからの追加指示:\n{custom_instruction.strip()}"

    # Microsoft Docs 参照を取得（失敗時はスキップ）
    resource_types = _extract_resource_types(resource_text)
    queries = security_search_queries(resource_types)
    docs_block = enrich_with_docs(
        queries, report_type="security",
        resource_types=resource_types, on_status=log,
    )
    if not docs_block:
        log("Microsoft Docs 参照なしでレポートを生成します")

    prompt = (
        "以下のAzure環境のセキュリティレポートを生成してください。\n\n"
        "## セキュリティデータ\n"
        f"```json\n{json.dumps(security_data, indent=2, ensure_ascii=False)}\n```\n\n"
        "## リソース一覧\n"
        f"```\n{resource_text}\n```"
        f"{docs_block}"
    )
    return _run_async(reviewer.generate(prompt, system_prompt))


def run_cost_report(
    cost_data: dict,
    advisor_data: dict,
    template: dict | None = None,
    custom_instruction: str = "",
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    resource_types: list[str] | None = None,
) -> str | None:
    """コストレポートを生成。"""
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status)
    log = on_status or (lambda s: None)

    # テンプレートがあればシステムプロンプトに反映
    if template:
        tmpl_instruction = build_template_instruction(template, custom_instruction)
        system_prompt = SYSTEM_PROMPT_COST_BASE + "\n\n" + tmpl_instruction
    else:
        system_prompt = SYSTEM_PROMPT_COST_BASE
        if custom_instruction.strip():
            system_prompt += f"\n\n### ユーザーからの追加指示:\n{custom_instruction.strip()}"

    # Microsoft Docs 参照を取得（失敗時はスキップ）
    queries = cost_search_queries(resource_types)
    docs_block = enrich_with_docs(
        queries, report_type="cost",
        resource_types=resource_types, on_status=log,
    )
    if not docs_block:
        log("Microsoft Docs 参照なしでレポートを生成します")

    prompt = (
        "以下のAzure環境のコストレポートを生成してください。\n\n"
        "## コストデータ\n"
        f"```json\n{json.dumps(cost_data, indent=2, ensure_ascii=False)}\n```\n\n"
        "## Advisor 推奨事項\n"
        f"```json\n{json.dumps(advisor_data, indent=2, ensure_ascii=False)}\n```"
        f"{docs_block}"
    )
    return _run_async(reviewer.generate(prompt, system_prompt))


def _run_async(coro: Any) -> Any:
    """コルーチンを同期的に実行する。バックグラウンドスレッドから呼ぶ前提。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=SEND_TIMEOUT + 30)
    else:
        return asyncio.run(coro)

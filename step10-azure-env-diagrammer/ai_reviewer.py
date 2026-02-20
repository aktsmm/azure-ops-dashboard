"""Step10: Azure Ops Dashboard — AI レビュー & レポート (GitHub Copilot SDK)

Collect したリソース一覧を Copilot SDK に送り、
構成のレビュー結果や各種レポート（日本語）をストリーミングで返す。
テンプレート設定とカスタム指示に対応。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import re
from pathlib import Path
from typing import Any, Callable, Optional

from copilot import CopilotClient

from app_paths import (
    bundled_templates_dir,
    copilot_cli_path,
    ensure_user_dirs,
    template_search_dirs,
)
from docs_enricher import (
    cost_search_queries,
    enrich_with_docs,
    security_search_queries,
)
from i18n import t as _t, get_language


def _approve_all(request: object) -> dict:
    """全てのパーミッションリクエストを承認する。"""
    return {"kind": "approved", "rules": []}


# ============================================================
# Session Hooks（SDK推奨パターン）
# ============================================================

# 読み取り専用ツールのみ許可（安全性向上）
_ALLOWED_TOOLS = frozenset({
    "view", "read", "readFile", "search", "grep",
    "list", "ls", "find", "cat", "head", "tail",
    # Microsoft Docs MCP ツール（読み取り専用）
    "microsoft_docs_search",
    "microsoft_docs_fetch",
    "microsoft_code_sample_search",
})


async def _on_pre_tool_use(input_data: dict, invocation: Any) -> dict:
    """ツール実行前のフック: 読み取り専用ツールのみ許可。"""
    tool_name = input_data.get("toolName", "")
    # 読み取り系は許可、それ以外は拒否
    if tool_name in _ALLOWED_TOOLS:
        decision = "allow"
    else:
        decision = "deny"
    return {
        "permissionDecision": decision,
        "modifiedArgs": input_data.get("toolArgs"),
    }


def _make_error_handler(
    on_status: Callable[[str], None],
    max_retry: int = 2,
) -> Callable:
    """リトライ付きエラーハンドラを生成。"""
    _retry_count: dict[str, int] = {}

    async def _on_error_occurred(input_data: dict, invocation: Any) -> dict:
        ctx = input_data.get("errorContext", "unknown")
        err = input_data.get("error", "")
        key = f"{ctx}:{err}"
        _retry_count[key] = _retry_count.get(key, 0) + 1

        if _retry_count[key] <= max_retry:
            wait = RETRY_BACKOFF ** _retry_count[key]
            if get_language() == "en":
                on_status(f"AI error (retry {_retry_count[key]}/{max_retry}, waiting {wait:.0f}s): {err}")
            else:
                on_status(f"AI エラー（リトライ {_retry_count[key]}/{max_retry}, {wait:.0f}s 待機）: {err}")
            await asyncio.sleep(wait)
            return {"errorHandling": "retry"}
        else:
            if get_language() == "en":
                on_status(f"AI error (aborted): {err}")
            else:
                on_status(f"AI エラー（中止）: {err}")
            return {"errorHandling": "abort"}

    return _on_error_occurred

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

    lang = get_language()

    def _desc(v: dict[str, Any]) -> str:
        if lang == "en":
            return str(v.get("description_en") or v.get("description") or "")
        return str(v.get("description") or v.get("description_en") or "")

    def _label(v: dict[str, Any]) -> str:
        if lang == "en":
            return str(v.get("label_en") or v.get("label") or "")
        return str(v.get("label") or v.get("label_en") or "")

    enabled = [f"- {_label(v)}: {_desc(v)}"
               for _k, v in sections.items() if v.get("enabled")]
    disabled = [f"- {_label(v)}" for _k, v in sections.items() if not v.get("enabled")]

    lines = []
    if lang == "en":
        lines.append("## Report Structure Instructions")
    else:
        lines.append("## レポート構成指示")
    lines.append("")
    lines.append(
        "### Included sections (must output):" if lang == "en"
        else "### 含めるセクション（必ず出力すること）:"
    )
    lines.extend(enabled)
    lines.append("")
    if disabled:
        lines.append(
            "### Excluded sections (do NOT output):" if lang == "en"
            else "### 含めないセクション（出力しないこと）:"
        )
        lines.extend(disabled)
        lines.append("")

    # オプション
    opt_lines = []
    if options.get("show_resource_ids"):
        opt_lines.append("- Show full Resource IDs" if lang == "en" else "- リソースIDをフル表示する")
    else:
        opt_lines.append(
            "- Omit Resource IDs; show resource names only" if lang == "en"
            else "- リソースIDは省略し、リソース名のみ表示"
        )
    if options.get("show_mermaid_charts"):
        opt_lines.append("- Include Mermaid charts" if lang == "en" else "- Mermaid チャートを含める")
    else:
        opt_lines.append("- Do not include Mermaid charts" if lang == "en" else "- Mermaid チャートは含めない")
    if options.get("include_remediation"):
        opt_lines.append("- Include remediation steps" if lang == "en" else "- 修復手順を含める")
    if options.get("redact_subscription"):
        opt_lines.append(
            "- Redact subscription IDs (e.g., xxxxxxxx-xxxx-...)" if lang == "en"
            else "- サブスクリプションIDはマスクする（例: xxxxxxxx-xxxx-...）"
        )
    max_items = options.get("max_detail_items", 10)
    opt_lines.append(
        f"- Limit detail items to max {max_items}" if lang == "en"
        else f"- 詳細項目は最大 {max_items} 件まで"
    )
    currency = options.get("currency_symbol", "")
    if currency:
        opt_lines.append(f"- Currency symbol: {currency}" if lang == "en" else f"- 通貨記号: {currency}")

    if opt_lines:
        lines.append("### Output options:" if lang == "en" else "### 出力オプション:")
        lines.extend(opt_lines)
        lines.append("")

    # カスタム指示
    if custom_instruction.strip():
        lines.append("### Additional user instructions:" if lang == "en" else "### ユーザーからの追加指示:")
        lines.append(custom_instruction.strip())
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 定数
# ============================================================

MODEL = "gpt-4.1"
MAX_RETRY = 2
RETRY_BACKOFF = 2.0
SEND_TIMEOUT = 180  # sec（MCP ツール呼び出し分を考慮して延長）


def choose_default_model_id(model_ids: list[str]) -> str:
    """モデルID一覧から既定モデルを選ぶ。

    優先順位:
      1) claude-sonnet の最新（x.y を数値比較）
      2) gpt-4.1
      3) 先頭
    """

    def _sonnet_ver(mid: str) -> tuple[int, int] | None:
        m = re.match(r"^claude-sonnet-(\d+)(?:\.(\d+))?$", mid)
        if not m:
            return None
        major = int(m.group(1))
        minor = int(m.group(2) or 0)
        return (major, minor)

    sonnets: list[tuple[tuple[int, int], str]] = []
    for mid in model_ids:
        v = _sonnet_ver(mid)
        if v:
            sonnets.append((v, mid))
    if sonnets:
        sonnets.sort(key=lambda x: x[0], reverse=True)
        return sonnets[0][1]

    if "gpt-4.1" in model_ids:
        return "gpt-4.1"

    return model_ids[0] if model_ids else MODEL


async def _list_model_ids_async(client: CopilotClient) -> list[str]:
    """Copilot SDK から利用可能なモデルIDを取得する。"""
    models = await client.list_models()
    ids: list[str] = []
    for m in models:
        mid = getattr(m, "id", None)
        if isinstance(mid, str) and mid.strip():
            ids.append(mid.strip())
    return ids

# Microsoft Docs MCP サーバー設定
# learn.microsoft.com/api/mcp を HTTP MCP として SDK セッションに接続
MCP_MICROSOFT_DOCS: dict[str, Any] = {
    "type": "http",
    "url": "https://learn.microsoft.com/api/mcp",
    "tools": ["*"],
}


# ============================================================
# システムプロンプト（言語対応）
# ============================================================


def _system_prompt_review() -> str:
    """リソースレビュー用システムプロンプト（言語対応）。"""
    if get_language() == "en":
        return """\
You are an Azure infrastructure review expert.
The user will provide a list of Azure resources obtained via Azure Resource Graph.

Review from the following perspectives and summarize concisely:

1. **Architecture Overview** — Infer the system purpose in 2-3 lines
2. **Resource Configuration** — Redundancy, HA setup, missing resources
3. **Security** — Presence of NSG, Key Vault, Private Endpoint
4. **Cost Optimization** — Seemingly unnecessary resources (e.g. duplicate NetworkWatcher)
5. **Diagram Hints** — Grouping suggestions

Respond in Markdown, keep the total under 500 words.
"""
    return """\
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


def _caf_security_guidance() -> str:
    """セキュリティガイダンス（言語対応）。"""
    if get_language() == "en":
        return """
## Compliance Frameworks

Recommendations must be based on these Microsoft official frameworks:
- **Cloud Adoption Framework (CAF)** — Security Baseline
- **Well-Architected Framework (WAF)** — Security Pillar
- **Azure Security Benchmark v3 (ASB)**
- **Microsoft Defender for Cloud** recommendations

## Environment-Specific Analysis

Read the provided resource list and security data carefully, and point out issues specific to THIS environment:
- Reference actual resource names and types in your comments
- Write "In this environment, X is Y, therefore Z should be done" — not generic advice
- Identify VMs without NSG, exposed Public IPs, unused Key Vault, missing Private Endpoints by concrete resource name
- If Secure Score is low, specify what improvements would raise the score

## Microsoft Learn Documentation Search

The microsoft_docs_search tool is available. Use it as follows:
1. Search for security best practices related to detected resource types
2. Search for Defender recommendation remediation documentation
3. Add search result URLs as "📚 Reference" to each recommendation

## Output Rules
- Classify severity as Critical / High / Medium / Low
- Attach official documentation in the format "Reference: [CAF Security Baseline](URL)" to each recommendation
- Do not comment on resource types that do not exist in this environment

## Tone (customer-aligned)

- Start by acknowledging what's already done well in this environment (if any).
- Use constructive, supportive wording (avoid blaming language).
- When recommending changes, present options and trade-offs (cost, effort, risk).
- Prefer actionable next steps: who should do what, and what to validate.
- If business context is unclear, state assumptions explicitly and keep them reasonable.
"""
    return """
## 準拠フレームワーク

推奨事項は以下の Microsoft 公式フレームワークに基づくこと:
- **Cloud Adoption Framework (CAF)** — セキュリティベースライン
- **Well-Architected Framework (WAF)** — Security Pillar
- **Azure Security Benchmark v3 (ASB)**
- **Microsoft Defender for Cloud** 推奨事項

## 環境固有の分析指示

提供されたリソース一覧とセキュリティデータをよく読み、この環境固有の問題を指摘すること:
- 実際に存在するリソース名・タイプを具体的に挙げてコメントする
- 「一般論」でなく「この環境では○○が△△だから□□すべき」と書く
- NSG未設定の VM、Public IP 露出、Key Vault 未使用、Private Endpoint 未構成などを具体的リソース名で指摘
- セキュアスコアが低い場合は、具体的に何を改善すればスコアが上がるか言及

## Microsoft Learn ドキュメント検索

microsoft_docs_search ツールが利用可能です。以下のように活用してください:
1. 検出したリソースタイプに関連するセキュリティベストプラクティスを検索
2. Defender 推奨事項の修復手順ドキュメントを検索
3. 検索結果の URL を「📚 参考」として各推奨事項に付与

## 出力ルール
- 深刻度は Critical / High / Medium / Low で分類
- 各推奨事項に「根拠: [CAF Security Baseline](URL)」の形式で公式ドキュメントを付与
- 環境に存在しないリソースについての指摘はしない

## トーン（顧客に寄り添う）

- まず、この環境で「できている点」を短く認める（該当があれば）。
- 責める表現は避け、建設的・支援的な言い回しにする。
- 推奨は一択にせず、コスト/工数/リスクのトレードオフを示す。
- 「次のアクション」を具体的に（誰が・何を・何を確認するか）。
- 顧客の目的が不明な場合は、前提を明記して控えめに推測する。
"""


def _system_prompt_security_base() -> str:
    """セキュリティレポート用システムプロンプト（言語対応）。"""
    guidance = _caf_security_guidance()
    if get_language() == "en":
        return f"""\
You are an Azure security audit expert.
You will be provided with Azure Security Center / Microsoft Defender for Cloud data and the actual Azure environment resource list.

Your report comments must be **specific findings for this particular environment** based on the provided data.
Prioritize specificity: "Resource X in this environment is Y, therefore Z should be done" — not generic advice.
Output in English Markdown format, using tables and lists for readability.
{guidance}
"""
    return f"""\
あなたは Azure セキュリティ監査の専門家です。
Azure Security Center / Microsoft Defender for Cloud のデータと、実際の Azure 環境のリソース一覧が提供されます。

レポートのコメントは、提供データを読み解いた上で「この環境固有の具体的な指摘」を書いてください。
一般論ではなく、「この環境の ○○ は △△ だから □□ すべき」という具体性を最優先してください。
日本語の Markdown 形式で、表やリストを活用して読みやすく。
{guidance}
"""


def _caf_cost_guidance() -> str:
    """コストガイダンス（言語対応）。"""
    if get_language() == "en":
        return """
## Compliance Frameworks

Recommendations must be based on these Microsoft official frameworks:
- **Cloud Adoption Framework (CAF)** — Cost Management best practices
- **Well-Architected Framework (WAF)** — Cost Optimization Pillar / Checklist
- **FinOps Framework** — Cloud cost optimization practices
- **Azure Advisor** — Cost recommendations

## Environment-Specific Analysis

Read the provided cost data and resource list carefully, and point out issues specific to THIS environment:
- Name top-cost resources explicitly, mention SKU downgrade or reservation purchase opportunities
- For resources with Advisor recommendations, provide specific savings amounts and remediation steps
- Write "Resource X in this environment costs $Y/month; doing Z would save $W" — not generic advice
- Identify unused or underutilized resources by name and recommend stopping/deleting
- If resources lack tags, flag this from a FinOps cost allocation perspective

## Microsoft Learn Documentation Search

The microsoft_docs_search tool is available. Use it as follows:
1. Search for optimization documentation related to detected cost issues
2. Search for resource-type-specific pricing guidance (e.g. "Azure SQL cost optimization")
3. Add search result URLs as "📚 Reference" to each recommendation

## Output Rules
- Attach official documentation in the format "Reference: [WAF Cost Optimization](URL)" to each recommendation
- Include currency symbols with amounts, use tables for readability
- Do not comment on resource types that do not exist in this environment

## Tone (customer-aligned)

- Highlight good practices found (e.g., tags, reservations, budgets) before pointing out gaps.
- Be sensitive to operational constraints (e.g., production workloads, compliance).
- Separate **Quick wins** (low effort) and **Strategic changes** (higher effort).
- Avoid recommending deletion when uncertainty is high; suggest validation steps first.
"""
    return """
## 準拠フレームワーク

推奨事項は以下の Microsoft 公式フレームワークに基づくこと:
- **Cloud Adoption Framework (CAF)** — コスト管理ベストプラクティス
- **Well-Architected Framework (WAF)** — Cost Optimization Pillar / チェックリスト
- **FinOps Framework** — クラウドコスト最適化の実践
- **Azure Advisor** — コスト推奨事項

## 環境固有の分析指示

提供されたコストデータとリソース一覧をよく読み、この環境固有の問題を指摘すること:
- コスト上位のリソースを具体名で挙げ、SKU ダウングレードや予約購入の可能性を言及
- Advisor 推奨があるリソースは具体的な削減額と対応方法を記載
- 「一般論」ではなく「この環境の ○○ は 月額 X円 かかっており、△△ すれば Y 円 削減可能」と書く
- 未使用・低稼働リソースは具体名を挙げて停止・削除を推奨
- タグ未設定のリソースがあれば、FinOps の「コスト配分」の観点で指摘

## Microsoft Learn ドキュメント検索

microsoft_docs_search ツールが利用可能です。以下のように活用してください:
1. 検出したコスト問題に関連する最適化ドキュメントを検索
2. リソースタイプ固有の価格ガイダンスを検索（例: 「Azure SQL cost optimization」）
3. 検索結果の URL を「📚 参考」として各推奨事項に付与

## 出力ルール
- 各推奨事項に「根拠: [WAF Cost Optimization](URL)」の形式で公式ドキュメントを付与
- 金額は通貨記号付きで、表を活用して読みやすく
- 環境に存在しないリソースについての指摘はしない

## トーン（顧客に寄り添う）

- できている運用（タグ、予約、予算など）があれば先に評価する。
- 本番/コンプライアンス等の制約を前提に、無理のない提案にする。
- **Quick win**（低工数）と **Strategic**（中長期）を分けて提案する。
- 不確実性が高いものは即削除推奨せず、検証手順→判断の順にする。
"""


def _system_prompt_cost_base() -> str:
    """コストレポート用システムプロンプト（言語対応）。"""
    guidance = _caf_cost_guidance()
    if get_language() == "en":
        return f"""\
You are an Azure cost optimization expert.
You will be provided with Azure Cost Management data (cost by service / by RG) and the actual Azure environment resource list.

Your report comments must be **specific findings for this particular environment** based on the provided data.
Prioritize specificity: "Resource X in this environment is Y, therefore Z should be done" — not generic advice.
Output in English Markdown format, using tables and lists for readability.
{guidance}
"""
    return f"""\
あなたは Azure コスト最適化の専門家です。
Azure Cost Management のデータ（サービス別・RG別コスト）と、実際の Azure 環境のリソース一覧が提供されます。

レポートのコメントは、提供データを読み解いた上で「この環境固有の具体的な指摘」を書いてください。
一般論ではなく、「この環境の ○○ は △△ だから □□ すべき」という具体性を最優先してください。
日本語の Markdown 形式で、表やリストを活用して読みやすく。
{guidance}
"""



# ============================================================
# CopilotClient キャッシュ（モジュール単位で再利用）
# ============================================================

_cached_client: CopilotClient | None = None
_cached_client_started: bool = False


async def _get_or_create_client(
    on_status: Optional[Callable[[str], None]] = None,
) -> CopilotClient:
    """CopilotClient をキャッシュして返す。

    連続レポート生成時に毎回接続→停止のオーバーヘッドを排除する。
    _bg_lock で _cached_client へのアクセスを保護する。
    """
    global _cached_client, _cached_client_started
    log = on_status or (lambda s: None)

    with _bg_lock:
        if _cached_client and _cached_client_started:
            log("Copilot SDK: キャッシュ済みクライアントを再利用")
            return _cached_client

    log("Copilot SDK に接続中...")
    client_opts: dict[str, Any] = {
        "auto_restart": True,
    }
    cli = copilot_cli_path()
    if cli:
        client_opts["cli_path"] = cli
        log(f"CLI path: {cli}")

    new_client = CopilotClient(client_opts)
    await new_client.start()

    with _bg_lock:
        _cached_client = new_client
        _cached_client_started = True

    log("Copilot SDK 接続 OK")
    return new_client


async def shutdown_cached_client() -> None:
    """アプリケーション終了時にキャッシュ済みクライアントを停止。"""
    global _cached_client, _cached_client_started
    if _cached_client and _cached_client_started:
        try:
            await _cached_client.stop()
        except Exception:
            pass
        finally:
            _cached_client = None
            _cached_client_started = False


def shutdown_sync() -> None:
    """同期版シャットダウン（tkinter の on_close から呼ぶ用）。"""
    global _bg_loop, _bg_thread
    # 1. CopilotClient を停止
    loop = _bg_loop
    if loop and not loop.is_closed():
        try:
            future = asyncio.run_coroutine_threadsafe(shutdown_cached_client(), loop)
            future.result(timeout=5)
        except Exception:
            pass
        # 2. イベントループを停止
        loop.call_soon_threadsafe(loop.stop)
    _bg_loop = None
    _bg_thread = None


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
        model_id: str | None = None,
    ) -> None:
        self._on_delta = on_delta or (lambda s: print(s, end="", flush=True))
        self._on_status = on_status or (lambda s: print(f"[reviewer] {s}"))
        self._model_id = model_id

    async def review(self, resource_text: str) -> str | None:
        """リソースサマリをレビューし、結果テキストを返す。"""
        if get_language() == "en":
            prompt = (
                "Please review the following Azure resource list:\n\n"
                f"```\n{resource_text}\n```"
            )
        else:
            prompt = (
                "以下のAzureリソース一覧をレビューしてください:\n\n"
                f"```\n{resource_text}\n```"
            )
        return await self.generate(prompt, _system_prompt_review(), model_id=self._model_id)

    async def generate(self, prompt: str, system_prompt: str, *, model_id: str | None = None) -> str | None:
        """汎用: 任意のプロンプトとシステムプロンプトで生成。

        SDK 推奨パターン:
          - session.idle イベント + asyncio.Event で完了待ち
          - hooks.on_error_occurred でリトライ制御
          - reasoning_delta 対応
          - on_pre_tool_use で読み取り専用ツールのみ許可
        """
        # 言語指示を system prompt 末尾に追加
        lang_instruction = _t("ai.output_language")
        system_prompt = system_prompt.rstrip() + "\n\n" + lang_instruction + "\n"

        try:
            # 1. SDK 接続（キャッシュ済みクライアントを再利用）
            client = await _get_or_create_client(on_status=self._on_status)

            # 2. セッション作成（hooks パターン + MCP サーバー）
            session_cfg: dict[str, Any] = {
                "model": model_id or self._model_id or MODEL,
                "streaming": True,
                "on_permission_request": _approve_all,
                "system_message": system_prompt,
                "hooks": {
                    "on_pre_tool_use": _on_pre_tool_use,
                    "on_error_occurred": _make_error_handler(self._on_status),
                },
            }

            # Microsoft Docs MCP をセッションに接続
            # learn.microsoft.com/api/mcp → AI が自律的にドキュメント検索可能
            session_cfg["mcp_servers"] = {
                "microsoftdocs": MCP_MICROSOFT_DOCS,
            }
            self._on_status("Microsoft Docs MCP を接続中...")

            session = await client.create_session(session_cfg)

            # 3. ストリーミングイベント収集（session.idle パターン）
            collected: list[str] = []
            done = asyncio.Event()
            reasoning_notified = False

            def _handler(event: Any) -> None:
                etype = event.type.value if hasattr(event.type, "value") else str(event.type)

                if etype == "assistant.message_delta":
                    delta = getattr(event.data, "delta_content", "")
                    if delta:
                        collected.append(delta)
                        self._on_delta(delta)

                elif etype == "assistant.reasoning_delta":
                    # 推論過程（chain-of-thought）をそのまま表示しない
                    nonlocal reasoning_notified
                    if not reasoning_notified:
                        reasoning_notified = True
                        self._on_status("AI 思考中...")

                elif etype == "assistant.message":
                    # 最終メッセージ（streaming の有無に関わらず送信される）
                    content = getattr(event.data, "content", "")
                    if content and not collected:
                        collected.append(content)

                elif etype == "session.idle":
                    # セッション完了シグナル
                    done.set()

            session.on(_handler)

            # 4. 送信（send + idle 待ち — SDK 推奨パターン）
            self._on_status("AI 処理実行中...")
            await session.send({"prompt": prompt})

            # タイムアウト付きで idle 待ち
            try:
                await asyncio.wait_for(done.wait(), timeout=SEND_TIMEOUT)
            except asyncio.TimeoutError:
                self._on_status(f"AI 処理タイムアウト（{SEND_TIMEOUT}秒）")

            result = "".join(collected) if collected else None

            # 5. セッションのみ破棄（クライアントはキャッシュ維持）
            await session.destroy()

            return result

        except Exception as e:
            self._on_status(f"AI レビューエラー: {e}")
            # エラー時はキャッシュを無効化（次回再作成）
            _invalidate_cached_client()
            return None


def _invalidate_cached_client() -> None:
    """キャッシュ済みクライアントをスレッドセーフに無効化する。"""
    global _cached_client, _cached_client_started
    with _bg_lock:
        _cached_client = None
        _cached_client_started = False


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
    model_id: str | None = None,
) -> str | None:
    """同期的にAIレビューを実行して結果を返す。"""
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status, model_id=model_id)
    return _run_async(reviewer.review(resource_text))


def run_security_report(
    security_data: dict,
    resource_text: str,
    template: dict | None = None,
    custom_instruction: str = "",
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    model_id: str | None = None,
    subscription_info: str = "",
) -> str | None:
    """セキュリティレポートを生成。"""
    resource_types = _extract_resource_types(resource_text)
    data_sections: list[tuple[str, str, dict]] = [
        ("Security Data", "セキュリティデータ", security_data),
    ]
    return _run_report(
        base_system_prompt=_system_prompt_security_base(),
        report_type="security",
        data_sections=data_sections,
        resource_text=resource_text,
        resource_types=resource_types,
        search_queries_fn=security_search_queries,
        template=template,
        custom_instruction=custom_instruction,
        on_delta=on_delta,
        on_status=on_status,
        model_id=model_id,
        subscription_info=subscription_info,
    )


def run_cost_report(
    cost_data: dict,
    advisor_data: dict,
    template: dict | None = None,
    custom_instruction: str = "",
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    resource_types: list[str] | None = None,
    model_id: str | None = None,
    subscription_info: str = "",
) -> str | None:
    """コストレポートを生成。"""
    data_sections: list[tuple[str, str, dict]] = [
        ("Cost Data", "コストデータ", cost_data),
        ("Advisor Recommendations", "Advisor 推奨事項", advisor_data),
    ]
    return _run_report(
        base_system_prompt=_system_prompt_cost_base(),
        report_type="cost",
        data_sections=data_sections,
        resource_text=None,
        resource_types=resource_types or [],
        search_queries_fn=cost_search_queries,
        template=template,
        custom_instruction=custom_instruction,
        on_delta=on_delta,
        on_status=on_status,
        model_id=model_id,
        subscription_info=subscription_info,
    )


# ============================================================
# 共通レポート生成ヘルパ
# ============================================================

def _run_report(
    *,
    base_system_prompt: str,
    report_type: str,
    data_sections: list[tuple[str, str, dict]],
    resource_text: str | None,
    resource_types: list[str],
    search_queries_fn: Callable,
    template: dict | None,
    custom_instruction: str,
    on_delta: Optional[Callable[[str], None]],
    on_status: Optional[Callable[[str], None]],
    model_id: str | None,
    subscription_info: str = "",
) -> str | None:
    """security / cost レポート の共通ロジック。"""
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status, model_id=model_id)
    log = on_status or (lambda s: None)

    # テンプレート → システムプロンプト
    if template:
        tmpl_instruction = build_template_instruction(template, custom_instruction)
        system_prompt = base_system_prompt + "\n\n" + tmpl_instruction
    else:
        system_prompt = base_system_prompt
        if custom_instruction.strip():
            system_prompt += f"\n\n### ユーザーからの追加指示:\n{custom_instruction.strip()}"

    # Microsoft Docs 参照
    queries = search_queries_fn(resource_types)
    docs_block = enrich_with_docs(
        queries, report_type=report_type,
        resource_types=resource_types, on_status=log,
    )
    if not docs_block:
        log("Microsoft Docs: generating report without references"
            if get_language() == "en"
            else "Microsoft Docs 参照なしでレポートを生成します")

    # プロンプト組み立て
    en = get_language() == "en"
    parts: list[str] = []

    # サブスクリプション情報（タイトルに使えるように）
    if subscription_info:
        if en:
            parts.append(f"**Target Subscription**: {subscription_info}\n\n")
        else:
            parts.append(f"**対象サブスクリプション**: {subscription_info}\n\n")

    if en:
        parts.append(
            f"Generate a {report_type} report for the following Azure environment.\n\n"
            "**Important**: Read the data below carefully and provide environment-specific findings.\n"
            "Reference specific resource names and types; avoid generic advice.\n"
            "Use microsoft_docs_search tool to find relevant docs and cite URLs.\n"
        )
    else:
        parts.append(
            f"以下の Azure 環境の{report_type}レポートを生成してください。\n\n"
            "**重要**: 以下のデータをよく読み、この環境固有の具体的な指摘を書いてください。\n"
            "リソース名やタイプを具体的に挙げてコメントし、「一般論」は避けてください。\n"
            "microsoft_docs_search ツールで関連ドキュメントを検索し、引用 URL を付けてください。\n"
        )

    for en_title, ja_title, data in data_sections:
        title = en_title if en else ja_title
        parts.append(f"\n## {title}\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```\n")

    if resource_text:
        rt_title = "Resource List" if en else "リソース一覧"
        parts.append(f"\n## {rt_title}\n```\n{resource_text}\n```")

    if docs_block:
        parts.append(docs_block)

    prompt = "".join(parts)
    return _run_async(reviewer.generate(prompt, system_prompt, model_id=model_id))


def list_available_model_ids_sync(
    on_status: Optional[Callable[[str], None]] = None,
    timeout: float = 15,
) -> list[str]:
    """利用可能モデルID一覧を同期的に取得する。

    GUI のバックグラウンドスレッドから呼べるように同期化。
    *timeout* 秒で接続/取得できなければ空リストを返す。
    """

    async def _inner() -> list[str]:
        client = await _get_or_create_client(on_status=on_status)
        return await _list_model_ids_async(client)

    try:
        loop = _get_bg_loop()
        future = asyncio.run_coroutine_threadsafe(_inner(), loop)
        return list(future.result(timeout=timeout))
    except Exception:
        return []


# ============================================================
# 永続イベントループ（CopilotClient のライフサイクルに合わせる）
# ============================================================

_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None
_bg_lock = threading.Lock()


def _get_bg_loop() -> asyncio.AbstractEventLoop:
    """CopilotClient 専用の永続イベントループを返す。

    asyncio.run() は毎回ループを閉じてしまい、キャッシュ済み
    CopilotClient が 'Event loop is closed' でクラッシュするため、
    専用スレッドで run_forever する永続ループを利用する。
    """
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is not None and not _bg_loop.is_closed():
            return _bg_loop
        _bg_loop = asyncio.new_event_loop()
        _bg_thread = threading.Thread(
            target=_bg_loop.run_forever, daemon=True, name="copilot-event-loop"
        )
        _bg_thread.start()
        return _bg_loop


def _run_async(coro: Any) -> Any:
    """コルーチンを永続イベントループ上で同期的に実行する。

    バックグラウンドスレッド（tkinter ワーカー）から呼ぶ前提。
    CopilotClient は同一ループ上に留まるためキャッシュが安全に使える。
    """
    loop = _get_bg_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=SEND_TIMEOUT + 30)

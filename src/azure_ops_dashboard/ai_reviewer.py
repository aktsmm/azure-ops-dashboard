"""Step10: Azure Ops Dashboard — AI レビュー & レポート (GitHub Copilot SDK)

Collect したリソース一覧を Copilot SDK に送り、
構成のレビュー結果や各種レポート（日本語）をストリーミングで返す。
テンプレート設定とカスタム指示に対応。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import threading
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

_COPILOT_IMPORT_ERROR: str | None = None
try:
    from copilot import CopilotClient  # type: ignore
except Exception as exc:
    CopilotClient = None  # type: ignore[assignment]
    _COPILOT_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

from .app_paths import (
    bundled_templates_dir,
    copilot_cli_path,
    ensure_user_dirs,
    template_search_dirs,
)
from .docs_enricher import (
    cost_search_queries,
    enrich_with_docs,
    security_search_queries,
)
from .i18n import t as _t, get_language


_TOOL_INPUT_BLOCK_RE = re.compile(
    r"<tool_input\b[^>]*>\s*(.*?)\s*</tool_input>",
    re.IGNORECASE | re.DOTALL,
)

_JSON_DECODER = json.JSONDecoder()


def _looks_like_markdown_report(text: str) -> bool:
    if not text:
        return False
    trimmed = text.strip()
    if not trimmed:
        return False
    # Integrated reports are expected to have headings.
    return any(l.lstrip().startswith("#") for l in trimmed.splitlines() if l.strip())


def _extract_jsonish_string_field(payload: str, field_name: str) -> str | None:
    """壊れた JSON からでも field の文字列値をベストエフォートで抜き出す。

    典型例:
      {"filePath":"x.md","content":"# Title\n..."}

    モデルが JSON の文字列中改行をエスケープせずに出してしまうと json.loads が失敗するため、
    `"content":"..."}` のパターンを優先して抜き取る。
    """
    if not payload or not field_name:
        return None

    def _unescape_backslash_sequences(s: str) -> str:
        buf: list[str] = []
        escape = False
        for ch in s:
            if escape:
                if ch == "n":
                    buf.append("\n")
                elif ch == "r":
                    buf.append("\r")
                elif ch == "t":
                    buf.append("\t")
                elif ch == '"':
                    buf.append('"')
                elif ch == "\\":
                    buf.append("\\")
                else:
                    buf.append(ch)
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            buf.append(ch)
        if escape:
            buf.append("\\")
        return "".join(buf)

    # 1) content がオブジェクト末尾（"..." }）にあるケースを優先（最も成功率が高い）
    tail_pat = re.compile(
        rf"[\"']{re.escape(field_name)}[\"']\s*:\s*\"(.*)\"\s*}}\s*$",
        re.IGNORECASE | re.DOTALL,
    )
    m = tail_pat.search(payload.strip())
    if m:
        s = m.group(1)
        if s and s.strip():
            return _unescape_backslash_sequences(s)

    # 2) それ以外: "field":"..." を 1 つ分だけ state-machine で抜く（途中に未エスケープの " があると打ち切り）
    head_pat = re.compile(
        rf"[\"']{re.escape(field_name)}[\"']\s*:\s*\"",
        re.IGNORECASE,
    )
    m2 = head_pat.search(payload)
    if not m2:
        return None

    i = m2.end()
    buf: list[str] = []
    escape = False
    while i < len(payload):
        ch = payload[i]
        if escape:
            if ch == "n":
                buf.append("\n")
            elif ch == "r":
                buf.append("\r")
            elif ch == "t":
                buf.append("\t")
            elif ch == '"':
                buf.append('"')
            elif ch == "\\":
                buf.append("\\")
            else:
                buf.append(ch)
            escape = False
            i += 1
            continue

        if ch == "\\":
            escape = True
            i += 1
            continue

        if ch == '"':
            break

        buf.append(ch)
        i += 1

    out = "".join(buf)
    return out if out.strip() else None


def _best_effort_json_load(payload: str) -> Any | None:
    """JSON をベストエフォートで parse する。

    - 先頭に余計な文字がある/末尾にゴミが付くケースでも、先頭の JSON を拾える範囲で拾う。
    - 失敗したら None。
    """
    if not payload:
        return None
    s = payload.strip()
    if not s:
        return None

    # Common fence wrappers (best-effort)
    if s.startswith("```"):
        # ```json\n{...}\n```
        first_nl = s.find("\n")
        last_fence = s.rfind("```")
        if first_nl >= 0 and last_fence > first_nl:
            inner = s[first_nl + 1:last_fence].strip()
            if inner:
                s = inner

    try:
        return json.loads(s)
    except Exception:
        pass

    try:
        obj, _idx = _JSON_DECODER.raw_decode(s)
        return obj
    except Exception:
        return None


def _score_markdown_candidate(text: str) -> int:
    if not text:
        return 0
    trimmed = text.strip()
    if not trimmed:
        return 0

    score = 0
    head_lines = trimmed.splitlines()[:30]
    heading_count = sum(1 for l in head_lines if l.lstrip().startswith("#"))
    score += min(40, heading_count * 8)
    if "\n|" in trimmed and "|" in trimmed:
        score += 10
    score += min(40, len(trimmed) // 400)
    lowered = trimmed.lower()
    if "<tool_call" in lowered or "<tool_calls" in lowered or "<tool_input" in lowered:
        score -= 50
    return score


def _extract_markdown_from_tool_input(text: str) -> str | None:
    """tool-call trace から Markdown 本文を救出する（ベストエフォート）。

    モデル出力が `<tool_call>...<tool_input>{"content": "..."}</tool_input>...` の形式
    になった場合、ツールブロックを丸ごと除去すると本文も消えるため、content を抽出して返す。
    """
    if not text or "<tool_input" not in text:
        return None

    candidates: list[str] = []
    for m in _TOOL_INPUT_BLOCK_RE.finditer(text):
        payload = (m.group(1) or "").strip()
        if not payload:
            continue
        obj = _best_effort_json_load(payload)
        if obj is None:
            # Broken JSON fallback: try to extract a plausible Markdown string.
            for key in ("content", "markdown", "text"):
                extracted = _extract_jsonish_string_field(payload, key)
                if extracted and extracted.strip():
                    candidates.append(extracted)
                    break
            else:
                # Some models put raw Markdown directly inside <tool_input>.
                if _looks_like_markdown_report(payload):
                    candidates.append(payload)
            continue

        if isinstance(obj, dict):
            for key in ("content", "markdown", "text"):
                content = obj.get(key)
                if isinstance(content, str) and content.strip():
                    candidates.append(content)
                    break
            else:
                args = obj.get("arguments")
                if isinstance(args, dict):
                    for key in ("content", "markdown", "text"):
                        content2 = args.get(key)
                        if isinstance(content2, str) and content2.strip():
                            candidates.append(content2)
                            break

    if not candidates:
        return None
    return max(candidates, key=_score_markdown_candidate)


def _sanitize_ai_markdown(text: str) -> str:
    """AI 出力に混入しがちなメタ情報を除去し、レポート本文に寄せる。"""
    if not text:
        return text

    extracted = _extract_markdown_from_tool_input(text)
    # Quality gate: extracted must be substantial (not just thinking preamble)
    # to prevent adopting a short "Let me examine..." snippet over the full output.
    if extracted and _looks_like_markdown_report(extracted):
        ex_lines = [l for l in extracted.splitlines() if l.strip()]
        ex_headings = sum(1 for l in ex_lines if l.lstrip().startswith("#"))
        if len(extracted.strip()) >= 300 and ex_headings >= 2:
            if _score_markdown_candidate(extracted) > _score_markdown_candidate(text):
                text = extracted

    lines = text.splitlines()
    sanitized: list[str] = []
    skip_tag: str | None = None
    in_code_fence = False

    tool_trace_tags_always = (
        "tool_call",
        "tool_call_result",
        "tool_result",
        "tool_calls",
        "tool_results",
        "tool_input",
        "tool_name",
        "FileReadResult",
        "FileWriteResult",
    )
    # NOTE:
    # These tags are too generic to treat as multi-line blocks. If we set skip_tag on an
    # opening tag without a matching close tag (which happens in real model outputs), we can
    # accidentally drop the entire report and cause downstream failures like "no_heading".
    # For these, we only drop the tag lines (outside code fences) and keep the rest.
    tool_trace_line_tags_outside_fence = (
        "parameters",
        "parameter",
        "result",
    )

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            sanitized.append(line)
            continue

        # Skip inside tool-trace blocks (also inside code fences).
        if skip_tag is not None:
            if re.search(rf"</\s*{re.escape(skip_tag)}\s*>", stripped, re.IGNORECASE):
                skip_tag = None
            continue

        # 1) Drop multi-line tool-trace blocks (also inside code fences).
        start_tag: str | None = None
        for tag in tool_trace_tags_always:
            if re.search(rf"<\s*{re.escape(tag)}\b", stripped, re.IGNORECASE):
                start_tag = tag
                break
        if start_tag is not None:
            # Handle "<tag>... </tag>" on the same line safely.
            if re.search(rf"</\s*{re.escape(start_tag)}\s*>", stripped, re.IGNORECASE):
                continue
            skip_tag = start_tag
            continue

        # 2) Drop generic tool-ish tag lines (outside code fences) but do NOT enter skip mode.
        #    This prevents swallowing the report when the close tag is missing.
        if not in_code_fence:
            for tag in tool_trace_line_tags_outside_fence:
                if re.search(rf"<\s*/?\s*{re.escape(tag)}\b", stripped, re.IGNORECASE):
                    # Only drop the tag line itself; keep the rest of the report.
                    start_tag = tag
                    break
            if start_tag is not None:
                continue

        if stripped.startswith("Tool summary:"):
            continue

        sanitized.append(line)

    out = "\n".join(sanitized).strip()

    # Reconsider: if line-by-line result is too short but we had a substantial extracted
    # candidate that failed the strict quality gate, prefer it over a near-empty result.
    # Only adopt if extracted is also at least as long (avoids replacing useful post-tool
    # text with a short "thinking" snippet from tool_input).
    if extracted and len(out.strip()) < 300:
        ex_score = _score_markdown_candidate(extracted)
        out_score = _score_markdown_candidate(out)
        if ex_score > out_score and len(extracted.strip()) >= len(out.strip()):
            out = extracted.strip()

    # 見出し(#)開始に寄せる（ただし Target metadata は許容）
    out_lines = out.splitlines()
    heading_idx = next((i for i, l in enumerate(out_lines) if l.lstrip().startswith("#")), None)
    if heading_idx is not None and heading_idx > 0:
        pre = [l.strip() for l in out_lines[:heading_idx] if l.strip()]
        allowed_prefixes = (
            "**Target Subscription**:",
            "**Target Resource Group**:",
            "**対象サブスクリプション**:",
            "**対象リソースグループ**:",
            "**サブスクリプション**:",
            "**リソースグループ**:",
        )
        if not (pre and all(any(p.startswith(ap) for ap in allowed_prefixes) for p in pre)):
            out = "\n".join(out_lines[heading_idx:]).strip()

    return out


def _system_prompt_drawio() -> str:
    """draw.io 図生成（mxfile XML）用システムプロンプト。

    注意: drawio 生成では Markdown を要求すると壊れやすいので、
    `AIReviewer.generate(..., append_language_instruction=False)` で呼ぶこと。
    """

    # drawio_writer のアイコンマッピングを AI に渡して、タイプ→アイコンの一貫性を上げる。
    # 失敗しても図生成自体は可能なので、import は遅延 + ベストエフォート。
    icons: dict[str, str] = {}
    try:
        from . import drawio_writer

        icons = dict(getattr(drawio_writer, "_TYPE_ICONS", {}) or {})
    except Exception:
        icons = {}

    icons_json = json.dumps(icons, ensure_ascii=False, indent=2)

    if get_language() == "en":
        return f"""\
You are an expert draw.io (diagrams.net) diagram generator for Azure environments.

The user will provide PREPROCESSED Azure resources and relationships as JSON.
Note: Noise resources have been filtered and similar resources grouped BEFORE you receive the data.
Your task is to output a SINGLE valid draw.io mxfile XML — compact, readable, and professional.

═══ CRITICAL OUTPUT RULES ═══
- Output ONLY XML. No Markdown. No code fences. No explanations.
- The output must contain exactly one <mxfile> root element.

═══ DO NOT OUTPUT AN EMPTY DIAGRAM ═══
- You must create vertex nodes for ALL provided input nodes (use their cellId).
- Do not output placeholder comments like "content cells here".

═══ XML STRUCTURE ═══
- Include <mxCell id=\"0\"/> and <mxCell id=\"1\" parent=\"0\"/>.
- Nodes: <mxCell vertex=\"1\"> with child <mxGeometry ... as=\"geometry\"/>.
- Edges: <mxCell edge=\"1\" source=... target=...> referring to existing node ids.
- All mxCell ids must be UNIQUE.

═══ ID RULES (VERY IMPORTANT) ═══
- For input nodes: use node.cellId as the mxCell id.
- For input edges: use source="sourceCellId" target="targetCellId".
- Do not invent ids for resources.
- Container/title ids must not collide with node ids (use "c_" or "t_" prefix).

═══ ICON RULES ═══
- Azure icons: style='shape=image;aspect=fixed;image=img/lib/azure2/.../*.svg;...'
- NEVER use mxgraph.azure.* shapes → REJECTED.
- NEVER use http/https image URLs.
- Type→icon mapping:
```json
{icons_json}
```

═══ LAYOUT (CRITICAL — this is the most important section) ═══

HIERARCHY (use swimlane containers, style="swimlane;..."):
  1. Azure (outermost) → 2. Region → 3. Resource Group → 4. VNet → 5. Subnet
  Omit levels with only 1 child (inline into parent).

CONTAINER SIZING:
  - Leaf nodes (icons): width=50 height=50
  - "+N more" summary labels: width=120 height=30, fontSize=10, italic
  - Subnet: pad 20px; VNet: pad 30px; RG: pad 40px

MULTI-COLUMN GRID:
  - Arrange containers/nodes in 2-4 column grids (NOT a single vertical stack).
  - For regions: place side-by-side if content is small, stack if large.
  - Small regions (≤3 nodes): 200px wide. Large regions: up to 800px wide.

RESOURCE GROUP GROUPING:
  - Group nodes by resourceGroup within each region.
  - Use a dashed-border container (dashed=1) for each RG.
  - Label: "RG: <name>" with fontSize=11.

SIMILAR-RESOURCE GROUPS (nodes with name like "prefix... (+N more)"):
  - These are already grouped by preprocessing. Display the summary node as-is.
  - Place the summary node next to the representative nodes in a compact row.

LABELS:
  - Truncate labels over 22 chars: keep first 10 + "..." + last 8.
  - Example: "DefaultWorkspace-832c4080-..." → "DefaultWor...080-..."
  - Use verticalLabelPosition=bottom for icon nodes.

CANVAS SIZING:
  - Target: width ≤ 1600px, height ≤ 2000px (compact!).
  - Adjust dynamically: ~100px per node height, ~200px per node width.
  - If nodes > 40: use smaller icons (width=40 height=40) and tighter spacing.

═══ EDGE RULES ═══
- Orthogonal routing: edgeStyle=orthogonalEdgeStyle;rounded=1;
- VNet peering: dashed=1;strokeWidth=2;strokeColor=#0078D4;
- Containment edges (in-subnet, contained-in): OMIT (parent relationship suffices).
- If resource is inside its container, do NOT draw an edge to it.

═══ DATA FIDELITY ═══
- Do not invent resources or relationships.
- If relationships are missing, omit edges rather than guessing.
"""

    return f"""\
あなたは Azure 環境の draw.io (diagrams.net) 図を生成する専門家です。

ユーザーから**前処理済み**の Azure リソースと関係性が JSON で提供されます。
注意: ノイズリソースは除去済み、類似リソースはグループ化済みです。
あなたのタスクは、コンパクトで見やすいプロフェッショナルな mxfile XML を1つ出力することです。

═══ 最重要: 出力ルール ═══
- 出力は XML のみ。Markdown禁止。コードフェンス禁止。説明文禁止。
- 出力は <mxfile> ルート要素を1つだけ含むこと。

═══ 空図の禁止 ═══
- 入力ノード全ての cellId に対応する vertex を必ず生成すること。
- 「content cells here」等のプレースホルダコメントは禁止。

═══ XML 構造 ═══
- <mxCell id=\"0\"/> と <mxCell id=\"1\" parent=\"0\"/> を必ず含める。
- ノード: <mxCell vertex=\"1\"> + 子に <mxGeometry ... as=\"geometry\"/>。
- エッジ: <mxCell edge=\"1\" source=... target=...>、既存ノード id を参照。
- mxCell id は全てユニーク。

═══ ID ルール（最重要） ═══
- 入力ノード: node.cellId を mxCell id として使用。
- 入力エッジ: source="sourceCellId" / target="targetCellId"。
- リソース id を捏造しない。
- コンテナ/タイトル id は "c_" / "t_" プレフィックスで node.cellId と衝突回避。

═══ アイコン ═══
- style に 'shape=image;aspect=fixed;image=img/lib/azure2/.../*.svg;...' を使用。
- shape=mxgraph.azure.* は禁止 → 不合格。
- http/https リモート画像URL 禁止。
- タイプ→アイコン対応表:
```json
{icons_json}
```

═══ レイアウト（最重要 — この図の品質を決める） ═══

【階層構造】swimlane コンテナ使用:
  1. Azure（最外枠）→ 2. Region → 3. Resource Group → 4. VNet → 5. Subnet
  子が1つだけの階層はスキップ（親にインライン展開）。

【コンテナサイズ】
  - リーフノード（アイコン）: width=50 height=50
  - "+N more" サマリ: width=120 height=30, fontSize=10, italic
  - Subnet: 20px余白; VNet: 30px余白; RG: 40px余白

【グリッド配置（縦一列禁止）】
  - コンテナ/ノードは 2～4列のグリッドに配置する。
  - 小さいリージョン（≤3ノード）: 幅200px。大きいリージョン: 最大800px。
  - リージョン同士: 内容が小さければ横並び、大きければ縦方向に配置。

【リソースグループによるグルーピング】
  - 各リージョン内でノードを resourceGroup ごとにまとめる。
  - 破線コンテナ (dashed=1) で RG を囲む。
  - ラベル: "RG: <名前>" fontSize=11。

【類似リソースグループ】（名前が "prefix... (+N more)" のノード）:
  - 前処理でグループ化済み。サマリノードはそのまま表示。
  - 代表ノードの横にコンパクトに並べる。

【ラベル短縮】
  - 22文字超: 先頭10文字 + "..." + 末尾8文字。
  - 例: "DefaultWorkspace-832c4080-..." → "DefaultWor...080-..."
  - アイコンノードは verticalLabelPosition=bottom。

【キャンバスサイズ（コンパクトに！）】
  - 目標: 幅 ≤ 1600px、高さ ≤ 2000px。
  - ノード数に応じて動的調整: ～100px/ノード高、～200px/ノード幅。
  - ノード > 40 の場合: 小アイコン (width=40 height=40) + 間隔を詰める。

═══ エッジ ═══
- 直行ルーティング: edgeStyle=orthogonalEdgeStyle;rounded=1;
- VNet peering: dashed=1;strokeWidth=2;strokeColor=#0078D4;
- 包含エッジ (in-subnet, contained-in): 省略（parent関係で表現済み）。
- リソースがコンテナ内にある場合、それへのエッジは引かない。

═══ データ忠実性 ═══
- リソースや関係性を捏造しない。
- 関係性不足の場合、推測でエッジを引かず省略する。
"""


_MXFILE_RE = re.compile(r"(<mxfile[\s\S]*?</mxfile>)", re.IGNORECASE)


def _extract_mxfile_xml(text: str) -> str | None:
    """モデル出力から <mxfile>...</mxfile> を抽出する（ベストエフォート）。"""
    if not text:
        return None

    s = text.strip()
    # Code fence を剥がす（モデルがルールを破った場合の救済）
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
        s = re.sub(r"\n```$", "", s)
        s = s.strip()

    m = _MXFILE_RE.search(s)
    if m:
        xml = m.group(1).strip()
        # <?xml ...?> が直前にあれば含める
        xml_decl = s.lower().rfind("<?xml", 0, m.start(1))
        if xml_decl != -1:
            return (s[xml_decl:m.end(1)]).strip()
        return xml

    # フォールバック: ルート開始/終了で切り出し
    start = s.lower().find("<mxfile")
    end = s.lower().rfind("</mxfile>")
    if start != -1 and end != -1:
        end2 = end + len("</mxfile>")
        return s[start:end2].strip()

    return None


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


def _make_on_pre_tool_use(
    *,
    on_status: Callable[[str], None],
    run_debug: dict[str, Any],
) -> Callable:
    """観測用の on_pre_tool_use フック（allow/deny を記録）。"""

    async def _hook(input_data: dict, invocation: Any) -> dict:
        tool_name = str(input_data.get("toolName", "") or "")
        tool_args = input_data.get("toolArgs")

        decision = "allow" if tool_name in _ALLOWED_TOOLS else "deny"

        counts = run_debug.setdefault("tool_counts", {})
        key = tool_name or "(unknown)"
        entry = counts.setdefault(key, {"allow": 0, "deny": 0})
        entry[decision] = int(entry.get(decision, 0)) + 1
        run_debug["tool_total"] = int(run_debug.get("tool_total", 0)) + 1

        # docs MCP ツールだけはログにも出す（その他はノイズになりやすいので抑制）
        if tool_name.startswith("microsoft_") or decision == "deny":
            on_status(f"Tool: {tool_name} => {decision}")

        return {
            "permissionDecision": decision,
            "modifiedArgs": tool_args,
        }

    return _hook


def _make_error_handler(
    on_status: Callable[[str], None],
    max_retry: int = 2,
    run_debug: dict[str, Any] | None = None,
) -> Callable:
    """リトライ付きエラーハンドラを生成。"""
    _retry_count: dict[str, int] = {}

    async def _on_error_occurred(input_data: dict, invocation: Any) -> dict:
        ctx = input_data.get("errorContext", "unknown")
        err = input_data.get("error", "")

        if run_debug is not None:
            errors = run_debug.setdefault("errors", [])
            s = str(err)
            errors.append({
                "context": str(ctx),
                "error": (s[:500] + "..." if len(s) > 500 else s),
            })

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


_LAST_RUN_DEBUG_LOCK = threading.Lock()
_LAST_RUN_DEBUG: dict[str, Any] | None = None


def _set_last_run_debug(run_debug: dict[str, Any]) -> None:
    global _LAST_RUN_DEBUG
    with _LAST_RUN_DEBUG_LOCK:
        _LAST_RUN_DEBUG = run_debug


def get_last_run_debug() -> dict[str, Any] | None:
    """直近の Copilot SDK 実行の観測情報（ツール呼び出し等）を返す。

    レポート本文に出す用途ではなく、GUIログ/監査用の input JSON に添付する想定。
    """
    with _LAST_RUN_DEBUG_LOCK:
        return dict(_LAST_RUN_DEBUG) if _LAST_RUN_DEBUG else None

# ============================================================
# テンプレート管理
# ============================================================
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

# フォールバック用モデルID。SDK からモデル一覧を取得できない場合に使用する。
# 実行時の優先選択は choose_default_model_id() で claude-sonnet 最新版を優先する。
MODEL = "gpt-4.1"
MAX_RETRY = 2
RETRY_BACKOFF = 2.0
SEND_TIMEOUT = 180  # sec（MCP ツール呼び出し分を考慮して延長）

# 図（draw.io XML）の生成は時間がかかりやすいので、別枠で長めに待つ。
DRAWIO_SEND_TIMEOUT = 60 * 60  # 60 min
REPORT_SEND_TIMEOUT = 600  # 10 min — MCP ツール利用を考慮
HEARTBEAT_INTERVAL = 5 * 60  # 5 min


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


async def _list_model_ids_async(client: Any) -> list[str]:
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

Do not mention internal tools, tool access, or any tool errors in your response.

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

回答では、内部ツールの有無・アクセス可否・ツールエラー等には一切触れないでください。

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

## Documentation references

Use only the reference URLs provided in the prompt (if present).
If no references are provided, proceed with best-effort recommendations without stating tool limitations.

## Output Structure (follow this structure)

1. **Secure Score Summary** — If score data is available, show:
   - Current score / Max score
   - Evaluation: 80-100 = Excellent (green), 60-79 = Needs improvement (yellow), 0-59 = Urgent (red)
   - Score improvement opportunities (what specific controls would raise the score)

2. **Recommendations Summary Table** — Classify and count by severity:
   | Severity | Count | Description |
   With Critical / High / Medium / Low categories.

3. **Critical & High Severity Findings** — For each:
   - Affected resource(s) by name
   - Impact description
   - Remediation steps (actionable commands or portal paths)
   - Reference: [Framework name](URL)

4. **Compliance Posture** — If compliance data available:
   | Standard | Passed | Failed | Rate |

5. **Prioritized Action Plan** — Separate into:
   - **Immediate (Today)**: Critical security gaps
   - **This Week**: High-priority improvements
   - **This Month**: Medium-priority hardening
   Each item as a checkbox task.

6. **What's Working Well** — Acknowledge good security practices found.

## Output Rules
- Classify severity as Critical / High / Medium / Low
- Attach official documentation in the format "Reference: [CAF Security Baseline](URL)" to each recommendation
- Do not comment on resource types that do not exist in this environment

## Data fidelity (IMPORTANT)

- Use ONLY facts present in the provided JSON blocks and resource list.
- Do NOT invent resource names, counts, plan tiers, scores, or settings.
- If a value is missing or null, explicitly write "Unknown" and propose how to verify.
- If you cite references, include the actual URL inline (do not use empty footnotes).

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

## 参考ドキュメント

プロンプト内に提示された参照URL（存在すれば）だけを使ってください。
参照が無い場合でも、ツール制約などの内部事情は書かずに、ベストエフォートで推奨を提示してください。

## 出力構成（この構成に従うこと）

1. **セキュアスコア概況** — スコアデータがあれば:
   - 現在のスコア / 最大スコア
   - 評価: 80-100 = 🟢 優良、60-79 = 🟡 要改善、0-59 = 🔴 要緊急対応
   - スコア改善の機会（具体的にどのコントロールを改善すれば上がるか）

2. **推奨事項サマリー表** — 深刻度で分類・件数表示:
   | 深刻度 | 件数 | 概要 |
   Critical / High / Medium / Low で分類。

3. **Critical & High の詳細** — 各項目に:
   - 対象リソース名
   - 影響の説明
   - 修復手順（実行可能なコマンドやポータルパス）
   - 根拠: [フレームワーク名](URL)

4. **コンプライアンスポスチャー** — コンプライアンスデータがあれば:
   | 標準 | 準拠 | 非準拠 | 準拠率 |

5. **優先度別アクションプラン** — 以下の3段に分離:
   - **即座に対応（当日）**: Critical なセキュリティギャップ
   - **今週中に対応**: High 優先度の改善
   - **今月中に対応**: Medium 優先度のハードニング
   各項目をチェックボックス形式で記載。

6. **この環境で良くできている点** — 既にあるセキュリティ対策を評価。

## 出力ルール
- 深刻度は Critical / High / Medium / Low で分類
- 各推奨事項に「根拠: [CAF Security Baseline](URL)」の形式で公式ドキュメントを付与
- 環境に存在しないリソースについての指摘はしない

## データ忠実性（重要）

- 事実として書いてよいのは、提示された JSON ブロックとリソース一覧に含まれる内容のみ。
- リソース名・件数・Defender の tier・スコア・設定値などを推測で「断定」しない。
- 値が欠けている/取得できていない場合は「不明」と明記し、確認手順を提案する。
- 参照を付ける場合は URL を本文に含める（URL なし脚注だけ、は不可）。

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

Do not mention internal tools, tool access, or any tool errors in your output.

Your report comments must be **specific findings for this particular environment** based on the provided data.
Prioritize specificity: "Resource X in this environment is Y, therefore Z should be done" — not generic advice.
Output in English Markdown format, using tables and lists for readability.
{guidance}
"""
    return f"""\
あなたは Azure セキュリティ監査の専門家です。
Azure Security Center / Microsoft Defender for Cloud のデータと、実際の Azure 環境のリソース一覧が提供されます。

出力では、内部ツールの有無・アクセス可否・ツールエラー等には一切触れないでください。

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

## Documentation references

Use only the reference URLs provided in the prompt (if present).
If no references are provided, proceed with best-effort recommendations without stating tool limitations.

## Output Structure (follow this structure)

1. **Cost Summary** — Show totals with trend indicator:
   - Total cost (MonthToDate)
   - Month-over-month change (% and absolute)
   - Trend: increasing / decreasing / stable

2. **Budget Consumption** — If budget data available:
   - Budget amount, consumed, remaining, percentage bar
   - Warning if > 80% consumed before month end

3. **Cost by Service** — Top services table with cost, percentage, bar visualization:
   | Service | Cost | % | Bar |

4. **Cost by Resource Group** — Table with costs sorted descending.

5. **Top 10 Resources** — Include resource name, type, RG, cost, owner/env tags.
   Flag resources missing cost allocation tags.

6. **Cost Anomaly Detection** — Resources with >50% cost increase vs prior period.
   | Resource | Prior Cost | Current Cost | Increase % | Possible Cause |

7. **Idle/Underutilized Resources** — Detect and list:
   - VMs with avg CPU < 5% (past 14 days)
   - Unattached disks, unused Public IPs
   - Storage accounts with no recent access
   Include estimated monthly savings for each.

8. **Optimization Recommendations** — Separate into:
   - **Quick Wins** (low effort, immediate savings): e.g., stop idle VMs, delete unattached disks
   - **Strategic Changes** (higher effort, larger savings): e.g., reserved instances, right-sizing
   Each with estimated savings amount and confidence level.

9. **Tag Governance** — If tag data available:
   - Tag coverage rate
   - Cost by department / environment / project tags
   - Untagged high-cost resources list

## Output Rules
- Attach official documentation in the format "Reference: [WAF Cost Optimization](URL)" to each recommendation
- Include currency symbols with amounts, use tables for readability
- Do not comment on resource types that do not exist in this environment

## Data fidelity (IMPORTANT)

- Use ONLY facts present in the provided JSON blocks and resource list.
- Do NOT invent resource names, costs, savings amounts, SKUs, or tags.
- If a value is missing or null, explicitly write "Unknown" and propose how to verify.
- If you cite references, include the actual URL inline (do not use empty footnotes).

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

## 参考ドキュメント

プロンプト内に提示された参照URL（存在すれば）だけを使ってください。
参照が無い場合でも、ツール制約などの内部事情は書かずに、ベストエフォートで推奨を提示してください。

## 出力構成（この構成に従うこと）

1. **コスト概況** — トレンド付きの合計表示:
   - 総コスト（月初来）
   - 前月比（% と絶対額）
   - トレンド: 📈 増加 / 📉 減少 / ➡️ 安定

2. **予算消化状況** — 予算データがあれば:
   - 予算額、消化額、残り、パーセント
   - 月末前に80%超消化の場合は警告

3. **サービス別コスト** — 上位サービスをテーブル表示:
   | サービス | コスト | 割合 | バー |

4. **リソースグループ別コスト** — コスト降順テーブル。

5. **コスト上位10リソース** — リソース名、種類、RG、コスト、owner/envタグ。
   コスト配分タグが未設定のリソースは指摘。

6. **コスト異常検知** — 前月比50%以上増加のリソースを検出:
   | リソース | 前月コスト | 今月コスト | 増加率 | 考えられる原因 |

7. **未使用・低稼働リソース** — 検出して一覧化:
   - 過去14日の平均CPU 5%未満の VM
   - 未接続ディスク、未使用 Public IP
   - アクセスのないストレージアカウント
   各項目に推定月額削減額を付記。

8. **最適化推奨事項** — 以下の2段に分離:
   - **Quick Win**（低工数・即効性）: アイドルVM停止、未接続ディスク削除など
   - **Strategic**（中長期・大きな削減）: 予約インスタンス、ライトサイジングなど
   各項目に推定削減額と信頼度を付記。

9. **タグガバナンス** — タグデータがあれば:
   - タグ設定率
   - 部門/環境/プロジェクト別コスト集計
   - タグ未設定の高コストリソース一覧

## 出力ルール
- 各推奨事項に「根拠: [WAF Cost Optimization](URL)」の形式で公式ドキュメントを付与
- 金額は通貨記号付きで、表を活用して読みやすく
- 環境に存在しないリソースについての指摘はしない

## データ忠実性（重要）

- 事実として書いてよいのは、提示された JSON ブロックとリソース一覧に含まれる内容のみ。
- リソース名・コスト・削減額・SKU・タグなどを推測で「断定」しない。
- 値が欠けている/取得できていない場合は「不明」と明記し、確認手順を提案する。
- 参照を付ける場合は URL を本文に含める（URL なし脚注だけ、は不可）。

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

Do not mention internal tools, tool access, or any tool errors in your output.

Your report comments must be **specific findings for this particular environment** based on the provided data.
Prioritize specificity: "Resource X in this environment is Y, therefore Z should be done" — not generic advice.
Output in English Markdown format, using tables and lists for readability.
{guidance}
"""
    return f"""\
あなたは Azure コスト最適化の専門家です。
Azure Cost Management のデータ（サービス別・RG別コスト）と、実際の Azure 環境のリソース一覧が提供されます。

出力では、内部ツールの有無・アクセス可否・ツールエラー等には一切触れないでください。

レポートのコメントは、提供データを読み解いた上で「この環境固有の具体的な指摘」を書いてください。
一般論ではなく、「この環境の ○○ は △△ だから □□ すべき」という具体性を最優先してください。
日本語の Markdown 形式で、表やリストを活用して読みやすく。
{guidance}
"""



# ============================================================
# CopilotClient キャッシュ（モジュール単位で再利用）
# ============================================================

_cached_client: Any | None = None
_cached_client_started: bool = False

# 同時に複数の generate/report が走った場合でも、CopilotClient.start() を
# 二重実行しないための非同期ロック（同一イベントループ内で直列化する）。
_client_create_lock: asyncio.Lock | None = None


def _get_client_create_lock() -> asyncio.Lock:
    global _client_create_lock
    if _client_create_lock is None:
        _client_create_lock = asyncio.Lock()
    return _client_create_lock


async def _get_or_create_client(
    on_status: Optional[Callable[[str], None]] = None,
) -> Any:
    """CopilotClient をキャッシュして返す。

    連続レポート生成時に毎回接続→停止のオーバーヘッドを排除する。
    asyncio.Lock で直列化し、_bg_lock（threading.Lock）は async 外の
    短いスナップショット参照にのみ使用してイベントループのブロックを防ぐ。
    """
    global _cached_client, _cached_client_started
    log = on_status or (lambda s: None)

    # 高速パス: ロック取得前にスナップショットチェック（threading.Lock は瞬時に解放）
    cached_client: Any | None = None
    with _bg_lock:
        if _cached_client is not None and _cached_client_started:
            cached_client = _cached_client
    if cached_client is not None:
        # NOTE: on_status は任意の実装（GUIログ等）になり得るため、ロック外で呼ぶ。
        log("Copilot SDK: Reusing cached client" if get_language() == "en" else "Copilot SDK: キャッシュ済みクライアントを再利用")
        return cached_client

    lock = _get_client_create_lock()
    async with lock:
        # ダブルチェック: 並行タスクが先に作成した場合
        cached_client = None
        with _bg_lock:
            if _cached_client is not None and _cached_client_started:
                cached_client = _cached_client
        if cached_client is not None:
            log("Copilot SDK: Reusing cached client" if get_language() == "en" else "Copilot SDK: キャッシュ済みクライアントを再利用")
            return cached_client

        log("Copilot SDK: Connecting..." if get_language() == "en" else "Copilot SDK に接続中...")
        client_opts: Any = {
            "auto_restart": True,
        }
        cli = copilot_cli_path()
        if cli:
            client_opts["cli_path"] = cli
            log(f"CLI path: {cli}")

        if CopilotClient is None:
            details = _COPILOT_IMPORT_ERROR or "unknown import error"
            log(f"⚠ Copilot SDK not available: {details}" if get_language() == "en" else f"⚠ Copilot SDK が利用できません: {details}")
            # frozen exe では、同梱ディレクトリ名が 'copilot' と衝突すると ImportError になりやすい。
            raise RuntimeError(
                f"Copilot SDK is not available.\n"
                f"→ Run: uv pip install copilot-sdk\n"
                f"Import error: {details}"
            )

        new_client = CopilotClient(options=client_opts)
        await new_client.start()

        with _bg_lock:
            _cached_client = new_client
            _cached_client_started = True

        log("Copilot SDK: Connected" if get_language() == "en" else "Copilot SDK 接続 OK")
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

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        *,
        model_id: str | None = None,
        append_language_instruction: bool = True,
        timeout_s: float | None = None,
        heartbeat_s: float | None = None,
    ) -> str | None:
        """汎用: 任意のプロンプトとシステムプロンプトで生成。

        SDK 推奨パターン:
          - session.idle イベント + asyncio.Event で完了待ち
          - hooks.on_error_occurred でリトライ制御
          - reasoning_delta 対応
          - on_pre_tool_use で読み取り専用ツールのみ許可
        """
        # 言語指示を system prompt 末尾に追加（デフォルト）。
        # drawio 生成のように Markdown 指示が致命的になる用途では OFF にする。
        if append_language_instruction:
            lang_instruction = _t("ai.output_language")
            system_prompt = system_prompt.rstrip() + "\n\n" + lang_instruction + "\n"

        run_debug: dict[str, Any] = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model_id or self._model_id or MODEL,
            "mcp_servers": {"microsoftdocs": {"url": MCP_MICROSOFT_DOCS.get("url"), "type": MCP_MICROSOFT_DOCS.get("type")}},
            "tool_total": 0,
            "tool_counts": {},
            "errors": [],
        }
        started = time.monotonic()

        try:
            # 1. SDK 接続（キャッシュ済みクライアントを再利用）
            client = await _get_or_create_client(on_status=self._on_status)

            # 2. セッション作成（hooks パターン + MCP サーバー）
            session_cfg: dict[str, Any] = {
                "model": model_id or self._model_id or MODEL,
                "streaming": True,
                "on_permission_request": _approve_all,
                "system_message": system_prompt,
                # Tool visibility hint: some environments require explicit allow-listing.
                # Keep this minimal and still enforce decisions via on_pre_tool_use.
                "available_tools": [
                    "microsoft_docs_search",
                    "microsoft_docs_fetch",
                    "microsoft_code_sample_search",
                ],
                "hooks": {
                    "on_pre_tool_use": _make_on_pre_tool_use(on_status=self._on_status, run_debug=run_debug),
                    "on_error_occurred": _make_error_handler(self._on_status, run_debug=run_debug),
                },
            }

            # Microsoft Docs MCP をセッションに接続
            # learn.microsoft.com/api/mcp → AI が自律的にドキュメント検索可能
            session_cfg["mcp_servers"] = {
                "microsoftdocs": MCP_MICROSOFT_DOCS,
            }
            self._on_status("Connecting Microsoft Docs MCP... (https://learn.microsoft.com/api/mcp)" if get_language() == "en" else "Microsoft Docs MCP を接続中... (https://learn.microsoft.com/api/mcp)")

            session = await client.create_session(session_cfg)

            # 3. ストリーミングイベント収集（session.idle パターン）
            collected: list[str] = []
            done = asyncio.Event()
            reasoning_notified = False

            def _handler(event: Any) -> None:
                # done後に遅延イベントが到着しても安全にスキップする (review #7)
                if done.is_set():
                    return
                etype = event.type.value if hasattr(event.type, "value") else str(event.type)

                # Capture session info about tool availability (best-effort)
                try:
                    allowed = getattr(event.data, "allowed_tools", None)
                    if allowed is not None and "allowed_tools" not in run_debug:
                        run_debug["allowed_tools"] = list(allowed) if isinstance(allowed, list) else allowed
                        if isinstance(allowed, list):
                            self._on_status(f"Allowed tools: {len(allowed)}")

                    telemetry = getattr(event.data, "tool_telemetry", None)
                    if telemetry is not None and "tool_telemetry" not in run_debug:
                        run_debug["tool_telemetry"] = telemetry
                except Exception:
                    pass

                if etype == "assistant.message_delta":
                    delta = getattr(event.data, "delta_content", "")
                    if delta:
                        collected.append(delta)
                        self._on_delta(delta)

                elif etype == "tool.execution_start":
                    # Tool execution started (includes MCP tool name if applicable)
                    try:
                        tool_name = getattr(event.data, "tool_name", None)
                        mcp_server = getattr(event.data, "mcp_server_name", None)
                        mcp_tool = getattr(event.data, "mcp_tool_name", None)
                        run_debug.setdefault("tool_exec", []).append({
                            "tool_name": tool_name,
                            "mcp_server": mcp_server,
                            "mcp_tool": mcp_tool,
                        })
                        if mcp_tool:
                            self._on_status(f"Tool exec start: {mcp_server}:{mcp_tool}")
                        elif tool_name:
                            self._on_status(f"Tool exec start: {tool_name}")
                    except Exception:
                        pass

                elif etype == "assistant.reasoning_delta":
                    # 推論過程（chain-of-thought）をそのまま表示しない
                    nonlocal reasoning_notified
                    if not reasoning_notified:
                        reasoning_notified = True
                        self._on_status("AI thinking..." if get_language() == "en" else "AI 思考中...")

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
            self._on_status("AI processing..." if get_language() == "en" else "AI 処理実行中...")
            await session.send({"prompt": prompt})

            # タイムアウト付きで idle 待ち（長時間タスクは heartbeat で進捗表示）
            effective_timeout = float(timeout_s) if timeout_s is not None else float(SEND_TIMEOUT)
            hb = float(heartbeat_s) if heartbeat_s is not None else 0.0
            try:
                if hb > 0:
                    while True:
                        elapsed = time.monotonic() - started
                        remaining = effective_timeout - elapsed
                        if remaining <= 0:
                            raise asyncio.TimeoutError
                        chunk = hb if remaining > hb else remaining
                        try:
                            await asyncio.wait_for(done.wait(), timeout=chunk)
                            break
                        except asyncio.TimeoutError:
                            elapsed2 = time.monotonic() - started
                            mins = int(elapsed2 // 60)
                            if get_language() == "en":
                                self._on_status(f"AI still running... (elapsed {mins} min)")
                            else:
                                self._on_status(f"AI 処理実行中...（経過 {mins}分）")
                else:
                    await asyncio.wait_for(done.wait(), timeout=effective_timeout)
            except asyncio.TimeoutError:
                if get_language() == "en":
                    self._on_status(f"AI timed out ({effective_timeout:g}s)")
                else:
                    self._on_status(f"AI 処理タイムアウト（{effective_timeout:g}秒）")

            result = "".join(collected) if collected else None

            # 5. セッションのみ破棄（クライアントはキャッシュ維持）
            await session.destroy()

            # ツール利用サマリ（GUIログ向け）
            try:
                tc: dict[str, dict[str, int]] = run_debug.get("tool_counts", {})  # type: ignore[assignment]
                docs_allow = 0
                docs_deny = 0
                for name, cnt in tc.items():
                    if str(name).startswith("microsoft_"):
                        docs_allow += int(cnt.get("allow", 0))
                        docs_deny += int(cnt.get("deny", 0))
                self._on_status(
                    f"Tool summary: total={run_debug.get('tool_total', 0)}, microsoft_docs_allow={docs_allow}, microsoft_docs_deny={docs_deny}"
                )
            except Exception:
                pass

            run_debug["duration_s"] = round(time.monotonic() - started, 3)
            run_debug["result_chars"] = len(result or "")
            _set_last_run_debug(run_debug)

            return result

        except Exception as e:
            self._on_status(f"AI review error: {e}" if get_language() == "en" else f"AI レビューエラー: {e}")
            run_debug["duration_s"] = round(time.monotonic() - started, 3)
            run_debug["exception"] = str(e)[:500]
            _set_last_run_debug(run_debug)
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


def run_summary_report(
    report_contents: list[tuple[str, str]],
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    model_id: str | None = None,
    subscription_info: str = "",
) -> str | None:
    """複数レポートのサマリ（エグゼクティブサマリ）を生成。

    Args:
        report_contents: [(report_type, markdown_text), ...] 例: [("security", "..."), ("cost", "...")]
    """
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status, model_id=model_id)

    en = get_language() == "en"
    if en:
        system_prompt = (
            "You are an Azure operations expert.\n"
            "The user has generated multiple Azure reports (security, cost, etc.).\n"
            "Your task is to produce a concise Executive Summary that:\n"
            "1. Highlights the most critical findings across ALL reports\n"
            "2. Provides a unified risk/opportunity matrix (Critical / High / Medium / Low)\n"
            "3. Recommends top 5 priority actions with estimated effort (Quick win / Strategic)\n"
            "4. Keeps total length under 800 words\n\n"
            "Output in Markdown. Do not repeat the full reports — summarize and cross-reference.\n"
            "Do not mention internal tools or tool errors.\n"
        )
    else:
        system_prompt = (
            "あなたは Azure 運用の専門家です。\n"
            "ユーザーが複数の Azure レポート（セキュリティ、コスト等）を生成しました。\n"
            "以下のタスクを実行してください:\n"
            "1. 全レポートを横断した最重要所見をハイライト\n"
            "2. 統合リスク/機会マトリクス（Critical / High / Medium / Low）\n"
            "3. 優先アクション Top 5（工数目安: Quick win / Strategic を付記）\n"
            "4. 全体 800 文字以内に収める\n\n"
            "Markdown で出力。各レポートの全文は繰り返さず、要約・相互参照すること。\n"
            "内部ツールの有無・アクセス可否には一切触れないこと。\n"
        )

    parts: list[str] = []
    if subscription_info:
        label = "Target Subscription" if en else "対象サブスクリプション"
        parts.append(f"**{label}**: {subscription_info}\n\n")

    header = "Generate an Executive Summary from the following reports." if en else "以下のレポート群からエグゼクティブサマリを生成してください。"
    parts.append(header + "\n\n")

    for rtype, content in report_contents:
        parts.append(f"## {rtype.upper()} Report\n\n{content}\n\n---\n\n")

    prompt = "".join(parts)
    return _run_async(
        reviewer.generate(prompt, system_prompt, model_id=model_id),
        timeout_s=REPORT_SEND_TIMEOUT + 30,
    )


def run_integrated_report(
    *,
    diagram_summaries: list[dict[str, Any]],
    report_contents: list[tuple[str, str]],
    diff_contents: list[tuple[str, str]] | None = None,
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    model_id: str | None = None,
    subscription_info: str = "",
    resource_group: str = "",
) -> str | None:
    """複数ビュー（図/レポート）を横断した統合レポートを生成する。"""
    reviewer = AIReviewer(on_delta=on_delta, on_status=on_status, model_id=model_id)

    en = get_language() == "en"
    if en:
        system_prompt = (
            "You are an Azure operations expert.\n"
            "The user generated multiple outputs from an Azure environment: diagrams and/or reports.\n"
            "Your task is to produce ONE integrated report in Markdown that:\n"
            "1. Summarizes environment overview from diagram summaries\n"
            "2. Summarizes key findings from each report (security/cost)\n"
            "3. Adds cross-domain insights (security vs cost vs architecture)\n"
            "4. Provides a unified priority action list (Top 5) with effort labels\n"
            "If diff data is provided, summarize what changed (3-5 bullets).\n"
            "Do not repeat the full reports. Be specific to the provided data.\n"
            "Do not mention internal tools, tool availability, or any tool errors.\n"
            "\n"
            "CRITICAL: Output the Markdown report DIRECTLY as plain text.\n"
            "Do NOT wrap the output in <tool_calls>, <tool_call>, <tool_input>, or any XML tags.\n"
            "Do NOT simulate file-creation tool calls. Just output the Markdown text directly.\n"
        )
    else:
        system_prompt = (
            "あなたは Azure 運用の専門家です。\n"
            "ユーザーが Azure 環境から複数の出力（図サマリ / セキュリティ / コスト等）を生成しました。\n"
            "Markdown で『統合レポート』を1本作ってください。要件:\n"
            "1. 図サマリから環境概要（構成/規模）を要約\n"
            "2. 各レポート（security/cost）の重要所見を要約\n"
            "3. 横断的な洞察（セキュリティ×コスト×アーキテクチャ）を追加\n"
            "4. 優先アクション Top 5（工数目安: Quick win / Strategic）\n"
            "差分データがある場合は、前回から何が変わったかを 3〜5 点で要約\n"
            "全文の貼り直しは避け、要約中心で具体的に。\n"
            "内部ツールの有無・アクセス可否・ツールエラー等には一切触れないでください。\n"
            "\n"
            "重要: レポートは Markdown テキストとして直接出力してください。\n"
            "<tool_calls>/<tool_call>/<tool_input> 等の XML タグで囲まないでください。\n"
            "ファイル作成のツール呼び出しを模倣しないでください。Markdown をそのまま出力してください。\n"
        )

    parts: list[str] = []
    if subscription_info:
        label = "Target Subscription" if en else "対象サブスクリプション"
        parts.append(f"**{label}**: {subscription_info}\n")
    if resource_group:
        label = "Target Resource Group" if en else "対象リソースグループ"
        parts.append(f"**{label}**: {resource_group}\n")
    if parts:
        parts.append("\n")

    header = "Generate an integrated Azure operations report from the following inputs." if en else "以下の入力から Azure 運用の統合レポートを生成してください。"
    parts.append(header + "\n\n")

    if diagram_summaries:
        title = "Diagram Summaries" if en else "図サマリ"
        parts.append(f"## {title}\n")
        parts.append("```json\n" + json.dumps(diagram_summaries, ensure_ascii=False) + "\n```\n\n")

    for rtype, content in report_contents:
        parts.append(f"## {rtype.upper()} Report\n\n{content}\n\n---\n\n")

    if diff_contents:
        diff_title = "Changes from Previous Reports" if en else "前回レポートからの変更点"
        parts.append(f"## {diff_title}\n\n")
        for rtype, diff_md in diff_contents:
            parts.append(f"### {rtype.upper()} Diff\n\n{diff_md}\n\n---\n\n")

    prompt = "".join(parts)
    raw = _run_async(
        reviewer.generate(prompt, system_prompt, model_id=model_id,
                         timeout_s=REPORT_SEND_TIMEOUT),
        timeout_s=REPORT_SEND_TIMEOUT + 30,
    )

    if not isinstance(raw, str):
        return raw

    sanitized = _sanitize_ai_markdown(raw)

    # If sanitization removed headings but the content is otherwise present, salvage by
    # prepending a top-level heading to avoid unnecessary fallback.
    if sanitized and not any(l.lstrip().startswith("#") for l in sanitized.splitlines() if l.strip()):
        title = "# Integrated Report" if get_language() == "en" else "# 統合レポート"
        sanitized = title + "\n\n" + sanitized.lstrip()

    # まだツール痕跡が残る/見出しが無い場合は「統合として不正」として扱う
    lowered = sanitized.lower()
    reasons: list[str] = []
    if (
        "<tool_" in lowered
        or "<parameters" in lowered
        or "<parameter" in lowered
        or "<result" in lowered
        or "<filereadresult" in lowered
        or "<filewriteresult" in lowered
    ):
        reasons.append("tool_trace")
    if not any(l.lstrip().startswith("#") for l in sanitized.splitlines() if l.strip()):
        reasons.append("no_heading")

    if reasons:
        log = on_status or (lambda _s: None)
        msg = (
            "AI output invalid for integrated report" if en else "AI 統合出力が不正です"
        ) + f" ({', '.join(reasons)})"
        log(msg)
        # Best-effort debug hint (keep short to avoid log bloat)
        try:
            raw_preview = raw.replace("\r", "").replace("\n", "\\n")[:240]
            san_preview = sanitized.replace("\r", "").replace("\n", "\\n")[:240]
            if en:
                log(f"  raw(head): {raw_preview}")
                log(f"  sanitized(head): {san_preview}")
            else:
                log(f"  raw(先頭): {raw_preview}")
                log(f"  sanitized(先頭): {san_preview}")
        except Exception:
            pass
        return None

    return sanitized


def run_drawio_generation(
    diagram_request: dict[str, Any],
    *,
    on_delta: Optional[Callable[[str], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
    model_id: str | None = None,
    require_azure2_icons: bool = True,
    max_attempts: int = 3,
) -> str | None:
    """AI で draw.io (mxfile) XML を生成し、バリデーションして返す。

    - 出力は XML のみを期待するが、逸脱した場合は抽出で救済する。
    - バリデーションERRORが出た場合は最大 *max_attempts* 回リトライ。
    - すべて失敗した場合は None。
    """
    from .drawio_validate import Issue, validate_drawio_xml

    import xml.etree.ElementTree as ET

    log = on_status or (lambda _s: None)

    base_prompt = (
        "Generate a draw.io diagram from the following JSON." if get_language() == "en" else "以下のJSONから draw.io 図を生成してください。"
    )
    # NOTE: keep this compact to reduce token usage when nodes are many.
    prompt = base_prompt + "\n\n```json\n" + json.dumps(diagram_request, ensure_ascii=False) + "\n```\n"

    reviewer = AIReviewer(
        on_delta=on_delta or (lambda _d: None),
        on_status=on_status,
        model_id=model_id,
    )

    system_prompt = _system_prompt_drawio()

    # Input-derived expectations (to prevent "blank" or container-only diagrams).
    node_cell_ids: list[str] = []
    try:
        for n in (diagram_request.get("nodes") or []):
            cid = n.get("cellId") if isinstance(n, dict) else None
            if isinstance(cid, str) and cid.strip():
                node_cell_ids.append(cid.strip())
    except Exception:
        node_cell_ids = []

    # Require at least some of the provided nodes to be present as mxCell ids.
    # Keep this lenient to avoid rejecting large diagrams due to token limits.
    min_present = 1
    if node_cell_ids:
        min_present = max(1, min(10, len(node_cell_ids) // 10))  # 10% up to 10 nodes

    last_issues: list[str] = []
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        if attempt > 1:
            log(_t("log.ai_drawio_retry", attempt=attempt, max=max_attempts))

        run_prompt = prompt
        if last_issues:
            # エラーをフィードバックして再生成
            issues_block = "\n".join(f"- {x}" for x in last_issues[:20])
            if get_language() == "en":
                run_prompt += (
                    "\n\nValidation errors from the previous attempt:\n" + issues_block +
                    "\n\nRegenerate the FULL corrected mxfile XML. Output XML only."
                )
            else:
                run_prompt += (
                    "\n\n前回の出力のバリデーションエラー:\n" + issues_block +
                    "\n\nエラーを解消した完全な mxfile XML を再生成してください。XMLのみ出力。"
                )

        result = _run_async(
            reviewer.generate(
                run_prompt,
                system_prompt,
                model_id=model_id,
                append_language_instruction=False,
                timeout_s=DRAWIO_SEND_TIMEOUT,
                heartbeat_s=HEARTBEAT_INTERVAL,
            ),
            timeout_s=DRAWIO_SEND_TIMEOUT + 30,
        )
        if not result:
            last_issues = ["Empty model output"]
            continue

        xml = _extract_mxfile_xml(result)
        if not xml:
            last_issues = ["Could not find <mxfile>...</mxfile> in the output"]
            continue

        issues = validate_drawio_xml(xml, require_azure2_icons=require_azure2_icons)
        errors = [i for i in issues if i.level == "ERROR"]

        # Extra gate: ensure generated XML contains enough of the requested node ids.
        if not errors and node_cell_ids:
            try:
                root = ET.fromstring(xml)
                found_ids = {c.get("id") for c in root.findall(".//mxCell")}
                present = sum(1 for cid in node_cell_ids if cid in found_ids)
                total = len(node_cell_ids)
                log(_t("log.ai_drawio_stats", present=present, total=total))
                if present < min_present:
                    errors.append(Issue("ERROR", f"Too few input nodes present in XML: {present}/{total} (min {min_present})"))
            except Exception:
                errors.append(Issue("ERROR", "Failed to parse generated XML for node-coverage check"))

        if not errors:
            return xml

        log(_t("log.ai_drawio_validation_failed", count=len(errors)))
        last_issues = [e.message for e in errors]

    return None


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
            "If reference URLs are provided below, cite them where relevant.\n"
            "Do not mention internal tools, tool access, or any tool errors.\n"
        )
    else:
        parts.append(
            f"以下の Azure 環境の{report_type}レポートを生成してください。\n\n"
            "**重要**: 以下のデータをよく読み、この環境固有の具体的な指摘を書いてください。\n"
            "リソース名やタイプを具体的に挙げてコメントし、「一般論」は避けてください。\n"
            "以下に参照URLが提示されていれば、適宜引用してください。\n"
            "内部ツールの有無・アクセス可否・ツールエラー等には一切触れないでください。\n"
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
    return _run_async(
        reviewer.generate(prompt, system_prompt, model_id=model_id,
                         timeout_s=REPORT_SEND_TIMEOUT),
        timeout_s=REPORT_SEND_TIMEOUT + 30,
    )


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

    future: concurrent.futures.Future[list[str]] | None = None
    try:
        loop = _get_bg_loop()
        future = asyncio.run_coroutine_threadsafe(_inner(), loop)
        return list(future.result(timeout=timeout))
    except concurrent.futures.TimeoutError:
        if on_status:
            on_status(f"Copilot SDK: Model listing timed out ({timeout:g}s)" if get_language() == "en" else f"Copilot SDK: モデル一覧取得が {timeout:g}s を超過しました")
        if future is not None:
            try:
                future.cancel()
            except Exception:
                pass
        return []
    except Exception as exc:
        if on_status:
            on_status(f"Copilot SDK: Model listing error: {type(exc).__name__}: {exc}" if get_language() == "en" else f"Copilot SDK: モデル一覧取得エラー: {type(exc).__name__}: {exc}")
        if future is not None:
            try:
                future.cancel()
            except Exception:
                pass
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
        loop = asyncio.new_event_loop()

        loop_ready = threading.Event()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            # Signal readiness only after the loop has started and can process callbacks.
            loop.call_soon(loop_ready.set)
            loop.run_forever()

            try:
                loop.close()
            except Exception:
                pass

        thread = threading.Thread(target=_run, daemon=True, name="copilot-event-loop")
        thread.start()

        # ループが起動しない場合、この後の run_coroutine_threadsafe が永久待ちになり得る。
        if not loop_ready.wait(timeout=5):
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
            raise RuntimeError("Copilot background event loop failed to start within 5 seconds")

        _bg_loop = loop
        _bg_thread = thread
        return loop


def _run_async(coro: Any, timeout_s: float | None = None) -> Any:
    """コルーチンを永続イベントループ上で同期的に実行する。

    バックグラウンドスレッド（tkinter ワーカー）から呼ぶ前提。
    CopilotClient は同一ループ上に留まるためキャッシュが安全に使える。
    """
    loop = _get_bg_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    timeout = timeout_s if timeout_s is not None else (SEND_TIMEOUT + 30)
    try:
        return future.result(timeout=timeout)
    except (TimeoutError, concurrent.futures.TimeoutError):
        # タイムアウト時はコルーチンをキャンセルしてリソースリークを防ぐ
        future.cancel()
        raise

"""Copilot SDK + Microsoft Docs MCP smoke test.

This script attempts to force a tool call to `microsoft_docs_search` via Copilot SDK.
It prints:
- on_status logs (should include Tool allow/deny + Tool summary)
- the final result (expected: a single URL)
- the debug snapshot from ai_reviewer.get_last_run_debug()

Run:
    uv run python ./scripts/mcp_smoke_test.py

Notes:
- Requires Copilot CLI auth (e.g. `copilot auth login`) or equivalent token setup.
- Network/proxy policies may block access to https://learn.microsoft.com/api/mcp.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Ensure project root (azure-ops-dashboard/) is importable when executed from scripts/.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from ai_reviewer import (
    AIReviewer,
    get_last_run_debug,
    list_available_model_ids_sync,
    choose_default_model_id,
    _run_async,
)


def main() -> int:
    system_prompt = """You are a helper.

You MUST do the following:
1) Call microsoft_docs_search with query: Azure Virtual Network overview
2) Return ONLY the raw JSON you received from the tool call (no extra words).
"""

    prompt = "Return the tool JSON only."

    model_ids = list_available_model_ids_sync(on_status=print, timeout=10)
    preferred = None
    for mid in model_ids:
        if str(mid).startswith("claude-sonnet"):
            preferred = mid
            break
    model_id = preferred or (choose_default_model_id(model_ids) if model_ids else None)
    print(f"Using model: {model_id or '(default)'}")

    reviewer = AIReviewer(on_delta=lambda _s: None, on_status=print, model_id=model_id)
    result = _run_async(reviewer.generate(prompt, system_prompt))

    print("\nRESULT:")
    print(result)

    print("\nDEBUG:")
    print(get_last_run_debug())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

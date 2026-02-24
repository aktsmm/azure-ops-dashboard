"""Probe Microsoft Docs MCP server tool list.

Attempts to talk to the Microsoft Learn MCP endpoint directly:
  https://learn.microsoft.com/api/mcp

This is for troubleshooting only (no secrets required).

Run:
  uv run python ./scripts/microsoft_docs_mcp_probe.py

Exit code:
  0 = request succeeded (even if tool list is empty)
  1 = request failed
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


MCP_URL = "https://learn.microsoft.com/api/mcp"


def _parse_sse_json(text: str) -> dict:
    # Very small SSE parser: gather first event's data lines and json-decode.
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif data_lines and not line.strip():
            break
    if not data_lines:
        raise json.JSONDecodeError("No SSE data frames", text, 0)
    joined = "\n".join(data_lines)
    return json.loads(joined)


def _post(payload: dict, *, session_id: str | None = None) -> tuple[dict, dict[str, str]]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    # Some MCP servers use a session header; try common names.
    if session_id:
        headers["Mcp-Session-Id"] = session_id
        headers["mcp-session-id"] = session_id

    req = urllib.request.Request(MCP_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            resp_headers = {k: v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise RuntimeError(f"HTTP {e.code}: {e.reason}\n{err_body[:4000]}") from e
    ctype = (resp_headers.get("Content-Type") or resp_headers.get("content-type") or "").lower()
    try:
        if "application/json" in ctype or body.lstrip().startswith("{"):
            return json.loads(body), resp_headers
        if "text/event-stream" in ctype or body.lstrip().startswith("data:") or body.lstrip().startswith("event:"):
            return _parse_sse_json(body), resp_headers
        # fallback: try JSON anyway
        return json.loads(body), resp_headers
    except json.JSONDecodeError as e:
        snippet = body[:500].replace("\r", "")
        raise json.JSONDecodeError(
            f"{e.msg} (content-type={ctype}, body[0:500]={snippet!r})",
            e.doc,
            e.pos,
        )


def main() -> int:
    try:
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                # MCP protocol version (server will reject if missing).
                # If this fails, inspect the error body to adjust.
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "azure-ops-dashboard-probe", "version": "0.1"},
                "capabilities": {},
            },
        }
        init_resp, init_headers = _post(init)
        print("initialize response keys:", list(init_resp.keys()))
        print("initialize headers (subset):")
        for k in sorted(init_headers):
            if k.lower().startswith("mcp") or k.lower().startswith("x-mcp"):
                print(f"  {k}: {init_headers[k]}")

        session_id = (
            init_headers.get("Mcp-Session-Id")
            or init_headers.get("mcp-session-id")
            or init_headers.get("x-mcp-session-id")
            or None
        )
        if session_id:
            print("session id:", session_id)

        tools_list = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        tools_resp, _tools_headers = _post(tools_list, session_id=session_id)
        print("tools/list response:")
        print(json.dumps(tools_resp, ensure_ascii=False, indent=2)[:8000])

        return 0

    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

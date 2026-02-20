"""Step10: Azure Env Diagrammer — Azure収集ロジック

az graph query ラッパとデータモデル。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import textwrap
from collections import Counter
from dataclasses import dataclass
from typing import Any

from i18n import get_language


# ============================================================
# データモデル
# ============================================================

@dataclass(frozen=True)
class Node:
    azure_id: str
    name: str
    type: str
    resource_group: str
    location: str | None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str


# ============================================================
# az CLI ヘルパ
# ============================================================

_AZ_EXE: str | None = None


class AzNotFoundError(RuntimeError):
    """Azure CLI が見つからない。"""


class AzNotLoggedInError(RuntimeError):
    """az login されていない。"""


class AzExtensionMissingError(RuntimeError):
    """resource-graph 拡張がない。"""


def _get_az_exe() -> str:
    global _AZ_EXE
    if _AZ_EXE:
        return _AZ_EXE

    for candidate in ("az", "az.cmd", "az.exe"):
        found = shutil.which(candidate)
        if found:
            _AZ_EXE = found
            return found

    raise AzNotFoundError(
        "Azure CLI (az) が見つかりません。\n"
        "→ https://learn.microsoft.com/cli/azure/install-azure-cli からインストールしてください。"
    )


def _run_command(args: list[str], timeout_s: int = 300) -> tuple[int, str, str]:
    import sys
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout_s,
        "encoding": "utf-8",
        "errors": "replace",
    }
    # Windows: shell=True だと timeout kill が効かないことがあるので
    # CREATE_NEW_PROCESS_GROUP を使いつつ shell=False で実行
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        completed = subprocess.run(args, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"コマンドが {timeout_s} 秒でタイムアウトしました。\n"
            f"→ RG を指定して範囲を絞るか、resource-graph 拡張を確認してください。"
        )
    return completed.returncode, completed.stdout, completed.stderr


def _classify_az_error(stderr: str) -> RuntimeError:
    """stderr からエラーを分類して適切な例外を返す。"""
    lower = stderr.lower()
    en = get_language() == "en"
    if "please run 'az login'" in lower or "az login" in lower:
        msg = ("Not logged in to Azure.\n→ Run `az login`."
               if en else
               "Azure にログインしていません。\n→ `az login` を実行してください。")
        return AzNotLoggedInError(msg)
    if "not an installed extension" in lower or "resource-graph" in lower:
        msg = ("resource-graph extension not installed.\n→ Run `az extension add --name resource-graph`."
               if en else
               "resource-graph 拡張がインストールされていません。\n→ `az extension add --name resource-graph` を実行してください。")
        return AzExtensionMissingError(msg)
    return RuntimeError(f"az graph query failed:\n{stderr}")


# ============================================================
# 事前チェック
# ============================================================

def preflight_check() -> list[str]:
    """起動時に az 環境をチェックし、問題があれば警告メッセージのリストを返す。"""
    warnings: list[str] = []

    # 1. az コマンドの存在確認
    try:
        _get_az_exe()
    except AzNotFoundError as e:
        warnings.append(str(e))
        return warnings  # az がないなら以降のチェックは不可能

    # 2. ログイン確認
    code, _out, err = _run_command([_get_az_exe(), "account", "show", "--output", "json"], timeout_s=30)
    if code != 0:
        en = get_language() == "en"
        msg = ("Not logged in to Azure.\n→ Run `az login`."
               if en else
               "Azure にログインしていません。\n→ `az login` を実行してください。")
        warnings.append(msg)
        return warnings

    # 3. resource-graph 拡張確認
    code, out, _err = _run_command([_get_az_exe(), "extension", "list", "--output", "json"], timeout_s=30)
    if code == 0:
        try:
            extensions = json.loads(out)
            names = [e.get("name", "") for e in extensions] if isinstance(extensions, list) else []
            if "resource-graph" not in names:
                en = get_language() == "en"
                msg = ("resource-graph extension not installed.\n→ Run `az extension add --name resource-graph`."
                       if en else
                       "resource-graph 拡張がインストールされていません。\n→ `az extension add --name resource-graph` を実行してください。")
                warnings.append(msg)
        except json.JSONDecodeError:
            pass

    return warnings


# ============================================================
# Subscription / Resource Group 候補取得
# ============================================================

def list_subscriptions() -> list[dict[str, str]]:
    """サブスクリプション一覧を返す。[{"id": ..., "name": ...}, ...]"""
    code, out, _err = _run_command([_get_az_exe(), "account", "list", "--output", "json"], timeout_s=30)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        if not isinstance(data, list):
            return []
        return [
            {"id": str(s.get("id", "")), "name": str(s.get("name", ""))}
            for s in data
            if s.get("id")
        ]
    except json.JSONDecodeError:
        return []


def list_resource_groups(subscription: str | None) -> list[str]:
    """指定サブスクリプションのRG名一覧を返す。"""
    cmd = [_get_az_exe(), "group", "list", "--output", "json"]
    if subscription:
        cmd.extend(["--subscription", subscription])
    code, out, _err = _run_command(cmd, timeout_s=30)
    if code != 0:
        return []
    try:
        data = json.loads(out)
        if not isinstance(data, list):
            return []
        return sorted([str(g.get("name", "")) for g in data if g.get("name")])
    except json.JSONDecodeError:
        return []


# ============================================================
# Azure Resource Graph クエリ
# ============================================================

def _az_graph_query(
    query: str,
    subscription: str | None,
    timeout_s: int = 300,
) -> tuple[int, str, str, list[dict[str, Any]]]:
    cmd = [_get_az_exe(), "graph", "query", "-q", query, "--first", "1000", "--output", "json"]
    if subscription:
        cmd.extend(["--subscriptions", subscription])

    code, out, err = _run_command(cmd, timeout_s=timeout_s)

    data: list[dict[str, Any]] = []
    if code == 0:
        try:
            payload = json.loads(out)
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                data = payload["data"]
            elif isinstance(payload, list):
                data = payload
        except json.JSONDecodeError:
            pass

    return code, out, err, data


# ============================================================
# ノーマライズ/ID
# ============================================================

def normalize_azure_id(azure_id: str) -> str:
    return azure_id.strip().lower()


def cell_id_for_azure_id(azure_id: str) -> str:
    digest = hashlib.sha1(normalize_azure_id(azure_id).encode("utf-8")).hexdigest()[:12]
    return f"n{digest}"


# ============================================================
# 収集: inventory
# ============================================================

def collect_inventory(
    subscription: str | None,
    resource_group: str | None,
    limit: int,
) -> tuple[list[Node], dict[str, Any]]:
    """ARGでリソース一覧を取得し、Nodeリストと実行メタを返す。"""
    where_clause = ""
    if resource_group:
        rg_escaped = resource_group.replace("'", "''")
        where_clause = f"| where resourceGroup =~ '{rg_escaped}'"

    query = textwrap.dedent(f"""
        Resources
        {where_clause}
        | project id, name, type, resourceGroup, location
        | order by type asc, name asc
        | limit {limit}
    """).strip()

    code, out, err, rows = _az_graph_query(query=query, subscription=subscription)

    meta = {"query": query, "az_exit_code": code, "stdout": out, "stderr": err}

    if code != 0:
        raise _classify_az_error(err)

    nodes: list[Node] = []
    for row in rows:
        azure_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        rtype = str(row.get("type") or "").strip()
        rg = str(row.get("resourceGroup") or "").strip()
        loc = row.get("location")
        location = str(loc).strip() if loc is not None else None

        if not azure_id or not name or not rtype:
            continue

        nodes.append(Node(
            azure_id=normalize_azure_id(azure_id),
            name=name,
            type=rtype,
            resource_group=rg,
            location=location,
        ))

    return nodes, meta


# ============================================================
# 収集: network
# ============================================================

def collect_network(
    subscription: str | None,
    resource_group: str | None,
    limit: int,
) -> tuple[list[Node], list[Edge], dict[str, Any]]:
    """ARGでネットワーク関連リソースを取得し、Node/Edgeリストと実行メタを返す。"""
    where_clause = ""
    if resource_group:
        rg_escaped = resource_group.replace("'", "''")
        where_clause = f"| where resourceGroup =~ '{rg_escaped}'"

    # VNet / Subnet / NSG / NIC / Public IP / LB / AppGW / VM
    net_types = [
        "microsoft.network/virtualnetworks",
        "microsoft.network/networksecuritygroups",
        "microsoft.network/networkinterfaces",
        "microsoft.network/publicipaddresses",
        "microsoft.network/loadbalancers",
        "microsoft.network/applicationgateways",
        "microsoft.network/connections",
        "microsoft.network/networkwatchers",
        "microsoft.compute/virtualmachines",
    ]
    type_filter = ", ".join(f"'{t}'" for t in net_types)

    query = textwrap.dedent(f"""
        Resources
        {where_clause}
        | where type in~ ({type_filter})
        | project id, name, type, resourceGroup, location, properties
        | order by type asc, name asc
        | limit {limit}
    """).strip()

    code, out, err, rows = _az_graph_query(query=query, subscription=subscription)
    meta = {"query": query, "az_exit_code": code, "stdout": out, "stderr": err}

    if code != 0:
        raise _classify_az_error(err)

    nodes: list[Node] = []
    edges: list[Edge] = []
    azure_ids: set[str] = set()

    for row in rows:
        azure_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        rtype = str(row.get("type") or "").strip()
        rg = str(row.get("resourceGroup") or "").strip()
        loc = row.get("location")
        location = str(loc).strip() if loc is not None else None
        props = row.get("properties") or {}

        if not azure_id or not name or not rtype:
            continue

        nid = normalize_azure_id(azure_id)
        azure_ids.add(nid)

        nodes.append(Node(
            azure_id=nid,
            name=name,
            type=rtype,
            resource_group=rg,
            location=location,
        ))

        lower_type = rtype.lower()

        # NIC → VM （virtualMachine.id）
        if lower_type == "microsoft.network/networkinterfaces":
            vm_ref = (props.get("virtualMachine") or {}).get("id")
            if vm_ref:
                edges.append(Edge(
                    source=nid,
                    target=normalize_azure_id(vm_ref),
                    kind="attached-to",
                ))
            # NIC → NSG
            nsg_ref = (props.get("networkSecurityGroup") or {}).get("id")
            if nsg_ref:
                edges.append(Edge(
                    source=nid,
                    target=normalize_azure_id(nsg_ref),
                    kind="secured-by",
                ))
            # NIC → Subnet (ipConfigurations[].subnet.id)
            for ipconfig in props.get("ipConfigurations") or []:
                ip_props = ipconfig.get("properties") or {}
                subnet_ref = (ip_props.get("subnet") or {}).get("id")
                if subnet_ref:
                    # Subnet は VNet の子リソースなので VNetへのエッジにする
                    vnet_id = "/".join(normalize_azure_id(subnet_ref).split("/")[:-2])
                    edges.append(Edge(
                        source=nid,
                        target=vnet_id,
                        kind="in-vnet",
                    ))
                # NIC → Public IP
                pip_ref = (ip_props.get("publicIPAddress") or {}).get("id")
                if pip_ref:
                    edges.append(Edge(
                        source=normalize_azure_id(pip_ref),
                        target=nid,
                        kind="assigned-to",
                    ))

    # ノードにないターゲットへのエッジを除外
    edges = [e for e in edges if e.target in azure_ids and e.source in azure_ids]

    return nodes, edges, meta


# ============================================================
# 収集: セキュリティデータ
# ============================================================

def collect_security(subscription: str | None) -> dict[str, Any]:
    """Azure Security Center / Defender のデータを収集。

    AG-azure-operation の Collect-AzureData.ps1 参照。
    REST API (az rest) でセキュアスコア・セキュリティ評価・Defender設定を取得。
    """
    sub_id = subscription
    if not sub_id:
        code, out, _err = _run_command([_get_az_exe(), "account", "show", "--query", "id", "-o", "tsv"], timeout_s=15)
        sub_id = out.strip() if code == 0 else None

    result: dict[str, Any] = {
        "subscription_id": sub_id,
        "secure_score": None,
        "assessments_summary": None,
        "defender_status": None,
    }

    if not sub_id:
        return result

    # 1. セキュアスコア
    score_uri = f"https://management.azure.com/subscriptions/{sub_id}/providers/Microsoft.Security/secureScores?api-version=2020-01-01"
    code, out, _err = _run_command(
        [_get_az_exe(), "rest", "--method", "GET", "--uri", score_uri, "--output", "json"],
        timeout_s=30,
    )
    if code == 0:
        try:
            data = json.loads(out)
            values = data.get("value", [])
            if values:
                props = values[0].get("properties", {})
                score = props.get("score", {})
                result["secure_score"] = {
                    "current": score.get("current"),
                    "max": score.get("max"),
                    "percentage": score.get("percentage"),
                }
        except json.JSONDecodeError:
            pass

    # 2. セキュリティ評価サマリ
    assess_uri = f"https://management.azure.com/subscriptions/{sub_id}/providers/Microsoft.Security/assessments?api-version=2021-06-01"
    code, out, _err = _run_command(
        [_get_az_exe(), "rest", "--method", "GET", "--uri", assess_uri, "--output", "json"],
        timeout_s=60,
    )
    if code == 0:
        try:
            data = json.loads(out)
            assessments = data.get("value", [])
            healthy = sum(1 for a in assessments
                         if a.get("properties", {}).get("status", {}).get("code") == "Healthy")
            unhealthy = sum(1 for a in assessments
                           if a.get("properties", {}).get("status", {}).get("code") == "Unhealthy")
            not_applicable = sum(1 for a in assessments
                                if a.get("properties", {}).get("status", {}).get("code") == "NotApplicable")
            result["assessments_summary"] = {
                "total": len(assessments),
                "healthy": healthy,
                "unhealthy": unhealthy,
                "not_applicable": not_applicable,
            }
        except json.JSONDecodeError:
            pass

    # 3. Defender プラン状態
    pricing_uri = f"https://management.azure.com/subscriptions/{sub_id}/providers/Microsoft.Security/pricings?api-version=2024-01-01"
    code, out, _err = _run_command(
        [_get_az_exe(), "rest", "--method", "GET", "--uri", pricing_uri, "--output", "json"],
        timeout_s=30,
    )
    if code == 0:
        try:
            data = json.loads(out)
            plans = data.get("value", [])
            plan_summary = []
            for p in plans:
                name = p.get("name", "")
                tier = p.get("properties", {}).get("pricingTier", "Unknown")
                plan_summary.append({"name": name, "tier": tier})
            result["defender_status"] = plan_summary
        except json.JSONDecodeError:
            pass

    return result


# ============================================================
# 収集: コストデータ
# ============================================================

def collect_cost(subscription: str | None) -> dict[str, Any]:
    """Azure Cost Management のデータを収集。

    AG-azure-operation の Collect-AzureData.ps1 参照。
    REST API (az rest) でサービス別コスト・RG別コストを取得。
    """
    sub_id = subscription
    if not sub_id:
        code, out, _err = _run_command([_get_az_exe(), "account", "show", "--query", "id", "-o", "tsv"], timeout_s=15)
        sub_id = out.strip() if code == 0 else None

    result: dict[str, Any] = {
        "subscription_id": sub_id,
        "cost_by_service": None,
        "cost_by_rg": None,
    }

    if not sub_id:
        return result

    cost_uri = f"https://management.azure.com/subscriptions/{sub_id}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"

    # 1. サービス別コスト (MonthToDate)
    service_query = json.dumps({
        "type": "Usage",
        "timeframe": "MonthToDate",
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
            "grouping": [{"name": "ServiceName", "type": "Dimension"}],
        },
    })
    code, out, _err = _run_command(
        [_get_az_exe(), "rest", "--method", "POST", "--uri", cost_uri,
         "--body", service_query, "--output", "json"],
        timeout_s=60,
    )
    if code == 0:
        try:
            data = json.loads(out)
            rows = data.get("properties", {}).get("rows", [])
            columns = [c.get("name", "") for c in data.get("properties", {}).get("columns", [])]
            services = []
            for row in rows:
                entry: dict[str, Any] = {}
                for i, col in enumerate(columns):
                    if i < len(row):
                        entry[col] = row[i]
                services.append(entry)
            services.sort(key=lambda x: x.get("PreTaxCost", 0), reverse=True)
            result["cost_by_service"] = services
        except json.JSONDecodeError:
            pass

    # 2. RG別コスト
    rg_query = json.dumps({
        "type": "Usage",
        "timeframe": "MonthToDate",
        "dataset": {
            "granularity": "None",
            "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
            "grouping": [{"name": "ResourceGroup", "type": "Dimension"}],
        },
    })
    code, out, _err = _run_command(
        [_get_az_exe(), "rest", "--method", "POST", "--uri", cost_uri,
         "--body", rg_query, "--output", "json"],
        timeout_s=60,
    )
    if code == 0:
        try:
            data = json.loads(out)
            rows = data.get("properties", {}).get("rows", [])
            columns = [c.get("name", "") for c in data.get("properties", {}).get("columns", [])]
            rg_costs = []
            for row in rows:
                entry: dict[str, Any] = {}
                for i, col in enumerate(columns):
                    if i < len(row):
                        entry[col] = row[i]
                rg_costs.append(entry)
            rg_costs.sort(key=lambda x: x.get("PreTaxCost", 0), reverse=True)
            result["cost_by_rg"] = rg_costs
        except json.JSONDecodeError:
            pass

    return result


# ============================================================
# 収集: Advisor 推奨事項
# ============================================================

def collect_advisor(subscription: str | None) -> dict[str, Any]:
    """Azure Advisor の推奨事項を収集。"""
    cmd = [_get_az_exe(), "advisor", "recommendation", "list", "--output", "json"]
    if subscription:
        cmd.extend(["--subscription", subscription])

    code, out, _err = _run_command(cmd, timeout_s=60)
    result: dict[str, Any] = {"recommendations": [], "summary": {}}

    if code == 0:
        try:
            items = json.loads(out)
            if isinstance(items, list):
                result["recommendations"] = items
                categories: dict[str, int] = {}
                for item in items:
                    cat = item.get("category", "Unknown")
                    categories[cat] = categories.get(cat, 0) + 1
                result["summary"] = categories
        except json.JSONDecodeError:
            pass

    return result


# ============================================================
# サマリ生成
# ============================================================

def type_summary(nodes: list[Node]) -> dict[str, int]:
    """type別の件数カウントを返す。"""
    return dict(Counter(n.type for n in nodes))

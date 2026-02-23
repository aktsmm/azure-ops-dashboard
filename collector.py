"""Step10: Azure Env Diagrammer — Azure収集ロジック

az graph query ラッパとデータモデル。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
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
_ARG_MAX_LIMIT = 1000


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
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout_s,
        "encoding": "utf-8",
        "errors": "replace",
    }
    # Windows: コンソール窓を非表示にする
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(args, **kwargs)
    except subprocess.TimeoutExpired as e:
        en = get_language() == "en"
        raise RuntimeError(
            (f"Command timed out after {timeout_s} seconds.\n"
             f"→ Specify a Resource Group to narrow the scope, or verify the resource-graph extension."
             if en else
             f"コマンドが {timeout_s} 秒でタイムアウトしました。\n"
             f"→ RG を指定して範囲を絞るか、resource-graph 拡張を確認してください。")
        ) from e
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
    limit = max(1, min(int(limit), _ARG_MAX_LIMIT))
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
    limit = max(1, min(int(limit), _ARG_MAX_LIMIT))
    where_clause = ""
    if resource_group:
        rg_escaped = resource_group.replace("'", "''")
        where_clause = f"| where resourceGroup =~ '{rg_escaped}'"

    # VNet / NSG / NIC / Public IP / LB / AppGW / VM (+ common network components)
    net_types = [
        "microsoft.network/virtualnetworks",
        "microsoft.network/virtualnetworkgateways",
        "microsoft.network/localnetworkgateways",
        "microsoft.network/bastionhosts",
        "microsoft.network/natgateways",
        "microsoft.network/azurefirewalls",
        "microsoft.network/routetables",
        "microsoft.network/virtualnetworkpeerings",
        "microsoft.network/networksecuritygroups",
        "microsoft.network/networkinterfaces",
        "microsoft.network/publicipaddresses",
        "microsoft.network/loadbalancers",
        "microsoft.network/applicationgateways",
        "microsoft.network/privateendpoints",
        "microsoft.network/connections",
        "microsoft.network/networkwatchers",
        "microsoft.compute/virtualmachines",
    ]
    type_filter = ", ".join(f"'{t}'" for t in net_types)

    # NOTE:
    # - If the environment has many resources, a simple `order by type` + `limit` may drop VNets.
    # - Also, VNets are often in a different RG than compute resources.
    #   We resolve references later (best-effort) to pull in missing VNets/VMs/NSGs/PIPs.
    query = textwrap.dedent(f"""
        Resources
        {where_clause}
        | where type in~ ({type_filter})
        | extend typeRank = case(
            type =~ 'microsoft.network/virtualnetworks', 0,
            type =~ 'microsoft.network/virtualnetworkgateways', 1,
            type =~ 'microsoft.network/networkinterfaces', 2,
            type =~ 'microsoft.network/publicipaddresses', 3,
            type =~ 'microsoft.network/loadbalancers', 4,
            type =~ 'microsoft.network/applicationgateways', 5,
            type =~ 'microsoft.network/networksecuritygroups', 6,
            type =~ 'microsoft.compute/virtualmachines', 7,
            50
        )
        | project id, name, type, resourceGroup, location, properties
        | order by typeRank asc, type asc, name asc
        | limit {limit}
    """).strip()

    code, out, err, rows = _az_graph_query(query=query, subscription=subscription)
    meta = {"query": query, "az_exit_code": code, "stdout": out, "stderr": err}

    if code != 0:
        raise _classify_az_error(err)

    nodes: list[Node] = []
    edges: list[Edge] = []
    azure_ids: set[str] = set()
    referenced_ids: set[str] = set()

    def _add_edge(source_id: str, target_id: str, kind: str) -> None:
        if not source_id or not target_id:
            return
        s = normalize_azure_id(source_id)
        t = normalize_azure_id(target_id)
        edges.append(Edge(source=s, target=t, kind=kind))
        referenced_ids.add(s)
        referenced_ids.add(t)

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

        # VNet has subnets[]; use it as a fallback to link subnet->vnet even if az subnet list fails.
        if lower_type == "microsoft.network/virtualnetworks":
            for sn in (props.get("subnets") or []):
                sid = (sn or {}).get("id")
                if sid:
                    _add_edge(sid, nid, "contained-in")

        # NIC → VM （virtualMachine.id）
        if lower_type == "microsoft.network/networkinterfaces":
            vm_ref = (props.get("virtualMachine") or {}).get("id")
            if vm_ref:
                _add_edge(nid, vm_ref, "attached-to")
            # NIC → NSG
            nsg_ref = (props.get("networkSecurityGroup") or {}).get("id")
            if nsg_ref:
                _add_edge(nid, nsg_ref, "secured-by")
            # NIC → Subnet (ipConfigurations[].subnet.id)
            for ipconfig in props.get("ipConfigurations") or []:
                ip_props = ipconfig.get("properties") or {}
                subnet_ref = (ip_props.get("subnet") or {}).get("id")
                if subnet_ref:
                    _add_edge(nid, subnet_ref, "in-subnet")
                # NIC → Public IP
                pip_ref = (ip_props.get("publicIPAddress") or {}).get("id")
                if pip_ref:
                    _add_edge(pip_ref, nid, "assigned-to")

        # VM → NIC (networkProfile.networkInterfaces[].id)
        if lower_type == "microsoft.compute/virtualmachines":
            nprof = (props.get("networkProfile") or {})
            for ni in nprof.get("networkInterfaces") or []:
                rid = (ni or {}).get("id")
                if rid:
                    _add_edge(rid, nid, "attached-to")

        # NSG → subnet/nic
        if lower_type == "microsoft.network/networksecuritygroups":
            for sn in (props.get("subnets") or []):
                sid = (sn or {}).get("id")
                if sid:
                    _add_edge(nid, sid, "secured-by")
            for ni in (props.get("networkInterfaces") or []):
                rid = (ni or {}).get("id")
                if rid:
                    _add_edge(rid, nid, "secured-by")

        # Private Endpoint → subnet / target resource (privateLinkServiceId)
        if lower_type == "microsoft.network/privateendpoints":
            subnet_ref = ((props.get("subnet") or {}).get("id"))
            if subnet_ref:
                _add_edge(nid, subnet_ref, "in-subnet")
            for c in (props.get("privateLinkServiceConnections") or []):
                cprops = (c or {}).get("properties") or {}
                target = cprops.get("privateLinkServiceId")
                if target:
                    _add_edge(nid, target, "connects-to")

        # NAT Gateway / Route Table associations → subnets
        if lower_type in ("microsoft.network/natgateways", "microsoft.network/routetables"):
            for sn in (props.get("subnets") or []):
                sid = (sn or {}).get("id")
                if sid:
                    _add_edge(nid, sid, "associated-with")

        # Bastion / Firewall / VNet Gateway / AppGW / LB frontend IPs → subnet or public IP
        if lower_type in (
            "microsoft.network/bastionhosts",
            "microsoft.network/azurefirewalls",
            "microsoft.network/virtualnetworkgateways",
            "microsoft.network/applicationgateways",
            "microsoft.network/loadbalancers",
        ):
            for ipcfg in (props.get("ipConfigurations") or []):
                ip_props = (ipcfg or {}).get("properties") or {}
                subnet_ref = ((ip_props.get("subnet") or {}).get("id"))
                if subnet_ref:
                    _add_edge(nid, subnet_ref, "in-subnet")
                pip_ref = ((ip_props.get("publicIPAddress") or {}).get("id"))
                if pip_ref:
                    _add_edge(pip_ref, nid, "assigned-to")
            for fe in (props.get("frontendIPConfigurations") or []):
                fe_props = (fe or {}).get("properties") or {}
                subnet_ref = ((fe_props.get("subnet") or {}).get("id"))
                if subnet_ref:
                    _add_edge(nid, subnet_ref, "in-subnet")
                pip_ref = ((fe_props.get("publicIPAddress") or {}).get("id"))
                if pip_ref:
                    _add_edge(pip_ref, nid, "assigned-to")

        # VNet peering: edge parent VNet → remote VNet
        if lower_type == "microsoft.network/virtualnetworkpeerings":
            remote = ((props.get("remoteVirtualNetwork") or {}).get("id"))
            parent_vnet = None
            marker = "/virtualnetworkpeerings/"
            if marker in nid:
                parent_vnet = nid.split(marker, 1)[0]
            if parent_vnet and remote:
                _add_edge(parent_vnet, remote, "peered-with")

        # Connections: best-effort link to gateway ids
        if lower_type == "microsoft.network/connections":
            vng1 = ((props.get("virtualNetworkGateway1") or {}).get("id"))
            vng2 = ((props.get("virtualNetworkGateway2") or {}).get("id"))
            lng2 = ((props.get("localNetworkGateway2") or {}).get("id"))
            if vng1 and vng2:
                _add_edge(vng1, vng2, "connected-to")
            if vng1 and lng2:
                _add_edge(vng1, lng2, "connected-to")

    # --- Resolve referenced resources across RG / limit truncation (best-effort) ---
    # This helps when VNets/NSGs/VMs are in a different RG than the selected one.
    max_refs = 60
    ref_stats: dict[str, Any] = {
        "referenced_total": len(referenced_ids),
        "max_refs": max_refs,
        "queried": 0,
        "resolved": 0,
        "still_missing": 0,
    }
    meta["ref_resolution"] = ref_stats

    missing = [rid for rid in referenced_ids if rid not in azure_ids]
    if missing:
        to_query = missing[:max_refs]
        ref_stats["queried"] = len(to_query)
        id_filter = ", ".join(f"'{rid}'" for rid in to_query)
        q2 = textwrap.dedent(f"""
            Resources
            | where id in~ ({id_filter})
            | project id, name, type, resourceGroup, location, properties
        """).strip()
        code2, out2, err2, rows2 = _az_graph_query(query=q2, subscription=subscription)
        meta["ref_resolution"]["query"] = q2
        meta["ref_resolution"]["az_exit_code"] = code2
        meta["ref_resolution"]["stdout"] = out2
        meta["ref_resolution"]["stderr"] = err2

        if code2 == 0:
            for row in rows2:
                azure_id = str(row.get("id") or "").strip()
                name = str(row.get("name") or "").strip()
                rtype = str(row.get("type") or "").strip()
                rg2 = str(row.get("resourceGroup") or "").strip()
                loc2 = row.get("location")
                location2 = str(loc2).strip() if loc2 is not None else None
                if not azure_id or not name or not rtype:
                    continue
                nid2 = normalize_azure_id(azure_id)
                if nid2 in azure_ids:
                    continue
                nodes.append(Node(
                    azure_id=nid2,
                    name=name,
                    type=rtype,
                    resource_group=rg2,
                    location=location2,
                ))
                azure_ids.add(nid2)
                ref_stats["resolved"] += 1

        ref_stats["still_missing"] = sum(1 for rid in missing[:max_refs] if rid not in azure_ids)

    # ノードにないターゲットへのエッジを除外（フィルタ前にSubnet収集を実行）

    # --- Subnet 収集（az network vnet subnet list を各VNet実行） ---
    vnet_nodes = [n for n in nodes if n.type.lower() == "microsoft.network/virtualnetworks"]
    max_vnets = 30
    subnet_stats: dict[str, Any] = {
        "vnets_total": len(vnet_nodes),
        "vnets_attempted": 0,
        "vnets_skipped": 0,
        "vnets_failed": 0,
        "subnets_added": 0,
        "max_vnets": max_vnets,
    }
    meta["subnet_collection"] = subnet_stats

    for vnet in vnet_nodes[:max_vnets]:
        try:
            subnet_stats["vnets_attempted"] += 1
            az_exe = _get_az_exe()

            # "All subscriptions" (subscription=None) でも subnet list が正しく動くように
            # VNet の Azure ID から subscriptionId を推定して指定する。
            sub_id = subscription
            if not sub_id:
                parts = vnet.azure_id.split("/")
                try:
                    idx = parts.index("subscriptions")
                    sub_id = parts[idx + 1] if idx + 1 < len(parts) else None
                except ValueError:
                    sub_id = None
            if not sub_id:
                subnet_stats["vnets_skipped"] += 1
                continue

            args = [
                az_exe, "network", "vnet", "subnet", "list",
                "--resource-group", vnet.resource_group,
                "--vnet-name", vnet.name,
                "--output", "json",
            ]
            args += ["--subscription", sub_id]
            code_s, out_s, _err_s = _run_command(args, timeout_s=20)
            if code_s != 0:
                subnet_stats["vnets_failed"] += 1
                continue
            subnets_raw = json.loads(out_s)
            if not isinstance(subnets_raw, list):
                subnet_stats["vnets_failed"] += 1
                continue
            for s in subnets_raw:
                sid = normalize_azure_id(str(s.get("id") or ""))
                sname = str(s.get("name") or "")
                srg = str(s.get("resourceGroup") or vnet.resource_group)
                if not sid or not sname:
                    continue
                if sid in azure_ids:
                    continue  # 重複スキップ
                nodes.append(Node(
                    azure_id=sid,
                    name=sname,
                    type="microsoft.network/virtualnetworks/subnets",
                    resource_group=srg,
                    location=vnet.location,
                ))
                azure_ids.add(sid)
                subnet_stats["subnets_added"] += 1
                # Subnet → VNet エッジ
                edges.append(Edge(source=sid, target=vnet.azure_id, kind="contained-in"))
        except Exception:
            subnet_stats["vnets_failed"] += 1
            continue  # Subnet 収集は best-effort

    # ノードにないターゲットへのエッジを除外
    edges = [e for e in edges if e.target in azure_ids and e.source in azure_ids]

    # --- Reduce noise for network diagram ---
    # Keep core topology resources, plus any endpoints that are connected via edges.
    core_types = {
        "microsoft.network/virtualnetworks",
        "microsoft.network/virtualnetworks/subnets",
        "microsoft.network/networkinterfaces",
        "microsoft.network/publicipaddresses",
        "microsoft.network/networksecuritygroups",
        "microsoft.network/loadbalancers",
        "microsoft.network/applicationgateways",
        "microsoft.network/privateendpoints",
        "microsoft.network/natgateways",
        "microsoft.network/bastionhosts",
        "microsoft.network/azurefirewalls",
        "microsoft.network/routetables",
        "microsoft.network/virtualnetworkgateways",
        "microsoft.network/localnetworkgateways",
        "microsoft.network/virtualnetworkpeerings",
        "microsoft.network/connections",
        "microsoft.compute/virtualmachines",
    }
    connected_ids: set[str] = set()
    for e in edges:
        connected_ids.add(e.source)
        connected_ids.add(e.target)

    keep_ids: set[str] = set(connected_ids)
    for n in nodes:
        if n.type.lower() in core_types:
            keep_ids.add(n.azure_id)

    nodes = [n for n in nodes if n.azure_id in keep_ids]
    edges = [e for e in edges if e.source in keep_ids and e.target in keep_ids]
    meta["network_filter"] = {
        "nodes_before": len(azure_ids),
        "nodes_after": len(nodes),
        "edges_after": len(edges),
    }

    return nodes, edges, meta


# ============================================================
# Collector registry / dispatcher
# ============================================================

def collect_diagram_view(
    *,
    view: str,
    subscription: str | None,
    resource_group: str | None,
    limit: int,
) -> tuple[list[Node], list[Edge], dict[str, Any]]:
    """diagram 系 view の収集を統一的に呼び出す。

    将来的に view を増やす際、main.py の分岐を最小化するためのディスパッチ。
    """
    limit = max(1, min(int(limit), _ARG_MAX_LIMIT))
    v = (view or "").strip().lower()
    if v == "network":
        # Network 図は topology を中心にしつつ、
        # 「箱だけ」にならないよう inventory 側のノードもマージして可視化する。
        net_nodes, net_edges, net_meta = collect_network(
            subscription=subscription, resource_group=resource_group, limit=limit
        )

        # inventory は best-effort（失敗しても network 図生成自体は継続）
        inv_nodes: list[Node] = []
        inv_meta: dict[str, Any] | None = None
        try:
            inv_nodes, inv_meta = collect_inventory(
                subscription=subscription, resource_group=resource_group, limit=limit
            )
        except Exception as e:
            net_meta["inventory_merge"] = {"enabled": False, "error": str(e)}
            return net_nodes, net_edges, net_meta

        seen: set[str] = {n.azure_id for n in net_nodes}
        added = 0
        merged_nodes = list(net_nodes)
        for n in inv_nodes:
            if n.azure_id in seen:
                continue
            merged_nodes.append(n)
            seen.add(n.azure_id)
            added += 1

        net_meta["inventory_merge"] = {
            "enabled": True,
            "network_nodes": len(net_nodes),
            "inventory_nodes": len(inv_nodes),
            "added": added,
        }
        if inv_meta is not None:
            net_meta["inventory_meta"] = inv_meta
        return merged_nodes, net_edges, net_meta

    # default: inventory
    nodes, meta = collect_inventory(subscription=subscription, resource_group=resource_group, limit=limit)
    return nodes, [], meta


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

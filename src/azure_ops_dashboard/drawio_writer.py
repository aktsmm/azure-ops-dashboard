"""Azure Ops Dashboard — .drawio XML 生成

mxfile XML を組み立てて返す。
Azure公式アイコン（img/lib/azure2/）を使用。
参考: drawio-diagram-forge スキル (https://github.com/aktsmm/Agent-Skills)

レイアウト方針:
  - リージョンコンテナ → RG コンテナ → VNet コンテナ → Subnet コンテナ の入れ子
  - 同一プレフィックスの類似リソースはグループにまとめる（代表5件 + "N more"）
  - ノイズリソース（NetworkWatcher, DefaultWorkspace 等）は折りたたみ
  - VNet 外リソースはリージョン直下
  - エッジは kind に応じてスタイル変更（peering=太破線 等）
"""

from __future__ import annotations

import hashlib
import re as _re
import uuid
from collections import defaultdict
from datetime import datetime

import xml.etree.ElementTree as ET

from collector import Node, Edge


# ============================================================
# ノード前処理: ノイズ除去 / グルーピング / ラベル短縮
# ============================================================

# ノイズとして扱うリソース種別 or 名前パターン
_NOISE_TYPE_PATTERNS: list[str] = [
    "microsoft.network/networkwatchers",
    "microsoft.operationsmanagement/solutions",
    "microsoft.alertsmanagement/smartdetectoralertrules",
    "microsoft.portal/dashboards",
]

_NOISE_NAME_PATTERNS: list[_re.Pattern[str]] = [
    _re.compile(r"^NetworkWatcher_", _re.IGNORECASE),
    _re.compile(r"^DefaultWorkspace-", _re.IGNORECASE),
    _re.compile(r"^SecurityCenterFree\(", _re.IGNORECASE),
    _re.compile(r"^Application Insights Smart Detection$", _re.IGNORECASE),
    _re.compile(r"^Failure Anomalies -", _re.IGNORECASE),
]

# グルーピング閾値（同一プレフィックスが N 件以上 → まとめる）
_GROUP_THRESHOLD = 4
# グルーピング後に表示する代表件数
_GROUP_SHOW_MAX = 3


def _is_noise(node: Node) -> bool:
    """ノイズリソースか判定する。"""
    lower_type = node.type.lower()
    for pat in _NOISE_TYPE_PATTERNS:
        if lower_type == pat:
            return True
    for pat in _NOISE_NAME_PATTERNS:
        if pat.search(node.name):
            return True
    return False


def _common_prefix(names: list[str], min_len: int = 4) -> str:
    """名前リストの共通プレフィックスを返す（ハイフン/アンダースコア境界で切る）。"""
    if not names:
        return ""
    prefix = names[0]
    for n in names[1:]:
        while not n.startswith(prefix):
            prefix = prefix[:-1]
            if len(prefix) < min_len:
                return ""
    # ハイフン/アンダースコア/空白 で切り揃え
    for sep in ("-", "_", " "):
        idx = prefix.rfind(sep)
        if idx >= min_len:
            return prefix[: idx + 1]
    return prefix if len(prefix) >= min_len else ""


def truncate_label(name: str, max_len: int = 25) -> str:
    """25文字超のラベルを省略形にする。"""
    if len(name) <= max_len:
        return name
    # 先頭と末尾を保持して中間を省略
    keep = (max_len - 3) // 2
    return name[:keep] + "..." + name[-(max_len - 3 - keep):]


def preprocess_nodes(
    nodes: list[Node],
    edges: list[Edge],
    *,
    remove_noise: bool = True,
    group_similar: bool = True,
) -> tuple[list[Node], list[Edge], list[dict]]:
    """描画前のノード前処理。

    Returns:
        (filtered_nodes, filtered_edges, groups)
        groups: [{"prefix": str, "type": str, "representative": [Node], "total": int, "hidden": [Node]}]
    """
    groups: list[dict] = []

    # 1) ノイズ除去
    noise_ids: set[str] = set()
    if remove_noise:
        kept: list[Node] = []
        noise_nodes: list[Node] = []
        for n in nodes:
            if _is_noise(n):
                noise_ids.add(n.azure_id)
                noise_nodes.append(n)
            else:
                kept.append(n)
        if noise_nodes:
            groups.append({
                "prefix": "(Infrastructure/Monitoring)",
                "type": "noise",
                "representative": noise_nodes[:2],
                "total": len(noise_nodes),
                "hidden": noise_nodes[2:],
            })
        nodes = kept

    # 2) 同一プレフィックス & 同一type のグルーピング
    if group_similar:
        # type+location ベースでグルーピング候補を探す
        by_type_loc: dict[tuple[str, str], list[Node]] = defaultdict(list)
        for n in nodes:
            key = (n.type.lower(), n.location or "")
            by_type_loc[key].append(n)

        grouped_ids: set[str] = set()
        new_nodes: list[Node] = []

        for (rtype, loc), members in by_type_loc.items():
            if len(members) < _GROUP_THRESHOLD:
                new_nodes.extend(members)
                continue
            # 共通プレフィックスを検出
            names = [m.name for m in members]
            prefix = _common_prefix(names)
            if not prefix:
                new_nodes.extend(members)
                continue
            # グルーピング
            reps = members[:_GROUP_SHOW_MAX]
            hidden = members[_GROUP_SHOW_MAX:]
            groups.append({
                "prefix": prefix,
                "type": rtype,
                "representative": reps,
                "total": len(members),
                "hidden": hidden,
            })
            # 代表ノードだけ残す + サマリノード追加
            for r in reps:
                new_nodes.append(r)
            # サマリ用ダミーノード（ + N more）
            if hidden:
                # prefix + rtype でハッシュして type 違い同名プレフィックスの衝突を防ぐ
                hash_src = f"{prefix}|{rtype}"
                summary_id = f"__group__{hashlib.sha1(hash_src.encode()).hexdigest()[:12]}"
                # RG が混在する場合は代表ノード (reps[0]) の RG を使う
                summary_node = Node(
                    azure_id=summary_id,
                    name=f"{prefix}... (+{len(hidden)} more)",
                    type=rtype,
                    resource_group=reps[0].resource_group,
                    location=loc or None,
                )
                new_nodes.append(summary_node)
                grouped_ids.update(h.azure_id for h in hidden)

        nodes = new_nodes
        noise_ids.update(grouped_ids)

    # 3) エッジフィルタ（除去ノードへのエッジを消す）
    if noise_ids:
        edges = [e for e in edges if e.source not in noise_ids and e.target not in noise_ids]

    return nodes, edges, groups


# ============================================================
# Azure リソースtype → 公式アイコン SVG パス
# cloud-icons.md 準拠: networking/ と other/ を使い分け
# ============================================================

_TYPE_ICONS: dict[str, str] = {
    # Compute
    "microsoft.compute/virtualmachines": "img/lib/azure2/compute/Virtual_Machine.svg",
    "microsoft.compute/disks": "img/lib/azure2/compute/Disks.svg",
    "microsoft.compute/availabilitysets": "img/lib/azure2/compute/Availability_Sets.svg",
    "microsoft.compute/virtualmachinescalesets": "img/lib/azure2/compute/VM_Scale_Sets.svg",
    "microsoft.compute/restorepointcollections": "img/lib/azure2/compute/Disks.svg",
    # Network — networking/
    "microsoft.network/virtualnetworks": "img/lib/azure2/networking/Virtual_Networks.svg",
    "microsoft.network/virtualnetworks/subnets": "img/lib/azure2/networking/Subnet.svg",
    "microsoft.network/networkinterfaces": "img/lib/azure2/networking/Network_Interfaces.svg",
    "microsoft.network/publicipaddresses": "img/lib/azure2/networking/Public_IP_Addresses.svg",
    "microsoft.network/networksecuritygroups": "img/lib/azure2/networking/Network_Security_Groups.svg",
    "microsoft.network/loadbalancers": "img/lib/azure2/networking/Load_Balancers.svg",
    "microsoft.network/applicationgateways": "img/lib/azure2/networking/Application_Gateways.svg",
    "microsoft.network/networkwatchers": "img/lib/azure2/networking/Network_Watcher.svg",
    "microsoft.network/connections": "img/lib/azure2/networking/Connections.svg",
    "microsoft.network/azurefirewalls": "img/lib/azure2/networking/Firewalls.svg",
    "microsoft.network/firewallpolicies": "img/lib/azure2/networking/Firewalls.svg",
    "microsoft.network/bastionhosts": "img/lib/azure2/networking/Bastions.svg",
    "microsoft.network/natgateways": "img/lib/azure2/networking/NAT.svg",
    "microsoft.network/routetables": "img/lib/azure2/networking/Route_Tables.svg",
    "microsoft.network/privateendpoints": "img/lib/azure2/networking/Private_Endpoint.svg",
    "microsoft.network/virtualnetworkgateways": "img/lib/azure2/networking/Virtual_Network_Gateways.svg",
    "microsoft.network/expressroutecircuits": "img/lib/azure2/networking/ExpressRoute_Circuits.svg",
    "microsoft.network/frontdoors": "img/lib/azure2/networking/Front_Doors.svg",
    "microsoft.network/dnszones": "img/lib/azure2/networking/DNS_Zones.svg",
    "microsoft.network/privatednszonesinternal": "img/lib/azure2/networking/DNS_Zones.svg",
    "microsoft.network/trafficmanagerprofiles": "img/lib/azure2/networking/Traffic_Manager_Profiles.svg",
    # Network — other/ (cloud-icons.md ⚠️)
    "microsoft.network/virtualnetworkpeerings": "img/lib/azure2/other/Peerings.svg",
    "microsoft.network/localnetworkgateways": "img/lib/azure2/other/Local_Network_Gateways.svg",
    "microsoft.network/privatelinkservices": "img/lib/azure2/networking/Private_Link.svg",
    "microsoft.cdn/profiles": "img/lib/azure2/networking/Front_Doors.svg",
    # Storage
    "microsoft.storage/storageaccounts": "img/lib/azure2/storage/Storage_Accounts.svg",
    # Web
    "microsoft.web/sites": "img/lib/azure2/compute/App_Services.svg",
    "microsoft.web/serverfarms": "img/lib/azure2/compute/App_Service_Plans.svg",
    # Database
    "microsoft.sql/servers": "img/lib/azure2/databases/SQL_Database.svg",
    "microsoft.documentdb/databaseaccounts": "img/lib/azure2/databases/Azure_Cosmos_DB.svg",
    "microsoft.dbforpostgresql/flexibleservers": "img/lib/azure2/databases/Azure_Database_PostgreSQL_Server.svg",
    "microsoft.dbformysql/flexibleservers": "img/lib/azure2/databases/Azure_Database_MySQL_Server.svg",
    "microsoft.cache/redis": "img/lib/azure2/databases/Cache_Redis.svg",
    # Security
    "microsoft.keyvault/vaults": "img/lib/azure2/security/Key_Vaults.svg",
    "microsoft.managedidentity/userassignedidentities": "img/lib/azure2/identity/Azure_Active_Directory.svg",
    # Containers
    "microsoft.containerregistry/registries": "img/lib/azure2/containers/Container_Registries.svg",
    "microsoft.containerservice/managedclusters": "img/lib/azure2/compute/Azure_Kubernetes_Service.svg",
    "microsoft.app/containerapps": "img/lib/azure2/other/Worker_Container_App.svg",
    "microsoft.app/managedenvironments": "img/lib/azure2/other/Container_App_Environments.svg",
    # AI / ML
    "microsoft.machinelearningservices/workspaces": "img/lib/azure2/ai_machine_learning/Machine_Learning.svg",
    "microsoft.cognitiveservices/accounts": "img/lib/azure2/ai_machine_learning/Cognitive_Services.svg",
    "microsoft.search/searchservices": "img/lib/azure2/ai_machine_learning/Cognitive_Services.svg",
    # Monitoring
    "microsoft.insights/components": "img/lib/azure2/management_governance/Application_Insights.svg",
    "microsoft.insights/actiongroups": "img/lib/azure2/management_governance/Monitor.svg",
    "microsoft.operationalinsights/workspaces": "img/lib/azure2/management_governance/Log_Analytics_Workspaces.svg",
    "microsoft.alertsmanagement/smartdetectoralertrules": "img/lib/azure2/management_governance/Monitor.svg",
    # Logic / Integration
    "microsoft.logic/workflows": "img/lib/azure2/integration/Logic_Apps.svg",
    "microsoft.automation/automationaccounts": "img/lib/azure2/management_governance/Automation_Accounts.svg",
    # Recovery
    "microsoft.recoveryservices/vaults": "img/lib/azure2/management_governance/Recovery_Services_Vaults.svg",
    "microsoft.dataprotection/backupvaults": "img/lib/azure2/management_governance/Recovery_Services_Vaults.svg",
    # Solutions / Other
    "microsoft.operationsmanagement/solutions": "img/lib/azure2/management_governance/Monitor.svg",
    "microsoft.portal/dashboards": "img/lib/azure2/management_governance/Monitor.svg",
    "microsoft.botservice/botservices": "img/lib/azure2/ai_machine_learning/Bot_Services.svg",
    "microsoft.resources/templatespecs": "img/lib/azure2/management_governance/Policy.svg",
    # DevOps
    "microsoft.devops/pipelines": "img/lib/azure2/devops/Azure_DevOps.svg",
    "microsoft.devtestlab/labs": "img/lib/azure2/devops/DevTest_Labs.svg",
}

# レイアウト列順（コンテナ内ソート順 + 後方互換テスト用）
LAYOUT_ORDER: list[str] = [
    # 外部接続
    "publicipaddresses",
    "frontdoors",
    "trafficmanagerprofiles",
    "expressroutecircuits",
    # NW中核
    "azurefirewalls",
    "loadbalancers",
    "applicationgateways",
    "bastionhosts",
    "natgateways",
    "virtualnetworkgateways",
    "localnetworkgateways",
    "connections",
    "virtualnetworkpeerings",
    # VNet / Subnet
    "networkinterfaces",
    "virtualnetworks/subnets",
    "virtualnetworks",
    "networksecuritygroups",
    "routetables",
    "privateendpoints",
    "privatelinkservices",
    # ワークロード
    "virtualmachines",
    "virtualmachinescalesets",
    "managedclusters",
    "containerapps",
    "sites",
    "serverfarms",
    # データ
    "disks",
    "storageaccounts",
    "servers",
    "databaseaccounts",
    # 管理
    "networkwatchers",
]

_LAYOUT_ORDER = LAYOUT_ORDER  # backward-compat

# ============================================================
# スタイル定義（style-guide.md 準拠）
# ============================================================

_FALLBACK_PALETTE = [
    "#E53935", "#8E24AA", "#3949AB", "#039BE5", "#00897B",
    "#7CB342", "#FDD835", "#FB8C00", "#6D4C41", "#546E7A",
    "#D81B60", "#5E35B1", "#1E88E5", "#00ACC1", "#43A047",
    "#F4511E", "#FFB300", "#8D6E63", "#78909C", "#AB47BC",
]

_REGION_FILL = "#E8EAF6"
_REGION_STROKE = "#5C6BC0"
_VNET_FILL = "#E3F2FD"
_VNET_STROKE = "#1565C0"
_SUBNET_FILL = "#F1F8E9"
_SUBNET_STROKE = "#558B2F"


def _color_for_type(rtype: str) -> str:
    lower = rtype.lower()
    idx = int(hashlib.sha1(lower.encode()).hexdigest()[:8], 16) % len(_FALLBACK_PALETTE)
    return _FALLBACK_PALETTE[idx]


# --- 公開ヘルパー (review #9: main.py のプレビュー描画用) ---


def get_type_icon(rtype: str) -> str | None:
    """type に対応する Azure 公式アイコンパスを返す。未マッピングなら None。"""
    return _TYPE_ICONS.get(rtype.lower())


def color_for_type(rtype: str) -> str:
    """type に対応するフォールバック色を返す。"""
    return _color_for_type(rtype)


def _edge_style_for_kind(kind: str) -> str:
    base = "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
    if kind in ("peered-with", "connected-to"):
        return base + "strokeWidth=3;strokeColor=#0078D4;dashed=1;dashPattern=8 4;"
    if kind == "secured-by":
        return base + "strokeWidth=1;strokeColor=#E53935;dashed=1;dashPattern=4 2;"
    if kind in ("in-subnet", "contained-in"):
        return base + "strokeWidth=1;strokeColor=#999999;"
    if kind == "assigned-to":
        return base + "strokeWidth=1;strokeColor=#0078D4;"
    if kind == "attached-to":
        return base + "strokeWidth=2;strokeColor=#333333;"
    return base


def _edge_label(kind: str) -> str:
    return {
        "peered-with": "peering",
        "connected-to": "VPN/ER",
        "secured-by": "NSG",
        "connects-to": "PE",
    }.get(kind, "")


def _icon_style(rtype: str) -> str:
    lower = rtype.lower()
    icon_path = _TYPE_ICONS.get(lower)
    if icon_path:
        return (
            f"aspect=fixed;html=1;points=[];align=center;image;fontSize=12;"
            f"image={icon_path};"
            f"verticalLabelPosition=bottom;verticalAlign=top;"
        )
    color = _color_for_type(rtype)
    return (
        f"rounded=1;whiteSpace=wrap;html=1;"
        f"fillColor={color};strokeColor=#ffffff;fontColor=#ffffff;"
        f"fontSize=11;fontFamily=Consolas;"
    )


def _title_style() -> str:
    return (
        "text;html=1;align=left;verticalAlign=middle;"
        "whiteSpace=wrap;rounded=0;fontSize=18;fontStyle=1;"
        "fontColor=#333333;fillColor=none;strokeColor=none;"
        "fontFamily=Helvetica;"
    )


def _container_style(fill: str, stroke: str, font_size: int = 14) -> str:
    return (
        f"swimlane;horizontal=1;startSize=30;fontSize={font_size};fontStyle=1;"
        f"fillColor={fill};strokeColor={stroke};fontColor=#333333;"
        f"rounded=1;shadow=0;whiteSpace=wrap;html=1;"
        f"collapsible=0;container=1;"
    )


# ============================================================
# 公開ユーティリティ
# ============================================================

def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ============================================================
# 階層構造の構築  リージョン → VNet → Subnet
# ============================================================

def _build_hierarchy(
    nodes: list[Node],
    edges: list[Edge],
) -> dict:
    """ノードとエッジから3層構造を構築して返す。"""
    node_by_id = {n.azure_id: n for n in nodes}

    def _loc_key(loc: str | None) -> str:
        # location が無い（global系や一部リソース）場合は global としてまとめる
        if loc is None:
            return "global"
        s = str(loc).strip()
        if not s:
            return "global"
        if s.lower() in ("global", "unknown"):
            return "global"
        return s

    subnet_to_vnet: dict[str, str] = {}
    node_to_subnet: dict[str, str] = {}

    for e in edges:
        if e.kind == "contained-in":
            subnet_to_vnet[e.source] = e.target
        elif e.kind == "in-subnet":
            node_to_subnet[e.source] = e.target

    # NIC → Subnet が取れている場合、NIC にアタッチされた VM も同じ Subnet とみなす
    # （network図で Subnet が空に見える問題の緩和）
    for e in edges:
        if e.kind != "attached-to":
            continue
        src = node_by_id.get(e.source)
        tgt = node_by_id.get(e.target)
        if not src or not tgt:
            continue
        src_t = src.type.lower()
        tgt_t = tgt.type.lower()
        if src_t == "microsoft.network/networkinterfaces" and tgt_t == "microsoft.compute/virtualmachines":
            sn = node_to_subnet.get(e.source)
            if sn:
                node_to_subnet.setdefault(e.target, sn)
        elif src_t == "microsoft.compute/virtualmachines" and tgt_t == "microsoft.network/networkinterfaces":
            sn = node_to_subnet.get(e.target)
            if sn:
                node_to_subnet.setdefault(e.source, sn)

    vnet_ids = {n.azure_id for n in nodes
                if n.type.lower() == "microsoft.network/virtualnetworks"}
    subnet_ids = {n.azure_id for n in nodes
                  if n.type.lower() == "microsoft.network/virtualnetworks/subnets"}

    regions: dict[str, dict] = {}
    placed: set[str] = set()

    for loc in sorted({_loc_key(n.location) for n in nodes}):
        regions[loc] = {"vnets": {}, "loose": []}

    # VNet → region
    for vid in vnet_ids:
        vnode = node_by_id.get(vid)
        if not vnode:
            continue
        loc = _loc_key(vnode.location)
        regions.setdefault(loc, {"vnets": {}, "loose": []})
        regions[loc]["vnets"][vid] = {
            "node": vnode, "subnets": {}, "direct_children": [],
        }
        placed.add(vid)

    # Subnet → VNet
    for sid in subnet_ids:
        snode = node_by_id.get(sid)
        if not snode:
            continue
        parent_vnet = subnet_to_vnet.get(sid)
        if not parent_vnet:
            parts = sid.lower().split("/subnets/")
            if len(parts) == 2:
                parent_vnet = parts[0]
        if parent_vnet and parent_vnet in vnet_ids:
            loc = _loc_key(node_by_id[parent_vnet].location)
            regions[loc]["vnets"].setdefault(parent_vnet, {
                "node": node_by_id[parent_vnet],
                "subnets": {}, "direct_children": [],
            })
            regions[loc]["vnets"][parent_vnet]["subnets"][sid] = {
                "node": snode, "children": [],
            }
        placed.add(sid)

    # 残りノード
    for n in nodes:
        if n.azure_id in placed:
            continue
        placed.add(n.azure_id)

        sn = node_to_subnet.get(n.azure_id)
        if sn:
            parent_vnet = subnet_to_vnet.get(sn)
            if not parent_vnet:
                parts = sn.lower().split("/subnets/")
                if len(parts) == 2:
                    parent_vnet = parts[0]
            if parent_vnet and parent_vnet in vnet_ids:
                loc = _loc_key(node_by_id[parent_vnet].location)
                vdata = regions[loc]["vnets"][parent_vnet]
                if sn in vdata["subnets"]:
                    vdata["subnets"][sn]["children"].append(n)
                    continue
                vdata["direct_children"].append(n)
                continue

        loc = _loc_key(n.location)
        regions.setdefault(loc, {"vnets": {}, "loose": []})
        regions[loc]["loose"].append(n)

    return {"regions": regions}


# ============================================================
# XML ビルド（コンテナレイアウト版）
# ============================================================

# レイアウト定数
_ICON_W, _ICON_H = 68, 68
_FB_W, _FB_H = 160, 44
_PAD = 20
_TITLE_H = 35
_GAP = 15


def _place_node(
    root: ET.Element,
    node: Node,
    cell_id: str,
    parent_id: str,
    x: int, y: int,
) -> None:
    """ノードを mxCell として配置する。"""
    lower_type = node.type.lower()
    has_icon = lower_type in _TYPE_ICONS
    w = _ICON_W if has_icon else _FB_W
    h = _ICON_H if has_icon else _FB_H
    style = _icon_style(node.type)

    if has_icon:
        label = truncate_label(node.name)
    else:
        short_type = node.type.split("/")[-1] if "/" in node.type else node.type
        label = f"<b>{truncate_label(node.name)}</b><br><i style='font-size:9px;'>{short_type}</i>"

    cell = ET.SubElement(root, "mxCell", {
        "id": cell_id, "value": label, "style": style,
        "vertex": "1", "parent": parent_id,
    })
    ET.SubElement(cell, "mxGeometry", {
        "x": str(x), "y": str(y),
        "width": str(w), "height": str(h),
        "as": "geometry",
    })


def build_drawio_xml(
    nodes: list[Node],
    edges: list[Edge],
    azure_to_cell_id: dict[str, str],
    diagram_name: str,
) -> str:
    """nodes/edges と ID マップから .drawio (mxfile XML) を生成して返す。

    リージョン → VNet → Subnet のコンテナ階層レイアウト。
    Azure公式アイコン対応（img/lib/azure2/ 形式）。
    前処理済みノード（preprocess_nodes 出力）を受け取ることを推奨。
    """
    hierarchy = _build_hierarchy(nodes, edges)

    mxfile = ET.Element("mxfile", {
        "host": "app.diagrams.net",
        "version": "27.0.5",
        "generator": "azure-env-diagrammer",
    })
    diagram_el = ET.SubElement(mxfile, "diagram", {
        "name": diagram_name, "id": uuid.uuid4().hex,
    })

    n_regions = len(hierarchy["regions"])
    total_vnets = sum(len(r["vnets"]) for r in hierarchy["regions"].values())
    total_nodes = len(nodes)
    # コンパクトなキャンバスサイズ計算
    canvas_w = min(2000, max(1200, (total_vnets + 1) * 400 + 200))
    canvas_h = min(3000, max(800, total_nodes * 40 + n_regions * 120))

    model = ET.SubElement(diagram_el, "mxGraphModel", {
        "dx": str(canvas_w), "dy": str(canvas_h),
        "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
        "fold": "1", "page": "1", "pageScale": "1",
        "pageWidth": str(canvas_w), "pageHeight": str(canvas_h),
        "math": "0", "shadow": "0",
    })
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    # タイトル
    tcell = ET.SubElement(root, "mxCell", {
        "id": "title1",
        "value": f"Azure Environment: {diagram_name}",
        "style": _title_style(),
        "vertex": "1", "parent": "1",
    })
    ET.SubElement(tcell, "mxGeometry", {
        "x": "20", "y": "10", "width": "600", "height": "30", "as": "geometry",
    })

    # 外枠: Azure コンテナ（リージョン/Global を内包）
    # タイトルは外側に残し、Azure コンテナはその下から開始。
    azure_cell_id = "azure_root"
    acell = ET.SubElement(root, "mxCell", {
        "id": azure_cell_id,
        "value": "Azure",
        "style": _container_style(_REGION_FILL, _REGION_STROKE, 18),
        "vertex": "1",
        "parent": "1",
    })
    ET.SubElement(acell, "mxGeometry", {
        "x": "10", "y": "50",
        "width": str(max(canvas_w - 20, 800)),
        "height": str(max(canvas_h - 60, 600)),
        "as": "geometry",
    })

    cell_id_map: dict[str, str] = {}
    region_y = _PAD

    for loc, rdata in hierarchy["regions"].items():
        region_cell_id = f"region_{hashlib.sha1(loc.encode()).hexdigest()[:8]}"

        # サイズ事前計算
        vnet_infos: list[dict] = []
        for vid, vdata in rdata["vnets"].items():
            sn_infos: list[dict] = []
            for sid, sdata in vdata["subnets"].items():
                nc = max(len(sdata["children"]), 1)
                sw = max(nc * (_ICON_W + _GAP) + _PAD * 2, 200)
                sh = _ICON_H + _PAD * 2 + _TITLE_H + 30
                sn_infos.append({"id": sid, "w": sw, "h": sh})
            nd = len(vdata["direct_children"])
            sn_w = sum(s["w"] + _GAP for s in sn_infos) + _PAD if sn_infos else 0
            dir_w = nd * (_ICON_W + _GAP) + _PAD if nd else 0
            vw = max(sn_w + dir_w + _PAD * 2, 300)
            sn_h = max((s["h"] for s in sn_infos), default=0) if sn_infos else 0
            vh = max(_TITLE_H + sn_h + _PAD * 3 + (_ICON_H + 30 if nd else 0), 200)
            vnet_infos.append({"id": vid, "w": vw, "h": vh, "subnets": sn_infos})

        n_loose = len(rdata["loose"])
        loose_cols = min(6, n_loose) if n_loose else 0
        loose_rows = (n_loose + 5) // 6
        loose_h = loose_rows * (_ICON_H + 40 + _GAP) if n_loose else 0

        vnets_total_w = (sum(v["w"] + _GAP for v in vnet_infos) + _PAD) if vnet_infos else _PAD
        vnets_max_h = max((v["h"] for v in vnet_infos), default=0)
        # loose ノードは 6 列固定で並べるため、件数に比例して幅が巨大化しないようにする
        if loose_cols:
            step = _ICON_W + _GAP + 20
            loose_w = _PAD * 2 + (loose_cols - 1) * step + _ICON_W
        else:
            loose_w = 0
        region_w = max(vnets_total_w + _PAD * 2, loose_w + _PAD * 2, 400)
        region_h = _TITLE_H + vnets_max_h + loose_h + _PAD * 4

        # リージョンコンテナ
        rcell = ET.SubElement(root, "mxCell", {
            "id": region_cell_id,
            "value": (f"\U0001f310 {loc}" if loc.lower() == "global" else f"\U0001f4cd {loc}"),
            "style": _container_style(_REGION_FILL, _REGION_STROKE, 16),
            "vertex": "1", "parent": azure_cell_id,
        })
        ET.SubElement(rcell, "mxGeometry", {
            "x": str(_PAD), "y": str(region_y),
            "width": str(region_w), "height": str(region_h),
            "as": "geometry",
        })

        vnet_x = _PAD
        vnet_y = _TITLE_H + _PAD

        for vi, vinfo in enumerate(vnet_infos):
            vid = vinfo["id"]
            vnode = rdata["vnets"][vid]["node"]
            vdata = rdata["vnets"][vid]
            vcell_id = azure_to_cell_id.get(vid, f"vnet_{vi}")
            cell_id_map[vid] = vcell_id

            vcell = ET.SubElement(root, "mxCell", {
                "id": vcell_id,
                "value": f"\U0001f517 VNet: {vnode.name}",
                "style": _container_style(_VNET_FILL, _VNET_STROKE, 14),
                "vertex": "1", "parent": region_cell_id,
            })
            ET.SubElement(vcell, "mxGeometry", {
                "x": str(vnet_x), "y": str(vnet_y),
                "width": str(vinfo["w"]), "height": str(vinfo["h"]),
                "as": "geometry",
            })

            sn_x = _PAD
            sn_y = _TITLE_H + _PAD

            for si, sinfo in enumerate(vinfo["subnets"]):
                sid = sinfo["id"]
                snode = vdata["subnets"][sid]["node"]
                children = vdata["subnets"][sid]["children"]
                scell_id = azure_to_cell_id.get(sid, f"sn_{si}")
                cell_id_map[sid] = scell_id

                scell = ET.SubElement(root, "mxCell", {
                    "id": scell_id,
                    "value": f"Subnet: {snode.name}",
                    "style": _container_style(_SUBNET_FILL, _SUBNET_STROKE, 12),
                    "vertex": "1", "parent": vcell_id,
                })
                ET.SubElement(scell, "mxGeometry", {
                    "x": str(sn_x), "y": str(sn_y),
                    "width": str(sinfo["w"]), "height": str(sinfo["h"]),
                    "as": "geometry",
                })

                cx, cy = _PAD, _TITLE_H + _PAD
                for child in children:
                    cid = azure_to_cell_id.get(child.azure_id, f"c_{uuid.uuid4().hex[:6]}")
                    cell_id_map[child.azure_id] = cid
                    _place_node(root, child, cid, scell_id, cx, cy)
                    cx += _ICON_W + _GAP

                sn_x += sinfo["w"] + _GAP

            # VNet直下ノード
            dx = sn_x + _PAD if vinfo["subnets"] else _PAD
            dy = _TITLE_H + _PAD
            for dc in vdata["direct_children"]:
                did = azure_to_cell_id.get(dc.azure_id, f"d_{uuid.uuid4().hex[:6]}")
                cell_id_map[dc.azure_id] = did
                _place_node(root, dc, did, vcell_id, dx, dy)
                dx += _ICON_W + _GAP

            vnet_x += vinfo["w"] + _GAP

        # VNet外（loose）ノード
        lx = _PAD
        ly = vnet_y + vnets_max_h + _PAD * 2
        for li, ln in enumerate(rdata["loose"]):
            lid = azure_to_cell_id.get(ln.azure_id, f"l_{uuid.uuid4().hex[:6]}")
            cell_id_map[ln.azure_id] = lid
            _place_node(root, ln, lid, region_cell_id, lx, ly)
            lx += _ICON_W + _GAP + 20
            if (li + 1) % 6 == 0:
                lx = _PAD
                ly += _ICON_H + 40 + _GAP

        region_y += region_h + 40

    # --- エッジ ---
    for edge in edges:
        src = cell_id_map.get(edge.source) or azure_to_cell_id.get(edge.source)
        tgt = cell_id_map.get(edge.target) or azure_to_cell_id.get(edge.target)
        if not src or not tgt:
            continue
        # containment はコンテナ parent で表現済み → エッジ不要
        if edge.kind in ("contained-in", "in-subnet"):
            continue
        eid = f"e{hashlib.sha1((src + '>' + tgt).encode()).hexdigest()[:12]}"
        label = _edge_label(edge.kind)
        ecell = ET.SubElement(root, "mxCell", {
            "id": eid, "value": label,
            "style": _edge_style_for_kind(edge.kind) + "fontSize=10;fontColor=#666666;",
            "edge": "1", "parent": "1", "source": src, "target": tgt,
        })
        ET.SubElement(ecell, "mxGeometry", {"relative": "1", "as": "geometry"})

    return ET.tostring(mxfile, encoding="utf-8", xml_declaration=True).decode("utf-8")

"""Step10: Azure Env Diagrammer — .drawio XML 生成

mxfile XML を組み立てて返す。
Azure公式アイコン（img/lib/azure2/）を使用。
参考: drawio-diagram-forge スキル (https://github.com/aktsmm/Agent-Skills)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

import xml.etree.ElementTree as ET

from collector import Node, Edge


# ============================================================
# Azure リソースtype → 公式アイコン SVG パス
# ============================================================

_TYPE_ICONS: dict[str, str] = {
    # Compute
    "microsoft.compute/virtualmachines": "img/lib/azure2/compute/Virtual_Machine.svg",
    "microsoft.compute/disks": "img/lib/azure2/compute/Disks.svg",
    "microsoft.compute/availabilitysets": "img/lib/azure2/compute/Availability_Sets.svg",
    "microsoft.compute/virtualmachinescalesets": "img/lib/azure2/compute/VM_Scale_Sets.svg",
    "microsoft.compute/restorepointcollections": "img/lib/azure2/compute/Disks.svg",
    # Network
    "microsoft.network/virtualnetworks": "img/lib/azure2/networking/Virtual_Networks.svg",
    "microsoft.network/networkinterfaces": "img/lib/azure2/networking/Network_Interfaces.svg",
    "microsoft.network/publicipaddresses": "img/lib/azure2/networking/Public_IP_Addresses.svg",
    "microsoft.network/networksecuritygroups": "img/lib/azure2/networking/Network_Security_Groups.svg",
    "microsoft.network/loadbalancers": "img/lib/azure2/networking/Load_Balancers.svg",
    "microsoft.network/applicationgateways": "img/lib/azure2/networking/Application_Gateways.svg",
    "microsoft.network/networkwatchers": "img/lib/azure2/networking/Network_Watcher.svg",
    "microsoft.network/connections": "img/lib/azure2/networking/Connections.svg",
    # Storage
    "microsoft.storage/storageaccounts": "img/lib/azure2/storage/Storage_Accounts.svg",
    # Web
    "microsoft.web/sites": "img/lib/azure2/compute/App_Services.svg",
    "microsoft.web/serverfarms": "img/lib/azure2/compute/App_Service_Plans.svg",
    # Database
    "microsoft.sql/servers": "img/lib/azure2/databases/SQL_Database.svg",
    "microsoft.documentdb/databaseaccounts": "img/lib/azure2/databases/Azure_Cosmos_DB.svg",
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

# フォールバック色（アイコンがないtype用）
_FALLBACK_PALETTE = [
    "#E53935", "#8E24AA", "#3949AB", "#039BE5", "#00897B",
    "#7CB342", "#FDD835", "#FB8C00", "#6D4C41", "#546E7A",
    "#D81B60", "#5E35B1", "#1E88E5", "#00ACC1", "#43A047",
    "#F4511E", "#FFB300", "#8D6E63", "#78909C", "#AB47BC",
]


def _color_for_type(rtype: str) -> str:
    """アイコンがないtypeのフォールバック色。"""
    lower = rtype.lower()
    idx = int(hashlib.sha1(lower.encode()).hexdigest()[:8], 16) % len(_FALLBACK_PALETTE)
    return _FALLBACK_PALETTE[idx]


def _icon_style(rtype: str) -> str:
    """Azure公式アイコンスタイルを返す。未マッピングは色付き矩形。"""
    lower = rtype.lower()
    icon_path = _TYPE_ICONS.get(lower)
    if icon_path:
        return (
            f"aspect=fixed;html=1;points=[];align=center;image;fontSize=12;"
            f"image={icon_path};"
            f"verticalLabelPosition=bottom;verticalAlign=top;"
        )
    else:
        color = _color_for_type(rtype)
        return (
            f"rounded=1;whiteSpace=wrap;html=1;"
            f"fillColor={color};strokeColor=#ffffff;fontColor=#ffffff;"
            f"fontSize=11;fontFamily=Consolas;"
        )


def _header_style() -> str:
    return (
        "text;html=1;align=center;verticalAlign=middle;"
        "whiteSpace=wrap;rounded=0;fontSize=13;fontStyle=1;"
        "fontColor=#333333;fillColor=none;strokeColor=none;"
        "fontFamily=Helvetica;"
    )


def _container_style() -> str:
    return (
        "swimlane;horizontal=1;startSize=30;fontSize=14;fontStyle=1;"
        "fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;"
        "rounded=1;shadow=0;whiteSpace=wrap;html=1;"
    )


# ============================================================
# 公開ユーティリティ
# ============================================================

def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ============================================================
# XML ビルド
# ============================================================

def build_drawio_xml(
    nodes: list[Node],
    edges: list[Edge],
    azure_to_cell_id: dict[str, str],
    diagram_name: str,
) -> str:
    """nodes/edges と ID マップから .drawio (mxfile XML) を生成して返す。

    Azure公式アイコン対応。マッピング済みtypeはアイコン68x68+ラベル下、
    未マッピングは色付き角丸矩形。列ヘッダー付き。
    """
    mxfile = ET.Element("mxfile", {
        "host": "app.diagrams.net",
        "version": "27.0.5",
        "generator": "azure-env-diagrammer",
    })
    diagram = ET.SubElement(mxfile, "diagram", {"name": diagram_name, "id": uuid.uuid4().hex})

    # キャンバスサイズ（ノード数に応じて拡大）
    n_types = len({n.type for n in nodes})
    max_in_col = max(
        (sum(1 for n in nodes if n.type == t) for t in {n.type for n in nodes}),
        default=1,
    )
    canvas_w = max(1600, n_types * 140)
    canvas_h = max(1200, max_in_col * 120 + 200)

    model = ET.SubElement(diagram, "mxGraphModel", {
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

    # レイアウト定数
    icon_w, icon_h = 68, 68          # アイコンサイズ（Azure公式推奨）
    fallback_w, fallback_h = 180, 50 # フォールバック矩形
    x0, y0 = 40, 80
    x_gap = 60                       # 列間（推奨50-80px）
    y_gap = 50                       # 行間（推奨40-60px）
    header_h = 30

    type_to_col: dict[str, int] = {}
    col_next = 0
    placed_in_col: dict[int, int] = {}
    col_widths: dict[int, int] = {}  # 列ごとに使用する幅

    for node in nodes:
        lower_type = node.type.lower()
        has_icon = lower_type in _TYPE_ICONS
        w = icon_w if has_icon else fallback_w
        h = icon_h if has_icon else fallback_h

        col = type_to_col.get(node.type)
        if col is None:
            col = col_next
            type_to_col[node.type] = col
            col_widths[col] = w
            col_next += 1

            # 列ヘッダー（type名）
            short_header = node.type.split("/")[-1] if "/" in node.type else node.type
            hx = _col_x(x0, col, col_widths, x_gap)
            hid = f"h{col}"
            hcell = ET.SubElement(root, "mxCell", {
                "id": hid, "value": short_header, "style": _header_style(),
                "vertex": "1", "parent": "1",
            })
            ET.SubElement(hcell, "mxGeometry", {
                "x": str(hx - 20), "y": str(y0 - header_h - 12),
                "width": str(max(w + 40, 140)), "height": str(header_h),
                "as": "geometry",
            })

        row = placed_in_col.get(col, 0)
        placed_in_col[col] = row + 1

        x = _col_x(x0, col, col_widths, x_gap)
        # アイコンの場合はラベル下で高さが大きくなる
        effective_h = (h + 30) if has_icon else h
        y = y0 + row * (effective_h + y_gap)

        cell_id = azure_to_cell_id[node.azure_id]
        style = _icon_style(node.type)

        if has_icon:
            # Azure公式アイコン: 名前はラベル下に表示
            label = node.name
        else:
            # フォールバック矩形
            short_type = node.type.split("/")[-1] if "/" in node.type else node.type
            label = f"<b>{node.name}</b><br><i style='font-size:9px;'>{short_type}</i>"

        cell = ET.SubElement(root, "mxCell", {
            "id": cell_id, "value": label, "style": style,
            "vertex": "1", "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y),
            "width": str(w), "height": str(h), "as": "geometry",
        })

    for edge in edges:
        src = azure_to_cell_id.get(edge.source)
        tgt = azure_to_cell_id.get(edge.target)
        if not src or not tgt:
            continue
        eid = f"e{hashlib.sha1((src + '>' + tgt).encode()).hexdigest()[:12]}"
        ecell = ET.SubElement(root, "mxCell", {
            "id": eid, "value": "",
            "style": "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;",
            "edge": "1", "parent": "1", "source": src, "target": tgt,
        })
        ET.SubElement(ecell, "mxGeometry", {"relative": "1", "as": "geometry"})

    return ET.tostring(mxfile, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _col_x(x0: int, col: int, col_widths: dict[int, int], x_gap: int) -> int:
    """列の X 座標を計算（各列の幅が異なる場合に対応）。"""
    x = x0
    for c in range(col):
        w = col_widths.get(c, 68)
        x += max(w + 40, 140) + x_gap
    return x

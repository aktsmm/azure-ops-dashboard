"""Step10: ユニットテスト

collector, drawio_writer, exporter, gui_helpers のテスト。
Azure CLI / Copilot SDK への接続は不要（モック化）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ---------- collector tests ----------

from collector import (
    Node, Edge, cell_id_for_azure_id, normalize_azure_id, type_summary,
)


class TestCollectorDataclasses(unittest.TestCase):
    def test_node_creation(self) -> None:
        n = Node(azure_id="/subs/1/rg/test/providers/Microsoft.Compute/vm/vm1",
                 name="vm1", type="Microsoft.Compute/virtualMachines",
                 resource_group="test", location="japaneast")
        self.assertEqual(n.name, "vm1")
        self.assertEqual(n.location, "japaneast")

    def test_edge_creation(self) -> None:
        e = Edge(source="a", target="b", kind="subnet_member")
        self.assertEqual(e.kind, "subnet_member")

    def test_cell_id_for_azure_id(self) -> None:
        aid = "/subscriptions/abc/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
        cid = cell_id_for_azure_id(aid)
        self.assertIsInstance(cid, str)
        self.assertTrue(len(cid) > 0)

    def test_normalize_azure_id(self) -> None:
        raw = "/SUBSCRIPTIONS/ABC/resourceGroups/RG1"
        normed = normalize_azure_id(raw)
        self.assertEqual(normed, raw.lower())

    def test_type_summary(self) -> None:
        nodes = [
            Node(azure_id="1", name="a", type="T1", resource_group="rg", location="loc"),
            Node(azure_id="2", name="b", type="T1", resource_group="rg", location="loc"),
            Node(azure_id="3", name="c", type="T2", resource_group="rg", location="loc"),
        ]
        s = type_summary(nodes)
        self.assertEqual(s["T1"], 2)
        self.assertEqual(s["T2"], 1)


# ---------- drawio_writer tests ----------

from drawio_writer import build_drawio_xml, now_stamp, LAYOUT_ORDER


class TestDrawioWriter(unittest.TestCase):
    def test_build_drawio_xml_basic(self) -> None:
        nodes = [
            Node(azure_id="/subs/1/vm1", name="vm1",
                 type="Microsoft.Compute/virtualMachines",
                 resource_group="rg1", location="japaneast"),
        ]
        edges: list[Edge] = []
        cell_map = {n.azure_id: cell_id_for_azure_id(n.azure_id) for n in nodes}
        xml = build_drawio_xml(nodes=nodes, edges=edges,
                               azure_to_cell_id=cell_map,
                               diagram_name="test-diagram")
        self.assertIn("<mxGraphModel", xml)
        self.assertIn("vm1", xml)
        self.assertIn("test-diagram", xml)

    def test_build_drawio_xml_empty(self) -> None:
        xml = build_drawio_xml(nodes=[], edges=[], azure_to_cell_id={},
                               diagram_name="empty")
        self.assertIn("<mxGraphModel", xml)

    def test_now_stamp_format(self) -> None:
        stamp = now_stamp()
        self.assertRegex(stamp, r"\d{8}-\d{6}")

    def test_layout_order_publicip_before_vnet(self) -> None:
        """PublicIP が VNet コンテナ外にリーフとして配置されることを検証する。"""
        nodes = [
            Node(azure_id="/subs/1/vnet1", name="vnet1",
                 type="microsoft.network/virtualnetworks",
                 resource_group="rg1", location="japaneast"),
            Node(azure_id="/subs/1/pip1", name="pip1",
                 type="microsoft.network/publicipaddresses",
                 resource_group="rg1", location="japaneast"),
        ]
        cell_map = {n.azure_id: cell_id_for_azure_id(n.azure_id) for n in nodes}
        xml = build_drawio_xml(nodes=nodes, edges=[], azure_to_cell_id=cell_map,
                               diagram_name="layout-test")
        self.assertIn("pip1", xml)
        self.assertIn("vnet1", xml)
        # PublicIP アイコンが出力されていること
        self.assertIn("Public_IP_Addresses", xml)
        # LAYOUT_ORDER で publicipaddresses が virtualnetworks より前
        from drawio_writer import LAYOUT_ORDER as LO
        self.assertLess(LO.index("publicipaddresses"), LO.index("virtualnetworks"))

    def test_layout_order_subnet_before_vnet(self) -> None:
        """Subnet が VNet コンテナ内に配置されることを検証する。"""
        nodes = [
            Node(azure_id="/subs/1/vnet1", name="vnet1",
                 type="microsoft.network/virtualnetworks",
                 resource_group="rg1", location="japaneast"),
            Node(azure_id="/subs/1/vnet1/subnets/default", name="default",
                 type="microsoft.network/virtualnetworks/subnets",
                 resource_group="rg1", location="japaneast"),
        ]
        cell_map = {n.azure_id: cell_id_for_azure_id(n.azure_id) for n in nodes}
        xml = build_drawio_xml(nodes=nodes, edges=[], azure_to_cell_id=cell_map,
                               diagram_name="subnet-layout-test")
        self.assertIn("default", xml)
        self.assertIn("vnet1", xml)
        # LAYOUT_ORDER で virtualnetworks/subnets が virtualnetworks より前
        from drawio_writer import LAYOUT_ORDER as LO
        self.assertLess(LO.index("virtualnetworks/subnets"), LO.index("virtualnetworks"))

    def test_layout_order_constant_exists(self) -> None:
        """LAYOUT_ORDER が定義されており公開 IP と VNet を含む。"""
        self.assertIn("publicipaddresses", LAYOUT_ORDER)
        self.assertIn("virtualnetworks", LAYOUT_ORDER)
        self.assertIn("networkinterfaces", LAYOUT_ORDER)
        self.assertIn("virtualnetworks/subnets", LAYOUT_ORDER)


import collector as _collector_module
from collector import collect_network


class TestSubnetCollection(unittest.TestCase):
    """collect_network が Subnet ノード/エッジを追加することを確認。"""

    def test_subnet_nodes_and_edges_added(self) -> None:
        import json as _json

        fake_vnet_id = (
            "/subscriptions/sub1/resourcegroups/rg1"
            "/providers/microsoft.network/virtualnetworks/vnet1"
        )
        fake_rows = [
            {
                "id": fake_vnet_id,
                "name": "vnet1",
                "type": "microsoft.network/virtualnetworks",
                "resourceGroup": "rg1",
                "location": "japaneast",
                "properties": {},
            }
        ]
        fake_subnet_id = fake_vnet_id + "/subnets/default"
        fake_subnet_json = _json.dumps([
            {"id": fake_subnet_id, "name": "default", "resourceGroup": "rg1"}
        ])

        def fake_az_graph_query(query, subscription=None, timeout_s=300):
            return (0, _json.dumps({"data": fake_rows}), "", fake_rows)

        def fake_run_command(args, timeout_s=300):
            if "subnet" in args and "list" in args:
                return (0, fake_subnet_json, "")
            # ARG 呼び出しは _az_graph_query で横取りされるので通常到達しない
            return (1, "", "unexpected")

        with patch.object(_collector_module, "_az_graph_query", side_effect=fake_az_graph_query), \
             patch.object(_collector_module, "_run_command", side_effect=fake_run_command):
            nodes, edges, _meta = collect_network(
                subscription="sub1", resource_group=None, limit=300
            )

        subnet_nodes = [n for n in nodes if n.type == "microsoft.network/virtualnetworks/subnets"]
        self.assertEqual(len(subnet_nodes), 1, "Subnet ノードが1件追加されるべき")
        self.assertEqual(subnet_nodes[0].name, "default")

        contained_edges = [e for e in edges if e.kind == "contained-in"]
        self.assertEqual(len(contained_edges), 1, "Subnet→VNet の contained-in エッジが1件あるべき")
        self.assertIn("subnets/default", contained_edges[0].source)

    def test_subnet_collection_failure_is_best_effort(self) -> None:
        """Subnet 収集が失敗しても collect_network が例外を投げないことを確認。"""
        import json as _json

        fake_vnet_id = (
            "/subscriptions/sub1/resourcegroups/rg1"
            "/providers/microsoft.network/virtualnetworks/vnet2"
        )
        fake_rows = [
            {
                "id": fake_vnet_id,
                "name": "vnet2",
                "type": "microsoft.network/virtualnetworks",
                "resourceGroup": "rg1",
                "location": "japaneast",
                "properties": {},
            }
        ]

        def fake_az_graph_query(query, subscription=None, timeout_s=300):
            return (0, _json.dumps({"data": fake_rows}), "", fake_rows)

        def fake_run_command_fail(args, timeout_s=300):
            # subnet list も含め常に失敗
            return (1, "", "error: something went wrong")

        with patch.object(_collector_module, "_az_graph_query", side_effect=fake_az_graph_query), \
             patch.object(_collector_module, "_run_command", side_effect=fake_run_command_fail):
            nodes, edges, _meta = collect_network(
                subscription="sub1", resource_group=None, limit=300
            )

        # VNet ノードのみ存在し、例外なく完了する
        self.assertEqual(len([n for n in nodes if "virtualnetworks" in n.type.lower()
                              and "subnets" not in n.type.lower()]), 1)


# ---------- exporter tests ----------

from exporter import (
    find_previous_report, generate_diff_report, _extract_sections,
)


class TestExporter(unittest.TestCase):
    def test_find_previous_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "security-report-20260101-000000.md").write_text("old", encoding="utf-8")
            (p / "security-report-20260102-000000.md").write_text("new", encoding="utf-8")
            prev = find_previous_report(p, "security", "security-report-20260102-000000.md")
            self.assertIsNotNone(prev)
            assert prev is not None
            self.assertIn("20260101", prev.name)

    def test_find_previous_report_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "security-report-20260101-000000.md").write_text("only", encoding="utf-8")
            prev = find_previous_report(p, "security", "security-report-20260101-000000.md")
            self.assertIsNone(prev)

    def test_generate_diff_report_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            f1 = p / "old.md"
            f2 = p / "new.md"
            content = "## Summary\nHello\n"
            f1.write_text(content, encoding="utf-8")
            f2.write_text(content, encoding="utf-8")
            result = generate_diff_report(f1, f2)
            self.assertIn("変更はありません", result)

    def test_generate_diff_report_with_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            f1 = p / "old.md"
            f2 = p / "new.md"
            f1.write_text("## Summary\nOld content\n", encoding="utf-8")
            f2.write_text("## Summary\n## New Section\nNew content\n", encoding="utf-8")
            result = generate_diff_report(f1, f2)
            self.assertIn("New Section", result)
            self.assertIn("diff", result.lower())

    def test_extract_sections(self) -> None:
        lines = ["# Title\n", "## Intro\n", "text\n", "## Details\n"]
        sections = _extract_sections(lines)
        self.assertEqual(sections, ["Intro", "Details"])


# ---------- gui_helpers tests ----------

from gui_helpers import (
    WINDOW_TITLE, ACCENT_COLOR, FONT_SIZE,
    cached_drawio_path, cached_vscode_path,
    write_text, write_json,
)


class TestGuiHelpers(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual(WINDOW_TITLE, "Azure Ops Dashboard")
        self.assertEqual(ACCENT_COLOR, "#0078d4")
        self.assertIsInstance(FONT_SIZE, int)

    def test_write_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sub" / "test.txt"
            write_text(p, "hello")
            self.assertTrue(p.exists())
            self.assertEqual(p.read_text(encoding="utf-8"), "hello")

    def test_write_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.json"
            write_json(p, {"key": "value"})
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["key"], "value")


# ---------- ai_reviewer tests (unit only, no SDK) ----------

from ai_reviewer import choose_default_model_id, build_template_instruction
from docs_enricher import enrich_with_docs, security_search_queries, cost_search_queries
from i18n import get_language, set_language


class TestAIReviewerHelpers(unittest.TestCase):
    def test_choose_default_sonnet_latest(self) -> None:
        ids = ["gpt-4.1", "claude-sonnet-4", "claude-sonnet-4.5", "claude-sonnet-4.6"]
        result = choose_default_model_id(ids)
        self.assertEqual(result, "claude-sonnet-4.6")

    def test_choose_default_no_sonnet(self) -> None:
        ids = ["gpt-4.1", "gpt-5.1"]
        result = choose_default_model_id(ids)
        self.assertEqual(result, "gpt-4.1")

    def test_choose_default_empty(self) -> None:
        result = choose_default_model_id([])
        self.assertEqual(result, "gpt-4.1")  # MODEL fallback

    def test_choose_default_unknown(self) -> None:
        ids = ["custom-model-1"]
        result = choose_default_model_id(ids)
        self.assertEqual(result, "custom-model-1")


class TestPromptAndDocs(unittest.TestCase):
    def test_build_template_instruction_english_headers(self) -> None:
        prev = get_language()
        try:
            set_language("en", persist=False)
            tmpl = {
                "sections": {
                    "s1": {"label": "概要", "label_en": "Overview", "enabled": True, "description": "desc"},
                    "s2": {"label": "詳細", "label_en": "Details", "enabled": False, "description": "desc"},
                },
                "options": {
                    "show_resource_ids": True,
                    "show_mermaid_charts": False,
                    "include_remediation": True,
                    "redact_subscription": True,
                    "max_detail_items": 3,
                    "currency_symbol": "$",
                },
            }
            out = build_template_instruction(tmpl)
            self.assertIn("## Report Structure Instructions", out)
            self.assertIn("### Included sections", out)
            self.assertIn("### Excluded sections", out)
            self.assertIn("### Output options", out)
            self.assertIn("Show full Resource IDs", out)
            self.assertIn("Redact subscription IDs", out)
        finally:
            set_language(prev, persist=False)

    def test_build_template_instruction_japanese_headers(self) -> None:
        prev = get_language()
        try:
            set_language("ja", persist=False)
            tmpl = {"sections": {"s1": {"label": "概要", "enabled": True}}, "options": {}}
            out = build_template_instruction(tmpl)
            self.assertIn("## レポート構成指示", out)
            self.assertIn("### 含めるセクション", out)
        finally:
            set_language(prev, persist=False)

    def test_docs_queries_include_waf_caf(self) -> None:
        sec = security_search_queries([])
        cost = cost_search_queries([])
        self.assertTrue(any("Well-Architected" in q for q in sec))
        self.assertTrue(any("Cloud Adoption Framework" in q for q in sec))
        self.assertTrue(any("Well-Architected" in q for q in cost))
        self.assertTrue(any("Cloud Adoption Framework" in q for q in cost))

    def test_enrich_with_docs_includes_waf_static_refs_en(self) -> None:
        prev = get_language()
        try:
            set_language("en", persist=False)
            block = enrich_with_docs([], report_type="security", resource_types=[], on_status=lambda _s: None)
            self.assertIn("Well-Architected", block)
            self.assertIn("Cloud Adoption Framework", block)
        finally:
            set_language(prev, persist=False)


class TestAISanitizer(unittest.TestCase):
    def test_sanitize_extracts_markdown_from_tool_input_json(self) -> None:
        from ai_reviewer import _sanitize_ai_markdown

        raw = (
            "Let me create the report.\n\n"
            "<tool_call>\n"
            "<tool_name>CreateFile</tool_name>\n"
            "<tool_input type=\"json\">{\"filePath\":\"x.md\",\"content\":\"# Integrated Report\\n\\n## A\\nBody\\n\"}</tool_input>\n"
            "</tool_call>\n"
        )
        out = _sanitize_ai_markdown(raw)
        self.assertTrue(out.startswith("# Integrated Report"))
        self.assertIn("## A", out)
        self.assertNotIn("<tool_call>", out)

    def test_sanitize_one_line_tool_calls_does_not_swallow_report(self) -> None:
        from ai_reviewer import _sanitize_ai_markdown

        raw = (
            "<tool_calls><tool_call>noop</tool_call></tool_calls>\n\n"
            "# Report\n"
            "Body\n"
        )
        out = _sanitize_ai_markdown(raw)
        self.assertTrue(out.startswith("# Report"))
        self.assertIn("Body", out)
        self.assertNotIn("tool_call", out.lower())

    def test_sanitize_drops_tool_blocks_keeps_report(self) -> None:
        from ai_reviewer import _sanitize_ai_markdown

        raw = """Preamble

<tool_calls>
<tool_call>
X
</tool_call>
</tool_calls>

# Report
Body
"""
        out = _sanitize_ai_markdown(raw)
        self.assertTrue(out.startswith("# Report"))
        self.assertNotIn("<tool_calls>", out)


if __name__ == "__main__":
    unittest.main()

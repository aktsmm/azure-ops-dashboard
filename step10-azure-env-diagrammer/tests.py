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

from drawio_writer import build_drawio_xml, now_stamp


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

from ai_reviewer import choose_default_model_id


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


if __name__ == "__main__":
    unittest.main()

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

PATH = pathlib.Path(__file__).resolve().parents[1] / "kamra" / "sarawat_erp_mcp.py"

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.frappe = types.ModuleType("frappe")
        self.frappe.conf = {}
        self.frappe.get_list = Mock(return_value=[])
        self.frappe.get_doc = Mock()
        spec = importlib.util.spec_from_file_location("isolated_review", PATH)
        self.bridge = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": self.frappe}):
            spec.loader.exec_module(self.bridge)
        self.bridge._gate = Mock()

    def test_gate_failure_prevents_reads(self):
        self.bridge._gate.side_effect = PermissionError
        for fn in (self.bridge.journal_get, self.bridge.posting_status, self.bridge.customers, self.bridge.ledger_entries):
            with self.assertRaises(PermissionError):
                fn("P", "test")
        self.frappe.get_list.assert_not_called()
        self.frappe.get_doc.assert_not_called()

    def test_unbound_customers_not_exposed(self):
        self.assertEqual(self.bridge.customers("P", "test"), [])
        self.frappe.get_list.assert_not_called()

    def test_customer_scope(self):
        self.frappe.conf["kamra_finance_approved_folios"] = {
            "F1": {"company":"sarawatpark","property":"P","customer":"Allowed"},
            "F2": {"company":"sarawatpark","property":"Other","customer":"Forbidden"}}
        self.bridge.customers("P", "Allowed")
        self.assertEqual(self.frappe.get_list.call_args.kwargs["filters"]["name"], ["in", ["Allowed"]])

    def test_wildcard_rejected(self):
        with self.assertRaises(ValueError):
            self.bridge.customers("P", "%%")
        self.frappe.get_list.assert_not_called()

    def test_unlinked_journal_rejected(self):
        with self.assertRaises(ValueError):
            self.bridge.journal_get("P", "JV-1")
        self.frappe.get_doc.assert_not_called()

    def test_cross_property_source_rejected(self):
        self.frappe.get_doc.return_value = types.SimpleNamespace(property="Other", check_permission=Mock())
        with self.assertRaises(ValueError):
            self.bridge.posting_status("P", "entry")
        self.frappe.get_list.assert_not_called()

    def test_ledger_cross_property(self):
        self.frappe.get_doc.return_value = types.SimpleNamespace(property="Other", check_permission=Mock())
        with self.assertRaises(ValueError):
            self.bridge.ledger_entries("P", "F1")
        self.frappe.get_list.assert_not_called()

    def test_ledger_pagination_and_scope(self):
        doc = types.SimpleNamespace(property="P", check_permission=Mock())
        self.frappe.get_doc.return_value = doc
        self.frappe.get_list.return_value = [{"name": "L1"}, {"name": "L2"}]
        result = self.bridge.ledger_entries("P", "F1", offset=2, limit=1)
        self.assertEqual(result["entries"], [{"name": "L1"}])
        self.assertEqual(result["next_offset"], 3)
        doc.check_permission.assert_called_once_with("read")
        args = self.frappe.get_list.call_args.kwargs
        self.assertEqual(args["filters"], {"property": "P", "folio": "F1"})
        self.assertEqual(args["limit_start"], 2)
        self.assertEqual(args["limit_page_length"], 2)

    def test_ledger_invalid_pagination(self):
        for offset, limit in ((-1, 1), (0, 201), (0, True)):
            with self.assertRaises(ValueError):
                self.bridge.ledger_entries("P", "F1", offset, limit)
        self.frappe.get_doc.assert_not_called()

if __name__ == "__main__":
    unittest.main()

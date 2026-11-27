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

    def test_period_movements_excludes_cancelled(self):
        self.bridge.general_ledger = Mock(return_value={"entries": [
            {"name":"G1","account":"A","debit":10,"credit":0,"is_cancelled":0},
            {"name":"G2","account":"B","debit":0,"credit":10,"is_cancelled":0},
            {"name":"G3","account":"A","debit":99,"credit":0,"is_cancelled":1}],
            "next_offset":None})
        result = self.bridge.period_movements("P", "2026-11-26", "2026-11-26")
        self.assertEqual(result["total_debit"], "10")
        self.assertEqual(result["difference"], "0")

    def test_balance_review_separates_opening(self):
        self.bridge.period_movements = Mock(side_effect=[
            {"accounts":[{"account":"A","net_debit":"20"}]},
            {"accounts":[{"account":"A","debit":"10","credit":"5"}]}])
        result = self.bridge.balance_review("P", "2026-11-26", "2026-11-27", "2026-11-25")
        self.assertEqual(result["accounts"][0]["closing_net_debit"], "25")
        self.assertEqual(result["accounts"][0]["opening_net_debit"], "20")

    def test_balance_review_handles_last_supported_date(self):
        self.bridge.period_movements = Mock(return_value={"accounts": []})
        result = self.bridge.balance_review("P", "9999-12-31", "9999-12-31", "9999-12-31")
        self.assertEqual(result["accounts"], [])
        self.bridge.period_movements.assert_called_once_with("P", "9999-12-31", "9999-12-31")

    def test_balance_review_rejects_invalid_interval(self):
        with self.assertRaises(ValueError):
            self.bridge.balance_review("P", "2026-11-26", "2026-11-25", "2026-11-24")

    def test_control_review_blocks_submitted_journal(self):
        self.bridge.journal_get = Mock(return_value={"docstatus":1,
            "record":{"status":"Posted"}, "rows":[], "total_debit":0, "total_credit":0})
        self.frappe.get_doc.return_value = types.SimpleNamespace(name="sarawatpark", check_permission=Mock())
        result = self.bridge.journal_control_review("P", "JV")
        self.assertEqual(result["status"], "Blocked")

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

    def test_general_ledger_disabled(self):
        self.frappe.PermissionError = PermissionError
        self.frappe.throw = Mock(side_effect=PermissionError)
        with self.assertRaises(PermissionError):
            self.bridge.general_ledger("P", "2026-11-26", "2026-11-26")
        self.frappe.get_list.assert_not_called()

    def test_general_ledger_scope(self):
        self.frappe.conf["sarawat_erp_company_ledger_read_enabled"] = 1
        self.frappe.get_list.return_value = [{"name": "G1"}, {"name": "G2"}]
        result = self.bridge.general_ledger("P", "2026-11-26", "2026-11-26", limit=1)
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(result["entries"], [{"name": "G1"}])
        args = self.frappe.get_list.call_args.kwargs
        self.assertEqual(args["filters"]["company"], "sarawatpark")
        self.assertEqual(args["filters"]["posting_date"], ["between", ["2026-11-26", "2026-11-26"]])
        self.assertIn("is_cancelled", args["fields"])

    def test_general_ledger_rejects_invalid_dates(self):
        self.frappe.conf["sarawat_erp_company_ledger_read_enabled"] = 1
        for start, end in (("2026-01-01", "2026-03-01"), ("2026-11-27", "2026-11-26"), ("invalid", "2026-11-26")):
            with self.assertRaises(ValueError):
                self.bridge.general_ledger("P", start, end)
        self.frappe.get_list.assert_not_called()

    def reversal_fixture(self):
        common = dict(property="P", folio="F1", source_doctype="Folio Charge",
                      ledger="Guest", transaction_code="1200", check_permission=Mock())
        original = types.SimpleNamespace(**common, name="L1", reversal_of=None, debit=1050, credit=0)
        reversal = types.SimpleNamespace(**common, name="L2", reversal_of="L1", debit=0, credit=1050, business_date="2026-11-26")
        self.frappe.get_doc.side_effect = [reversal, original]
        self.bridge.posting_status = Mock(side_effect=[{"records":[{"status":"Posted","journal_entry":"JV1"}]}, {"records":[]}])
        self.bridge.journal_get = Mock(return_value={"docstatus":1,"record":{"status":"Posted"},"journal":"JV1","total_debit":1050,"total_credit":1050,
            "rows":[{"account":"AR","debit":1050,"credit":0,"party":"C1"},{"account":"Revenue","debit":0,"credit":1000},{"account":"VAT","debit":0,"credit":50}]})
        self.frappe.get_list.return_value = [{"name":"L2","folio":"F1"}]
        return original, reversal

    def test_reversal_review_full_charge(self):
        self.reversal_fixture()
        result = self.bridge.reversal_review("P", "L2")
        self.assertEqual(result["original_journal"], "JV1")
        self.assertEqual(result["status"], "Needs Review")
        self.assertEqual([r["debit"] for r in result["rows"]], [0,1000,50])
        self.assertEqual([r["credit"] for r in result["rows"]], [1050,0,0])
        self.assertEqual(result["rows"][0]["party"], "C1")

    def test_reversal_review_cross_property(self):
        original, reversal = self.reversal_fixture()
        original.property = "Other"
        with self.assertRaises(ValueError):
            self.bridge.reversal_review("P", "L2")
        self.bridge.posting_status.assert_not_called()

    def test_reversal_review_partial_rejected(self):
        original, reversal = self.reversal_fixture()
        reversal.credit = 1000
        with self.assertRaises(ValueError):
            self.bridge.reversal_review("P", "L2")
        self.bridge.posting_status.assert_not_called()

    def test_reversal_review_unsubmitted_rejected(self):
        self.reversal_fixture()
        self.bridge.journal_get.return_value["docstatus"] = 0
        with self.assertRaises(ValueError):
            self.bridge.reversal_review("P", "L2")

    def test_reversal_review_gate(self):
        self.bridge._gate.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            self.bridge.reversal_review("P", "L2")
        self.frappe.get_doc.assert_not_called()

    def test_reversal_review_duplicate_source(self):
        self.reversal_fixture()
        self.frappe.get_list.return_value.append({"name":"L3","folio":"F1"})
        with self.assertRaises(ValueError):
            self.bridge.reversal_review("P", "L2")

    def test_reversal_review_existing_record(self):
        self.reversal_fixture()
        self.bridge.posting_status.side_effect = [{"records":[{"status":"Posted","journal_entry":"JV1"}]}, {"records":[{"status":"Draft Created","journal_entry":"JV2"}]}]
        result = self.bridge.reversal_review("P", "L2")
        self.assertEqual(result["status"], "Already Recorded")

if __name__ == "__main__":
    unittest.main()

"""Read-only ERP bridge for the explicitly configured Sarawat agent."""
import frappe

def _gate(property):
    if (frappe.conf.get("sarawat_erp_mcp_enabled") != 1
        or frappe.session.user != "agent@kamra.local"
        or property != frappe.conf.get("kamra_finance_property")
        or frappe.conf.get("kamra_finance_company") != "sarawatpark"
        or "kamra_erpnext_integration" not in frappe.get_installed_apps()):
        frappe.throw("ERP bridge not authorized", frappe.PermissionError)
    from kamra_erpnext_integration.review_api import _scope
    _scope()

def accounts(property, offset=0, limit=100):
    _gate(property)
    from kamra_erpnext_integration.review_api import list_accounts
    return list_accounts(offset=offset, limit=limit)

def mappings(property, offset=0, limit=100):
    _gate(property)
    from kamra_erpnext_integration.review_api import list_mappings
    return list_mappings(offset=offset, limit=limit)

def cost_centers(property):
    _gate(property)
    return frappe.get_list("Cost Center", filters={"company":"sarawatpark"},
        fields=["name","cost_center_number","cost_center_name","is_group","disabled","parent_cost_center"],
        order_by="name asc", limit_page_length=200)

def journal_preview(property, entry_id):
    _gate(property)
    from kamra_erpnext_integration.preview_api import preview
    return preview(entry_id=entry_id)

def journal_draft(property, entry_id):
    _gate(property)
    if frappe.conf.get("sarawat_erp_mcp_draft_enabled") != 1:
        frappe.throw("ERP draft bridge disabled", frappe.PermissionError)
    from kamra_erpnext_integration.draft_api import create_draft
    return create_draft(entry_id=entry_id)

def journal_get(property, journal):
    _gate(property)
    if not isinstance(journal, str) or not journal.strip() or len(journal) > 140:
        raise ValueError("Invalid journal identity")
    records = frappe.get_list("Kamra Posting Record", filters={
        "company": "sarawatpark", "source_property": property, "journal_entry": journal},
        fields=["name", "status", "source_key"], limit_page_length=2)
    if len(records) != 1:
        raise ValueError("Unique scoped posting record required")
    doc = frappe.get_doc("Journal Entry", journal)
    doc.check_permission("read")
    if doc.company != "sarawatpark":
        raise ValueError("Company mismatch")
    return {"journal": doc.name, "docstatus": doc.docstatus,
        "posting_date": str(doc.posting_date), "record": records[0],
        "total_debit": doc.total_debit, "total_credit": doc.total_credit,
        "rows": [{"account": row.account, "debit": row.debit_in_account_currency,
                  "credit": row.credit_in_account_currency, "cost_center": row.cost_center,
                  "party_type": row.party_type, "party": row.party} for row in doc.accounts]}

def posting_status(property, entry_id):
    _gate(property)
    import hashlib
    import json
    if not isinstance(entry_id, str) or not entry_id.strip() or len(entry_id) > 140:
        raise ValueError("Invalid entry identity")
    ledger = frappe.get_doc("Folio Ledger Entry", entry_id)
    ledger.check_permission("read")
    if ledger.property != property or ledger.source_doctype not in ("Folio Charge", "Folio Payment") or not ledger.source_name:
        raise ValueError("Unsupported source")
    def key(*parts):
        return hashlib.sha256(json.dumps(["sarawatpark", property, *parts]).encode()).hexdigest()
    keys = [key(ledger.source_doctype, ledger.source_name),
            key(ledger.source_doctype, ledger.source_name, "advance_applied"),
            key("folio_ledger", entry_id)]
    return {"entry_id": entry_id, "records": frappe.get_list("Kamra Posting Record",
        filters={"company": "sarawatpark", "source_property": property, "source_key": ["in", keys]},
        fields=["name", "source_key", "status", "journal_entry"], limit_page_length=10),
        "scope": "integration records only; not proof of absence of other postings"}

for fn in (accounts, mappings, cost_centers, journal_preview, journal_draft, journal_get, posting_status):
    fn._kamra_roles = ("System Manager",)

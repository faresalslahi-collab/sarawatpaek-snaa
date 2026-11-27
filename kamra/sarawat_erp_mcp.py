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
    siblings = frappe.get_list("Folio Ledger Entry", filters={"property": property, "source_doctype": ledger.source_doctype, "source_name": ledger.source_name}, fields=["name", "folio"], limit_page_length=5)
    if not siblings or len(siblings) > 3 or any(row.folio != ledger.folio for row in siblings) or entry_id not in [row.name for row in siblings]:
        raise ValueError("Ambiguous source scope")
    keys = [key(ledger.source_doctype, ledger.source_name),
            key(ledger.source_doctype, ledger.source_name, "advance_applied"),
            * [key("folio_ledger", row.name) for row in siblings]]
    return {"entry_id": entry_id, "records": frappe.get_list("Kamra Posting Record",
        filters={"company": "sarawatpark", "source_property": property, "source_key": ["in", keys]},
        fields=["name", "source_key", "status", "journal_entry"], limit_page_length=10),
        "scope": "integration records only; not proof of absence of other postings"}

def customers(property, search):
    _gate(property)
    if not isinstance(search, str) or not 2 <= len(search.strip()) <= 100 or any(c in search for c in "%_"):
        raise ValueError("Specific customer search required")
    bindings = frappe.conf.get("kamra_finance_approved_folios") or {}
    if not isinstance(bindings, dict):
        raise ValueError("Invalid approved folio bindings")
    allowed = sorted({b["customer"] for b in bindings.values() if isinstance(b, dict) and b.get("company") == "sarawatpark" and b.get("property") == property and isinstance(b.get("customer"), str) and b["customer"]})
    if not allowed:
        return []
    return frappe.get_list("Customer", filters={"disabled": 0, "name": ["in", allowed]},
        or_filters={"name": ["like", "%" + search.strip() + "%"],
                    "customer_name": ["like", "%" + search.strip() + "%"]},
        fields=["name", "customer_name"], order_by="name asc", limit_page_length=30)

def ledger_entries(property, folio, offset=0, limit=100):
    _gate(property)
    if not isinstance(folio, str) or not folio.strip() or len(folio) > 140:
        raise ValueError("Invalid folio identity")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Invalid pagination")
    doc = frappe.get_doc("Folio", folio)
    doc.check_permission("read")
    if doc.property != property:
        raise ValueError("Property mismatch")
    rows = frappe.get_list("Folio Ledger Entry",
        filters={"property": property, "folio": folio},
        fields=["name", "folio", "business_date", "ledger", "source_doctype",
                "source_name", "description", "debit", "credit", "transaction_code",
                "reversal_of"],
        order_by="business_date asc, name asc", limit_start=offset,
        limit_page_length=limit + 1)
    return {"folio": folio, "entries": rows[:limit],
            "next_offset": offset + limit if len(rows) > limit else None,
            "scope": "Folio ledger only; not ERP general ledger"}

def general_ledger(property, from_date, to_date, offset=0, limit=100):
    _gate(property)
    from datetime import date
    if frappe.conf.get("sarawat_erp_company_ledger_read_enabled") != 1:
        frappe.throw("Company-wide ledger access disabled", frappe.PermissionError)
    if not all(isinstance(v, str) and len(v) == 10 for v in (from_date, to_date)):
        raise ValueError("ISO dates required")
    start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
    if start > end or (end - start).days > 31:
        raise ValueError("Date range must not exceed 32 days")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Invalid pagination")
    rows = frappe.get_list("GL Entry", filters={"company": "sarawatpark",
        "posting_date": ["between", [from_date, to_date]]},
        fields=["name", "posting_date", "account", "debit", "credit",
                "voucher_type", "voucher_no", "party_type", "party",
                "cost_center", "is_cancelled"],
        order_by="posting_date asc, name asc", limit_start=offset,
        limit_page_length=limit + 1)
    return {"company": "sarawatpark", "entries": rows[:limit],
            "next_offset": offset + limit if len(rows) > limit else None,
            "scope": "Permission-filtered company GL, including cancellation rows; not proof of source identity"}

for fn in (general_ledger, ledger_entries, accounts, mappings, cost_centers, journal_preview, journal_draft, journal_get, posting_status, customers):
    fn._kamra_roles = ("System Manager",)

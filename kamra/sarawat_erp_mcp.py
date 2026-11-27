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

def reversal_review(property, entry_id):
    _gate(property)
    from decimal import Decimal
    if not isinstance(entry_id, str) or not entry_id.strip() or len(entry_id) > 140:
        raise ValueError("Invalid reversal identity")
    reversal = frappe.get_doc("Folio Ledger Entry", entry_id)
    reversal.check_permission("read")
    if reversal.property != property or not reversal.reversal_of:
        raise ValueError("Scoped reversal required")
    original = frappe.get_doc("Folio Ledger Entry", reversal.reversal_of)
    original.check_permission("read")
    if (original.property != property or original.folio != reversal.folio
        or original.reversal_of or original.source_doctype != "Folio Charge"
        or reversal.source_doctype != "Folio Charge"
        or original.ledger != "Guest" or reversal.ledger != "Guest"
        or original.transaction_code != reversal.transaction_code
        or Decimal(str(original.debit)) <= 0 or original.credit or reversal.debit
        or Decimal(str(original.debit)) != Decimal(str(reversal.credit))):
        raise ValueError("Only full guest charge reversals supported")
    records = posting_status(property, original.name)["records"]
    if len(records) != 1 or records[0]["status"] != "Posted":
        raise ValueError("Unique posted original required")
    journal = journal_get(property, records[0]["journal_entry"])
    if journal["docstatus"] != 1 or journal["record"]["status"] != "Posted":
        raise ValueError("Submitted original required")
    if Decimal(str(journal["total_debit"])) != Decimal(str(original.debit)) or journal["total_debit"] != journal["total_credit"]:
        raise ValueError("Original amount mismatch")
    reversals = frappe.get_list("Folio Ledger Entry",
        filters={"property": property, "reversal_of": original.name},
        fields=["name", "folio"], limit_page_length=2)
    if len(reversals) != 1 or reversals[0]["name"] != entry_id or reversals[0]["folio"] != original.folio:
        raise ValueError("Unique visible reversal required")
    existing = posting_status(property, entry_id)["records"]
    return {"entry_id": entry_id, "original_entry": original.name,
            "original_journal": journal["journal"], "folio": original.folio,
            "business_date": str(reversal.business_date),
            "existing_records": existing,
            "rows": [{**row, "debit": row["credit"], "credit": row["debit"]} for row in journal["rows"]],
            "status": "Already Recorded" if existing else "Needs Review",
            "scope": "Read-only proposal; manual duplicate, currency and period review required before saving"}

def period_movements(property, from_date, to_date):
    """Summarize visible GL movements, not opening or closing balances."""
    from decimal import Decimal
    totals = {}
    seen = set()
    offset = 0
    while True:
        page = general_ledger(property, from_date, to_date, offset=offset, limit=200)
        for row in page["entries"]:
            if row["name"] in seen:
                raise ValueError("Ledger changed during pagination")
            seen.add(row["name"])
            if row["is_cancelled"]:
                continue
            account = row["account"]
            pair = totals.setdefault(account, [Decimal(0), Decimal(0)])
            pair[0] += Decimal(str(row["debit"]))
            pair[1] += Decimal(str(row["credit"]))
        offset = page["next_offset"]
        if offset is None:
            break
        if offset >= 10000:
            raise ValueError("Narrow the reporting period")
    debit = sum((v[0] for v in totals.values()), Decimal(0))
    credit = sum((v[1] for v in totals.values()), Decimal(0))
    return {"from_date": from_date, "to_date": to_date,
            "accounts": [{"account": k, "debit": str(v[0]), "credit": str(v[1]),
                          "net_debit": str(v[0]-v[1])} for k,v in sorted(totals.items())],
            "total_debit": str(debit), "total_credit": str(credit),
            "difference": str(debit-credit),
            "scope": "Visible non-cancelled period movements only; not a trial balance or consistent database snapshot"}

def folio_reconciliation(property, folio):
    _gate(property)
    page = ledger_entries(property, folio, limit=200)
    if page["next_offset"] is not None:
        raise ValueError("Folio exceeds review limit")
    results = []
    for row in page["entries"]:
        item = {"entry_id": row["name"], "source_name": row["source_name"],
                "description": row["description"], "debit": row["debit"],
                "credit": row["credit"], "reversal_of": row["reversal_of"]}
        if row["source_doctype"] not in ("Folio Charge", "Folio Payment"):
            item["status"] = "Unsupported source"
        else:
            records = posting_status(property, row["name"])["records"]
            item["records"] = records
            item["status"] = "Review linked records" if records else "No visible integration record"
            if row["reversal_of"]:
                item["status"] = "Review reversal"
        results.append(item)
    return {"folio": folio, "entries": results,
            "scope": "Integration record review only; shared payment records do not establish operation-level posting or absence of manual GL entries"}

def balance_review(property, from_date, to_date, opening_from):
    """Bounded visible-ledger balance review, including prior movements."""
    from datetime import date, timedelta
    from decimal import Decimal
    _gate(property)
    start, end, opening = map(date.fromisoformat, (from_date, to_date, opening_from))
    if opening > start or start > end or (end-opening).days > 366:
        raise ValueError("Invalid review interval; maximum 367 days")
    totals = {}
    cursor = opening
    while cursor <= end:
        boundary = min(end, cursor + timedelta(days=31))
        if cursor < start:
            boundary = min(boundary, start-timedelta(days=1))
        report = period_movements(property, cursor.isoformat(), boundary.isoformat())
        for row in report["accounts"]:
            values = totals.setdefault(row["account"], [Decimal(0), Decimal(0), Decimal(0)])
            if cursor < start:
                values[0] += Decimal(row["net_debit"])
            else:
                values[1] += Decimal(row["debit"])
                values[2] += Decimal(row["credit"])
        cursor = boundary + timedelta(days=1)
    return {"opening_from": opening_from, "from_date": from_date, "to_date": to_date,
            "accounts": [{"account": account, "opening_net_debit": str(v[0]),
                          "debit": str(v[1]), "credit": str(v[2]),
                          "closing_net_debit": str(v[0]+v[1]-v[2])}
                         for account, v in sorted(totals.items())],
            "scope": "Permission-filtered movements since supplied opening date; excludes earlier balances and is not a certified trial balance"}

def journal_control_review(property, journal):
    _gate(property)
    from decimal import Decimal
    doc = journal_get(property, journal)
    blockers = []
    if doc["docstatus"] != 0 or doc["record"]["status"] != "Draft Created":
        blockers.append("Journal is not a linked draft")
    company = frappe.get_doc("Company", "sarawatpark")
    company.check_permission("read")
    debit = credit = Decimal(0)
    for row in doc["rows"]:
        account = frappe.get_doc("Account", row["account"])
        account.check_permission("read")
        if (account.company != company.name or account.is_group or account.disabled
            or account.account_currency != company.default_currency):
            blockers.append("Invalid or non-company-currency account: " + account.name)
        d, c = Decimal(str(row["debit"])), Decimal(str(row["credit"]))
        if not d.is_finite() or not c.is_finite() or min(d,c) < 0 or (d > 0) == (c > 0):
            raise ValueError("Invalid journal row amounts")
        debit += d
        credit += c
        if account.account_type in ("Receivable", "Payable") and not (row["party_type"] and row["party"]):
            blockers.append("Missing party: " + account.name)
        if not row["cost_center"]:
            blockers.append("Missing cost center: " + account.name)
        else:
            center = frappe.get_doc("Cost Center", row["cost_center"])
            center.check_permission("read")
            if center.company != company.name or center.is_group or center.disabled:
                blockers.append("Invalid cost center: " + center.name)
    if debit <= 0 or debit != credit or debit != Decimal(str(doc["total_debit"])) or credit != Decimal(str(doc["total_credit"])):
        blockers.append("Journal totals mismatch")
    return {"journal": journal, "blockers": blockers,
            "status": "Blocked" if blockers else "Preliminary checks passed",
            "scope": "Read-only checks; source identity, duplicate audit, accounting period and explicit approval remain required. Not authorization to submit."}

for fn in (journal_control_review, balance_review, folio_reconciliation, period_movements, reversal_review, general_ledger, ledger_entries, accounts, mappings, cost_centers, journal_preview, journal_draft, journal_get, posting_status, customers):
    fn._kamra_roles = ("System Manager",)

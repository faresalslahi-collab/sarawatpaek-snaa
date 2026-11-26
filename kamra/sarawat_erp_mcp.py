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

for fn in (accounts, mappings, cost_centers, journal_preview):
    fn._kamra_roles = ("System Manager",)

"""Read-only diagnostics for the Sarawat administrator."""
import frappe

@frappe.whitelist(methods=["GET"])
def draft_status():
    frappe.only_for("System Manager")
    from kamra.authz import assert_property_access
    from kamra.mcp_access import property_policy, mcp_level
    from kamra.mcp_tools import BY_NAME, module_allowed
    prop = frappe.conf.get("kamra_finance_property")
    if not prop or frappe.conf.get("kamra_finance_company") != "sarawatpark":
        frappe.throw("Sarawat scope required", frappe.PermissionError)
    assert_property_access(prop)
    agent = "agent@kamra.local"
    policy = property_policy(prop)
    spec = BY_NAME.get("erp_journal_draft")
    roles = set(frappe.get_roles(agent))
    flag = frappe.conf.get("sarawat_erp_mcp_draft_enabled")
    return {
        "diagnostic_revision": 1,
        "registered": spec is not None,
        "bridge_enabled": frappe.conf.get("sarawat_erp_mcp_enabled") == 1,
        "draft_enabled": flag == 1,
        "draft_flag_type": type(flag).__name__,
        "agent_enabled": bool(frappe.db.get_value("User", agent, "enabled")),
        "agent_system_manager": "System Manager" in roles,
        "agent_mcp_level": mcp_level(agent),
        "property_enabled": policy.enabled,
        "property_read_only": policy.read_only,
        "draft_blocked": "erp_journal_draft" in policy.blocked,
        "module_allowed": bool(spec and module_allowed(spec, property=prop)),
        "integration_installed": "kamra_erpnext_integration" in frappe.get_installed_apps(),
        "draft_api_enabled": frappe.conf.get("kamra_finance_draft_api_enabled") == 1,
        "save_enabled": frappe.conf.get("kamra_finance_save_drafts") == 1,
    }

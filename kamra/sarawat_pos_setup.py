"""Provision Sarawat outlets explicitly; no automatic migration or financial writes."""
import frappe

OUTLETS = (
    ("المجالس العامة والتذاكر", "Other"),
    ("الشيش", "Other"),
    ("البقالة", "Shop"),
    ("المغسلة", "Other"),
    ("المجالس الخاصة", "Other"),
    ("قاعة الأفراح", "Other"),
)


@frappe.whitelist(methods=["POST"])
def provision():
    """Administrator-only, idempotent setup; never overwrite existing outlets."""
    if frappe.session.user != "Administrator":
        frappe.throw("Administrator required", frappe.PermissionError)
    property_id = frappe.conf.get("kamra_finance_property")
    if property_id != "فندق ومنتجع السروات بارك":
        frappe.throw("Sarawat property scope required")
    prop = frappe.get_doc("Property", property_id)
    prop.check_permission("write")
    frappe.db.sql("SELECT name FROM `tabProperty` WHERE name = %s FOR UPDATE", (property_id,))
    created = []
    existing = []
    frappe.db.savepoint("sarawat_pos_setup")
    try:
        for title, kind in OUTLETS:
            name = f"{property_id}-{title}"
            if frappe.db.exists("POS Outlet", name):
                existing.append(name)
                continue
            doc = frappe.get_doc({
                "doctype": "POS Outlet",
                "property": property_id,
                "outlet_name": title,
                "outlet_type": kind,
                "gst_rate": 0,
                "levy_percent": 0,
                "print_barcode": 1,
                "receipt_design": "Columns",
                "disabled": 0,
            })
            doc.insert()
            created.append(doc.name)
    except Exception:
        frappe.db.rollback(save_point="sarawat_pos_setup")
        raise
    return {"created": created, "existing": existing}

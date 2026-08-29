import io

import frappe
from frappe import _

from wedding_plan.import_excel import build_template_workbook, run_import


@frappe.whitelist()
def download_import_template():
    """GET /api/method/wedding_plan.api.download_import_template
    Returns a blank .xlsx with one sheet per importable doctype, headers
    matching the live field list — so the sheet template can never drift
    from what run_import() actually accepts.
    Intentionally has no frappe.has_permission gate (unlike every other
    endpoint in this module) — it exposes only field-name schema, no
    tenant data, so any authenticated caller may download it."""
    wb = build_template_workbook()
    buf = io.BytesIO()
    wb.save(buf)
    frappe.local.response.filename = "wedding_plan_import_template.xlsx"
    frappe.local.response.filecontent = buf.getvalue()
    frappe.local.response.type = "download"


@frappe.whitelist()
def import_excel(wedding, file_url):
    """POST /api/method/wedding_plan.api.import_excel {wedding, file_url}
    file_url comes from Frappe's stock /api/method/upload_file endpoint —
    upload there first, then pass the returned file_url here."""
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted to import into this wedding"))

    file_doc = frappe.get_doc("File", {"file_url": file_url})
    # file_url is a hash-like path, not a secret — without this check any
    # caller who can write to *some* wedding could read the content of a
    # file uploaded (and privately owned) by a different tenant simply by
    # guessing/observing its URL. Only the uploader (or a System Manager)
    # may import it.
    if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to use this file"))
    file_path = file_doc.get_full_path()

    job = frappe.get_doc({
        "doctype": "WD Import Job",
        "wedding": wedding,
        "file": file_url,
        "status": "Processing",
        "created_by_user": frappe.session.user,
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    result = run_import(wedding, file_path, import_job=job.name)
    return {"import_job": job.name, **result}

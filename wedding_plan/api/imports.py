import io

import frappe
from frappe import _
from frappe.utils import cint

from wedding_plan.guest_import import build_guest_template_workbook, import_guest_families
from wedding_plan.import_excel import build_template_workbook, run_import


def _import_file_path(file_url):
    """The on-disk path behind an uploaded `file_url`, ownership-checked.

    file_url is a hash-like path, not a secret — without this check any
    caller who can write to *some* wedding could read the content of a file
    uploaded (and privately owned) by a different tenant simply by
    guessing/observing its URL. Only the uploader (or a System Manager) may
    import it.
    """
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to use this file"))
    return file_doc.get_full_path()


def _xlsx_download(workbook, filename):
    buf = io.BytesIO()
    workbook.save(buf)
    frappe.local.response.filename = filename
    frappe.local.response.filecontent = buf.getvalue()
    frappe.local.response.type = "download"


@frappe.whitelist()
def download_import_template():
    """GET /api/method/wedding_plan.api.download_import_template
    Returns a blank .xlsx with one sheet per importable doctype, headers
    matching the live field list — so the sheet template can never drift
    from what run_import() actually accepts.
    Intentionally has no frappe.has_permission gate (unlike every other
    endpoint in this module) — it exposes only field-name schema, no
    tenant data, so any authenticated caller may download it."""
    _xlsx_download(build_template_workbook(), "wedding_plan_import_template.xlsx")


@frappe.whitelist()
def download_guest_import_template():
    """GET /api/method/wedding_plan.api.download_guest_import_template
    Blank one-sheet .xlsx for the Guest Family importer, headed with the
    field *labels* a planner reads on that page ("Household", "Mobile",
    "Sub Group", ...). Generated from live meta, same no-tenant-data
    reasoning as download_import_template above."""
    _xlsx_download(build_guest_template_workbook(), "guest_family_import_template.xlsx")


@frappe.whitelist()
def import_excel(wedding, file_url):
    """POST /api/method/wedding_plan.api.import_excel {wedding, file_url}
    file_url comes from Frappe's stock /api/method/upload_file endpoint —
    upload there first, then pass the returned file_url here."""
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted to import into this wedding"))

    file_path = _import_file_path(file_url)

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


@frappe.whitelist()
def preview_guest_import(wedding, file_url, create_missing_links=1):
    """POST /api/method/wedding_plan.api.preview_guest_import
         {wedding, file_url, create_missing_links}

    A full dry run of the Guest Family importer: every column mapped, every
    cell validated, every link resolved — and **nothing written**. Returns
    the same shape as `import_guest_families` so the UI renders one review
    table before and after committing.

    Gated on Wedding *write*, not read, deliberately: it reports which
    existing households a sheet would overwrite, which is write-shaped
    information, and it is only ever the step before a write.
    """
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted to import into this wedding"))

    return import_guest_families(
        wedding,
        _import_file_path(file_url),
        dry_run=True,
        create_missing_links=bool(cint(create_missing_links)),
    )


@frappe.whitelist()
def import_guest_families_excel(wedding, file_url, create_missing_links=1):
    """POST /api/method/wedding_plan.api.import_guest_families_excel
         {wedding, file_url, create_missing_links}

    Upserts `WD Guest` rows from one flat sheet, matched on the Mobile
    column: a number already on this wedding's list updates that household,
    a new number creates one. Blank cells are never written, so a partial
    sheet tops rows up instead of blanking them.

    Same upload-then-import flow as `import_excel`: POST the file to
    Frappe's stock /api/method/upload_file first and pass the `file_url`
    that comes back. Recorded as a `WD Import Job` either way, so a bad
    import is traceable after the browser tab is closed.
    """
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted to import into this wedding"))

    file_path = _import_file_path(file_url)

    job = frappe.get_doc({
        "doctype": "WD Import Job",
        "wedding": wedding,
        "file": file_url,
        "status": "Processing",
        "created_by_user": frappe.session.user,
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    result = import_guest_families(
        wedding,
        file_path,
        dry_run=False,
        create_missing_links=bool(cint(create_missing_links)),
        import_job=job.name,
    )
    return {"import_job": job.name, **result}

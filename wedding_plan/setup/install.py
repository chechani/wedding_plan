"""
Creates/updates every DocType in doctype_specs.py. Runs on `bench install-app
wedding_plan` (after_install) and again on every `bench migrate`
(after_migrate, via patches.txt's post_model_sync hook) so editing
doctype_specs.py and migrating is the whole workflow for schema changes —
no hand-written JSON fixtures to keep in sync.
"""
import json

import frappe

from wedding_plan.setup.doctype_specs import DOCTYPES, PLANNER_ROLE


def after_install():
    create_role()
    sync_all_doctypes()
    frappe.db.commit()


def after_migrate():
    create_role()
    sync_all_doctypes()


def create_role():
    if not frappe.db.exists("Role", PLANNER_ROLE):
        frappe.get_doc({
            "doctype": "Role",
            "role_name": PLANNER_ROLE,
            "desk_access": 1,
        }).insert(ignore_permissions=True)


def sync_all_doctypes():
    for spec in DOCTYPES:
        _sync_one(spec)
    frappe.clear_cache()


def _fields_for(spec):
    fields = [dict(f) for f in spec["fields"]]
    if spec.get("wedding_scoped"):
        fields = [
            {
                "fieldname": "wedding",
                "label": "Wedding",
                "fieldtype": "Link",
                "options": "Wedding",
                "reqd": 1,
                "in_list_view": 1,
                "in_standard_filter": 1,
            }
        ] + fields
    return fields


def _sync_one(spec):
    # Note: only ADDS fields that are missing by fieldname on an existing
    # DocType — it won't retroactively change an already-created field's
    # type/options/default if you edit one in doctype_specs.py later. For
    # that, edit the field through Desk (Customize Form) or drop and
    # recreate the DocType in a dev site. Permissions ARE fully re-synced
    # from the spec every run.
    name = spec["name"]
    fields = _fields_for(spec)

    if frappe.db.exists("DocType", name):
        doc = frappe.get_doc("DocType", name)
        existing = {f.fieldname for f in doc.fields}
        for f in fields:
            if f["fieldname"] not in existing:
                doc.append("fields", f)
        doc.permissions = []
        for p in spec["permissions"]:
            doc.append("permissions", p)
        doc.save(ignore_permissions=True)
        return

    doc = frappe.new_doc("DocType")
    doc.name = name
    doc.module = spec["module"]
    doc.custom = 0
    doc.istable = spec.get("istable", 0)
    doc.autoname = spec.get("autoname", "hash")
    if spec.get("title_field"):
        doc.title_field = spec["title_field"]
    for f in fields:
        doc.append("fields", f)
    for p in spec["permissions"]:
        doc.append("permissions", p)
    doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Convenience used by api.py when a brand-new wedding is created: makes the
# creating user a Wedding Member with role Owner and grants them the
# Wedding Planner role if they don't already have it.
# ---------------------------------------------------------------------------

def ensure_planner_role(user: str):
    user_doc = frappe.get_doc("User", user)
    if not any(r.role == PLANNER_ROLE for r in user_doc.roles):
        user_doc.append("roles", {"role": PLANNER_ROLE})
        user_doc.save(ignore_permissions=True)

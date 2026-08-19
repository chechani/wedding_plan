"""
Runs on `bench install-app wedding_plan` (after_install) and again on every
`bench migrate` (after_migrate). DocType schemas live as native Frappe JSON
fixtures under wedding_plan/wedding_plan/doctype/ and are created/updated by
Frappe itself as part of migrate, so this module only creates the "Wedding
Planner" Role — a data record, not part of any DocType's schema, so it isn't
covered by that sync.
"""
import frappe

from wedding_plan.setup.doctype_specs import PLANNER_ROLE


def after_install():
    create_role()
    frappe.db.commit()


def after_migrate():
    create_role()


def create_role():
    if not frappe.db.exists("Role", PLANNER_ROLE):
        frappe.get_doc({
            "doctype": "Role",
            "role_name": PLANNER_ROLE,
            "desk_access": 1,
        }).insert(ignore_permissions=True)


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

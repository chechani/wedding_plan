import frappe
from wedding_plan.setup.doctype_specs import get_wedding_scoped_doctypes

app_name = "wedding_plan"
app_title = "Wedding Plan"
app_publisher = "Smarty Software Pvt Ltd"
app_description = "Multi-tenant wedding planning backend "
app_email = "ca.bc.chechani@gmail.com"
app_license = "mit"

after_install = "wedding_plan.setup.install.after_install"
after_migrate = "wedding_plan.setup.install.after_migrate"

_scoped = get_wedding_scoped_doctypes() + ["Wedding"]

permission_query_conditions = {
    dt: f"wedding_plan.permissions.query_conditions__{frappe.scrub(dt)}" for dt in _scoped
}
has_permission = {
    dt: f"wedding_plan.permissions.has_permission__{frappe.scrub(dt)}" for dt in _scoped
}

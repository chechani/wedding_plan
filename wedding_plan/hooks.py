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

# Global (not wedding-scoped) reference/master-list doctypes shipped with the
# app so a fresh install isn't missing standard vocabulary — previously only
# populated by manually running wedding_plan.setup.seed_task_masters.run.
# Order matters: WD Task Subtype links to WD Task Category, and WD Task
# Checklist Template Item links to WD Task Subtype, so each must sync after
# the one it depends on.
#
# Deliberately NOT here:
#   - WD City, WD Gifting Type — per-wedding data (Gifting Type even carries
#     its own `wedding` field), not a fixed vocabulary the app should ship.
#   - WD Invitation Channel — has its own idempotent seed in setup/install.py
#     that only inserts channels that don't exist yet, specifically so a
#     planner's edits (e.g. disabling one) survive future migrates. Fixture
#     sync re-imports and overwrites on every migrate, which would undo that.
#   - WD Function Type — already auto-seeds via the one-time patch
#     patches/seed_function_types.py; left as-is rather than duplicated here.
fixtures = [
    "WD Unit",
    "WD Task Status",
    "WD Vendor Type",
    "WD Service Style",
    "WD Meal Session Type",
    "WD Crockery Type",
    "WD Menu Category",
    "WD Flower Type",
    "WD Sound Element",
    "WD Light Element",
    "WD SFX Type",
    "WD Permit Type",
    "WD Hamper Tier",
    "WD Payment Mode",
    "WD Patrika Delivery Mode",
    "WD Task Category",
    "WD Task Subtype",
    "WD Task Checklist Template Item",
]

_scoped = get_wedding_scoped_doctypes() + ["Wedding"]

permission_query_conditions = {
    dt: f"wedding_plan.permissions.query_conditions__{frappe.scrub(dt)}" for dt in _scoped
}
has_permission = {
    dt: f"wedding_plan.permissions.has_permission__{frappe.scrub(dt)}" for dt in _scoped
}

# Doctypes whose changes matter to another coordinator's already-open /live
# tab (implementation plan §14) — a curated subset of the wedding-scoped
# list, not all of it. Planning-only doctypes (WD Venue, WD Vendor, ...)
# don't need a live nudge, since nobody is staring at /live waiting on them
# to change; these are the ones the day board's timeline and Attention band
# actually read. See wedding_plan/realtime.py for why this targets each
# member's user room rather than a custom "wedding:<name>" room.
_REALTIME_DOCTYPES = [
    "WD Pickup",
    "WD Convoy Leg",
    "WD Transport Movement",
    "WD Vehicle Assignment",
    "WD Room Allotment",
    "WD Menu",
    "WD Event Issue",
]
doc_events = {
    dt: {"on_update": "wedding_plan.realtime.notify_event_update"} for dt in _REALTIME_DOCTYPES
}

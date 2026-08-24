"""
Planner-facing guest/attendance APIs. Kept entirely separate from
wedding_plan/api/guest_portal.py (guest-facing, self-service only) — this
module operates at full wedding-scoped visibility, guest_portal.py never
does.
"""
import frappe


@frappe.whitelist()
def function_headcount_stats(wedding, function=None):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	filters = {"wedding": wedding}
	if function:
		filters["function"] = function

	rows = frappe.get_all("WD Guest Member Function", filters=filters, fields=["function", "status"])

	by_function = {}
	for r in rows:
		bucket = by_function.setdefault(
			r.function, {"invited": 0, "confirmed": 0, "declined": 0, "attended": 0, "no_show": 0, "total_members": 0}
		)
		bucket["total_members"] += 1
		key = r.status.lower().replace(" ", "_")
		if key in bucket:
			bucket[key] += 1

	functions = frappe.get_all("WD Function", filters={"wedding": wedding}, fields=["name", "function_name"], order_by="date asc")
	if function:
		functions = [f for f in functions if f.name == function]

	# Household-level "invited" cross-check (WD Guest.functions_invited).
	# WD Guest Function rows aren't wedding-scoped on their own, so filter by
	# this wedding's household names — one query per function, kept cheap
	# since a wedding has a handful of functions.
	household_names = frappe.get_all("WD Guest", filters={"wedding": wedding}, pluck="name")
	household_invite_counts = {}
	for f in functions:
		household_invite_counts[f.name] = frappe.db.count(
			"WD Guest Function",
			filters={"wd_function": f.name, "parenttype": "WD Guest", "parent": ["in", household_names]},
		)

	return [
		{
			"function": f.name,
			"function_name": f.function_name,
			"households_invited": household_invite_counts.get(f.name, 0),
			**by_function.get(f.name, {"invited": 0, "confirmed": 0, "declined": 0, "attended": 0, "no_show": 0, "total_members": 0}),
		}
		for f in functions
	]

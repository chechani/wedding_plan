"""
Function readiness checklist: per-Function readiness items (decoration,
catering, activities, ...) each with a Vendor-or-Team responsible party and
optional readiness photos. Mirrors api/tasks.py's split — plain REST
(/api/resource/WD Function Checklist Item) covers ordinary CRUD; these
bespoke methods are for the board view's cross-doctype joins and the
per-function readiness summary, same reasoning as task_board()/
task_dashboard_stats().
"""
import frappe

from wedding_plan.task_logic import resolve_contact_point

STATUSES = ["Pending", "In Progress", "Ready", "Blocked"]


def _enrich(items):
	vendor_ids = {i.responsible_vendor for i in items if i.responsible_vendor}
	vendor_names = {}
	if vendor_ids:
		for row in frappe.get_all("WD Vendor", filters={"name": ["in", list(vendor_ids)]}, fields=["name", "vendor_name"]):
			vendor_names[row.name] = row.vendor_name

	team_ids = {i.responsible_team for i in items if i.responsible_team}
	team_names = {}
	if team_ids:
		for row in frappe.get_all("WD Team", filters={"name": ["in", list(team_ids)]}, fields=["name", "team_name"]):
			team_names[row.name] = row.team_name

	function_ids = {i.function for i in items if i.function}
	function_names = {}
	if function_ids:
		for row in frappe.get_all("WD Function", filters={"name": ["in", list(function_ids)]}, fields=["name", "function_name"]):
			function_names[row.name] = row.function_name

	responsible_name_by_type = {"Team": team_names, "Vendor": vendor_names}
	responsible_field_by_type = {"Team": "responsible_team", "Vendor": "responsible_vendor"}

	attachment_counts = {}
	item_ids = [i.name for i in items]
	if item_ids:
		for row in frappe.get_all("WD Checklist Attachment", filters={"parent": ["in", item_ids]}, fields=["parent"]):
			attachment_counts[row.parent] = attachment_counts.get(row.parent, 0) + 1

	out = []
	for i in items:
		contact = resolve_contact_point(
			i.responsible_type,
			assigned_team=i.responsible_team,
			assigned_vendor=i.responsible_vendor,
		)
		responsible_name = None
		if i.responsible_type:
			ref = i.get(responsible_field_by_type[i.responsible_type])
			responsible_name = responsible_name_by_type[i.responsible_type].get(ref)

		out.append(
			{
				**i,
				"function_name": function_names.get(i.function),
				"responsible_name": responsible_name,
				"contact_name": contact["contact_name"],
				"contact_phone": contact["contact_phone"],
				"attachment_count": attachment_counts.get(i.name, 0),
			}
		)
	return out


@frappe.whitelist()
def checklist_board(wedding, function=None, category=None, status=None, responsible_type=None):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	filters = {"wedding": wedding}
	if function:
		filters["function"] = function
	if category:
		filters["category"] = category
	if status:
		filters["status"] = status
	if responsible_type:
		filters["responsible_type"] = responsible_type

	items = frappe.get_all(
		"WD Function Checklist Item",
		filters=filters,
		fields=[
			"name",
			"function",
			"category",
			"item",
			"status",
			"responsible_type",
			"responsible_vendor",
			"responsible_team",
			"check_by",
			"notes",
			"blocked_reason",
		],
		order_by="creation asc",
	)
	return _enrich(items)


@frappe.whitelist()
def function_readiness_stats(wedding):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	items = frappe.get_all("WD Function Checklist Item", filters={"wedding": wedding}, fields=["name", "function", "status"])

	total_by_function = {}
	ready_by_function = {}
	for i in items:
		if not i.function:
			continue
		total_by_function[i.function] = total_by_function.get(i.function, 0) + 1
		if i.status == "Ready":
			ready_by_function[i.function] = ready_by_function.get(i.function, 0) + 1

	functions = frappe.get_all("WD Function", filters={"wedding": wedding}, fields=["name", "function_name"], order_by="date asc")
	return [
		{
			"function": f.name,
			"function_name": f.function_name,
			"total": total_by_function.get(f.name, 0),
			"ready": ready_by_function.get(f.name, 0),
		}
		for f in functions
	]

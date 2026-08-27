"""
Tasks & Coordination module: the cross-cutting task/todo list — every task
optionally tied to a Function, assigned to a Team/Vendor/Person, with a
contact point surfaced so the planner can just call the right person.

Design notes:
  - Plain REST (/api/resource/WD Task) covers ordinary CRUD; these bespoke
    methods are for aggregation (dashboard) and cross-doctype joins/live
    contact resolution (board) — same split api/invitations.py uses.
  - task_board() re-resolves contact info live via task_logic, rather than
    trusting the stored contact_* fields (which only refresh when a task is
    next saved) — this is the read path that matters most for "call the
    right person right now".
  - task_dashboard_stats() left-joins against WD Function so a function with
    zero tasks still shows up as a visible gap, instead of just vanishing —
    this is the "ensure nothing is missed" coverage view standing in for a
    template/checklist generator (deferred to a later version).
"""
import frappe
from frappe import _
from frappe.utils import today

from wedding_plan.task_logic import resolve_contact_point

STATUSES = ["Not Started", "In Progress", "Blocked", "Done", "Cancelled"]


def _enrich(tasks):
	function_ids = {t.function for t in tasks if t.function}
	function_types = {}
	if function_ids:
		for row in frappe.get_all("WD Function", filters={"name": ["in", list(function_ids)]}, fields=["name", "function_type"]):
			function_types[row.name] = row.function_type

	vendor_ids = {t.assigned_vendor for t in tasks if t.assigned_vendor}
	vendor_names = {}
	if vendor_ids:
		for row in frappe.get_all("WD Vendor", filters={"name": ["in", list(vendor_ids)]}, fields=["name", "vendor_name"]):
			vendor_names[row.name] = row.vendor_name

	team_ids = {t.assigned_team for t in tasks if t.assigned_team}
	team_names = {}
	if team_ids:
		for row in frappe.get_all("WD Team", filters={"name": ["in", list(team_ids)]}, fields=["name", "team_name"]):
			team_names[row.name] = row.team_name

	person_ids = {t.assigned_person for t in tasks if t.assigned_person}
	person_names = {}
	if person_ids:
		for row in frappe.get_all("User", filters={"name": ["in", list(person_ids)]}, fields=["name", "full_name"]):
			person_names[row.name] = row.full_name

	assignee_name_by_type = {"Team": team_names, "Vendor": vendor_names, "Person": person_names}
	assignee_field_by_type = {"Team": "assigned_team", "Vendor": "assigned_vendor", "Person": "assigned_person"}

	out = []
	for t in tasks:
		contact = resolve_contact_point(
			t.assigned_to_type,
			assigned_team=t.assigned_team,
			assigned_vendor=t.assigned_vendor,
			assigned_person=t.assigned_person,
		)
		assignee_name = None
		if t.assigned_to_type:
			ref = t.get(assignee_field_by_type[t.assigned_to_type])
			assignee_name = assignee_name_by_type[t.assigned_to_type].get(ref)

		out.append(
			{
				**t,
				"function_type": function_types.get(t.function),
				"assignee_name": assignee_name,
				"contact_name": contact["contact_name"],
				"contact_phone": contact["contact_phone"],
				"contact_secondary_name": contact["contact_secondary_name"],
				"contact_secondary_phone": contact["contact_secondary_phone"],
			}
		)
	return out


@frappe.whitelist()
def task_board(wedding, function=None, category=None, status=None, assigned_to_type=None, overdue=False):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	filters = {"wedding": wedding}
	if function:
		filters["function"] = function
	if category:
		filters["category"] = category
	if status:
		filters["status"] = status
	if assigned_to_type:
		filters["assigned_to_type"] = assigned_to_type
	if frappe.parse_json(overdue):
		filters["due_date"] = ["<", today()]
		filters["status"] = ["not in", ["Done", "Cancelled"]]

	tasks = frappe.get_all(
		"WD Task",
		filters=filters,
		fields=[
			"name",
			"title",
			"category",
			"status",
			"priority",
			"function",
			"venue",
			"due_date",
			"completed_date",
			"assigned_to_type",
			"assigned_team",
			"assigned_vendor",
			"assigned_person",
			"blocked_reason",
			"description",
		],
		order_by="due_date asc, creation desc",
	)
	return _enrich(tasks)


@frappe.whitelist()
def task_dashboard_stats(wedding):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	tasks = frappe.get_all("WD Task", filters={"wedding": wedding}, fields=["name", "status", "category", "function", "due_date"])

	by_status = {s: 0 for s in STATUSES}
	by_category = {}
	overdue = 0
	for t in tasks:
		by_status[t.status] = by_status.get(t.status, 0) + 1
		by_category[t.category] = by_category.get(t.category, 0) + 1
		if t.due_date and str(t.due_date) < today() and t.status not in ("Done", "Cancelled"):
			overdue += 1

	task_counts_by_function = {}
	done_counts_by_function = {}
	for t in tasks:
		if not t.function:
			continue
		task_counts_by_function[t.function] = task_counts_by_function.get(t.function, 0) + 1
		if t.status == "Done":
			done_counts_by_function[t.function] = done_counts_by_function.get(t.function, 0) + 1

	functions = frappe.get_all("WD Function", filters={"wedding": wedding}, fields=["name", "function_type"], order_by="date asc")
	by_function = [
		{
			"function": f.name,
			"function_type": f.function_type,
			"task_count": task_counts_by_function.get(f.name, 0),
			"done_count": done_counts_by_function.get(f.name, 0),
		}
		for f in functions
	]

	return {
		"total": len(tasks),
		"by_status": by_status,
		"by_category": by_category,
		"by_function": by_function,
		"overdue": overdue,
	}


@frappe.whitelist()
def bulk_update_task_status(wedding, task_names, status, blocked_reason=None):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	if isinstance(task_names, str):
		task_names = frappe.parse_json(task_names)

	results = []
	for name in task_names:
		try:
			task = frappe.get_doc("WD Task", name)
			if task.wedding != wedding:
				frappe.throw(_("Task {0} does not belong to this wedding.").format(name))
			task.status = status
			if blocked_reason is not None:
				task.blocked_reason = blocked_reason
			task.save()
			results.append({"task": name, "ok": True, "status": task.status})
		except Exception as e:
			frappe.local.message_log = []
			results.append({"task": name, "ok": False, "error": str(e)})

	return {
		"updated": len([r for r in results if r["ok"]]),
		"failed": len([r for r in results if not r["ok"]]),
		"results": results,
	}

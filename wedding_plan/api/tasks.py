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

from wedding_plan.task_logic import batch_lookup_titles, resolve_contact_point, resolve_polymorphic_name


def _enrich(tasks):
	function_types = batch_lookup_titles("WD Function", (t.function for t in tasks), "function_type")
	vendor_names = batch_lookup_titles("WD Vendor", (t.assigned_vendor for t in tasks), "vendor_name")
	team_names = batch_lookup_titles("WD Team", (t.assigned_team for t in tasks), "team_name")
	person_names = batch_lookup_titles("User", (t.assigned_person for t in tasks), "full_name")

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
		assignee_name = resolve_polymorphic_name(t.assigned_to_type, assignee_field_by_type, t, assignee_name_by_type)

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
			"subtype",
			"status",
			"priority",
			"function",
			"venue",
			"due_date",
			"completed_date",
			"depends_on_task",
			"assigned_to_type",
			"assigned_team",
			"assigned_vendor",
			"assigned_person",
			"shadow_backup",
			"vendor",
			"estimated_cost",
			"actual_cost",
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

	by_status = {s: 0 for s in frappe.get_all("WD Task Status", pluck="name")}
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
	"""Set `status` (and `blocked_reason` when moving to Blocked) on every
	task in `task_names` that belongs to `wedding` — a task outside this
	wedding is skipped with an error in its own result row rather than
	failing the whole batch. Backs the task board's multi-select bulk
	action."""
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


@frappe.whitelist()
def get_task_subtype_detail(task):
	"""Backs the task drawer's "Open <Subtype> Detail Sheet ->" link.
	Returns {doctype, name} for the auto-created detail record (see
	WDTask._ensure_subtype_detail), or None if the task has no subtype
	or the subtype has no structured detail sheet."""
	row = frappe.db.get_value("WD Task", task, ["wedding", "subtype"])
	if not row:
		frappe.throw(_("Task {0} not found").format(task), frappe.DoesNotExistError)
	wedding, subtype = row
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	if not subtype:
		return None

	detail_doctype = frappe.db.get_value("WD Task Subtype", subtype, "detail_doctype")
	if not detail_doctype:
		return None

	name = frappe.db.get_value(detail_doctype, {"task": task}, "name")
	if not name:
		return None

	return {"doctype": detail_doctype, "name": name}

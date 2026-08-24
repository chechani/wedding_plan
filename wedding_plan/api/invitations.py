"""
Invitations & Manvaar module: the household x channel distribution matrix,
dashboard counts, and status updates (single + bulk).

Design notes:
  - A channel's Link value IS its channel_code (WD Invitation Channel
    autonames on that field), so the frontend's existing ChannelKey strings
    ("main", "ganesh", ...) work directly as Link values with no translation
    layer.
  - Not every household x channel pair has a WD Invitation Task row — most
    don't (most channels don't apply to most households). Missing pairs are
    presented as a virtual "Not Required" cell rather than pre-materializing
    every combination, matching how the UI already renders a dashed "NOT
    REQ" pill for the majority of cells. update_invitation_task lazily
    creates the row the first time a cell actually changes.
  - "Fully Invited" and the dashboard counts are both derived from the same
    _build_matrix() pass so the two can't drift apart.
"""
import frappe
from frappe import _

from wedding_plan.invitation_logic import is_task_complete

_STATUSES_FOR_BUCKET = {
	"acknowledged": {"Acknowledged"},
	"delivered_awaiting_ack": {"Delivered"},
	"planned_in_transit": {"Planned", "Sent"},
	"failed_redo": {"Failed"},
}


def _channel_list():
	return frappe.get_all(
		"WD Invitation Channel",
		filters={"enabled": 1},
		fields=["name as code", "channel_name", "short_label", "sort_order", "acknowledgement_required"],
		order_by="sort_order asc",
	)


def _build_matrix(wedding):
	"""Unfiltered household x channel grid for `wedding`. Internal — both
	get_invitation_matrix (which filters/searches on top) and
	invitation_dashboard_stats (which aggregates over it) call this so the
	two never disagree."""
	channels = _channel_list()
	channel_by_code = {c.code: c for c in channels}

	households = frappe.get_all(
		"WD Guest",
		filters={"wedding": wedding},
		fields=["name", "household_name", "city", "sub_group", "owner_in_family"],
		order_by="household_name asc",
	)

	city_labels = {}
	city_ids = {h.city for h in households if h.city}
	if city_ids:
		for row in frappe.get_all("WD City", filters={"name": ["in", list(city_ids)]}, fields=["name", "city"]):
			city_labels[row.name] = row.city

	sub_group_labels = {}
	sub_group_ids = {h.sub_group for h in households if h.sub_group}
	if sub_group_ids:
		for row in frappe.get_all(
			"WD Sub Group", filters={"name": ["in", list(sub_group_ids)]}, fields=["name", "sub_group_name"]
		):
			sub_group_labels[row.name] = row.sub_group_name

	household_names = [h.name for h in households]
	tasks_by_pair = {}
	if household_names:
		for t in frappe.get_all(
			"WD Invitation Task",
			filters={"wedding": wedding, "household": ["in", household_names]},
			fields=["name", "household", "channel", "status", "retry_required", "delivery_reference"],
		):
			tasks_by_pair[(t.household, t.channel)] = t

	rows = []
	for h in households:
		cells = {}
		any_applicable = False
		fully_invited = True
		for c in channels:
			task = tasks_by_pair.get((h.name, c.code))
			status = task.status if task else "Not Required"
			cells[c.code] = {
				"task": task.name if task else None,
				"status": status,
				"retry_required": bool(task.retry_required) if task else False,
				"delivery_reference": task.delivery_reference if task else None,
			}
			if status != "Not Required":
				any_applicable = True
				if not is_task_complete(status, c.acknowledgement_required):
					fully_invited = False

		rows.append(
			{
				"household": h.name,
				"household_name": h.household_name,
				"city": city_labels.get(h.city, h.city),
				"sub_group": h.sub_group,
				"sub_group_name": sub_group_labels.get(h.sub_group, h.sub_group),
				"owner": h.owner_in_family,
				"fully_invited": bool(any_applicable and fully_invited),
				"channels": cells,
			}
		)

	sub_groups = [{"name": k, "label": v} for k, v in sub_group_labels.items()]
	sub_groups.sort(key=lambda s: s["label"] or "")

	return channels, sub_groups, rows


@frappe.whitelist()
def get_invitation_channels(include_disabled=False):
	frappe.has_permission("WD Invitation Channel", "read", throw=True)
	filters = {} if frappe.parse_json(include_disabled) else {"enabled": 1}
	return frappe.get_all(
		"WD Invitation Channel",
		filters=filters,
		fields=[
			"name as code",
			"channel_name",
			"short_label",
			"sort_order",
			"enabled",
			"acknowledgement_required",
			"delivery_tracking_required",
			"description",
			"typical_owner",
			"redo_policy",
			"acknowledgement_expectation",
		],
		order_by="sort_order asc",
	)


@frappe.whitelist()
def get_invitation_matrix(wedding, search=None, sub_group=None, channel=None, status=None):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	channels, sub_groups, rows = _build_matrix(wedding)

	if sub_group:
		rows = [r for r in rows if r["sub_group"] == sub_group]

	if search:
		q = search.lower().strip()
		rows = [
			r
			for r in rows
			if q in (r["household_name"] or "").lower() or q in (r["city"] or "").lower()
		]

	if status:
		if channel:
			rows = [r for r in rows if r["channels"].get(channel, {}).get("status") == status]
		else:
			rows = [r for r in rows if any(c["status"] == status for c in r["channels"].values())]
	elif channel:
		rows = [r for r in rows if r["channels"].get(channel, {}).get("status") != "Not Required"]

	return {"channels": channels, "sub_groups": sub_groups, "households": rows}


@frappe.whitelist()
def invitation_dashboard_stats(wedding):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	_channels, _sub_groups, rows = _build_matrix(wedding)

	invitation_tasks = 0
	buckets = {k: 0 for k in _STATUSES_FOR_BUCKET}
	fully_invited = 0

	for r in rows:
		if r["fully_invited"]:
			fully_invited += 1
		for cell in r["channels"].values():
			if cell["status"] == "Not Required":
				continue
			invitation_tasks += 1
			for bucket, statuses in _STATUSES_FOR_BUCKET.items():
				if cell["status"] in statuses:
					buckets[bucket] += 1

	return {
		"households": len(rows),
		"invitation_tasks": invitation_tasks,
		"acknowledged": buckets["acknowledged"],
		"delivered_awaiting_ack": buckets["delivered_awaiting_ack"],
		"planned_in_transit": buckets["planned_in_transit"],
		"failed_redo": buckets["failed_redo"],
		"fully_invited": fully_invited,
	}


def _get_or_build_task(wedding, household, channel):
	if not frappe.db.exists("WD Invitation Channel", channel):
		frappe.throw(_("Unknown invitation channel: {0}").format(channel))
	if not frappe.db.exists("WD Guest", {"name": household, "wedding": wedding}):
		frappe.throw(_("Unknown household for this wedding: {0}").format(household))

	task_name = frappe.db.get_value(
		"WD Invitation Task", {"wedding": wedding, "household": household, "channel": channel}, "name"
	)
	if task_name:
		return frappe.get_doc("WD Invitation Task", task_name)
	return frappe.get_doc(
		{
			"doctype": "WD Invitation Task",
			"wedding": wedding,
			"household": household,
			"channel": channel,
			"status": "Not Required",
		}
	)


@frappe.whitelist()
def update_invitation_task(
	wedding,
	household,
	channel,
	status=None,
	notes=None,
	delivery_reference=None,
	failure_reason=None,
	delivery_mode=None,
	assigned_to=None,
):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	task = _get_or_build_task(wedding, household, channel)
	if status is not None:
		task.status = status
	if notes is not None:
		task.notes = notes
	if delivery_reference is not None:
		task.delivery_reference = delivery_reference
	if failure_reason is not None:
		task.failure_reason = failure_reason
	if delivery_mode is not None:
		task.delivery_mode = delivery_mode
	if assigned_to is not None:
		task.assigned_to = assigned_to

	task.save()
	return task.as_dict()


@frappe.whitelist()
def bulk_update_invitation_tasks(wedding, households, channel, status, notes=None):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	if isinstance(households, str):
		households = frappe.parse_json(households)

	results = []
	for household in households:
		try:
			task = update_invitation_task(wedding, household, channel, status=status, notes=notes)
			results.append({"household": household, "ok": True, "task": task.get("name"), "status": task.get("status")})
		except Exception as e:
			# validate() throws before any DB write for that doc, so nothing to
			# roll back here — a failure just means this one record's write
			# never happened. Rolling back the whole transaction would also
			# discard the successful records already saved earlier in this loop.
			frappe.local.message_log = []
			results.append({"household": household, "ok": False, "error": str(e)})

	return {
		"updated": len([r for r in results if r["ok"]]),
		"failed": len([r for r in results if not r["ok"]]),
		"results": results,
	}


@frappe.whitelist()
def ensure_invitation_tasks(wedding, household=None):
	"""Materialize 'Not Required' WD Invitation Task rows for every enabled
	channel x household pair that doesn't have one yet. Not required for the
	matrix API (which virtualizes missing pairs) — useful for pre-populating
	real rows before a bulk data import, or so the plain WD Invitation Task
	list view shows complete data for a household."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	channels = frappe.get_all("WD Invitation Channel", filters={"enabled": 1}, pluck="name")
	household_filters = {"wedding": wedding}
	if household:
		household_filters["name"] = household
	households = frappe.get_all("WD Guest", filters=household_filters, pluck="name")

	existing_pairs = set()
	if households:
		for e in frappe.get_all(
			"WD Invitation Task", filters={"wedding": wedding, "household": ["in", households]}, fields=["household", "channel"]
		):
			existing_pairs.add((e.household, e.channel))

	created = 0
	for h in households:
		for c in channels:
			if (h, c) in existing_pairs:
				continue
			frappe.get_doc(
				{
					"doctype": "WD Invitation Task",
					"wedding": wedding,
					"household": h,
					"channel": c,
					"status": "Not Required",
				}
			).insert()
			created += 1

	return {"created": created}

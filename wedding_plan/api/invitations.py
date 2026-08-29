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
from frappe.utils import date_diff, getdate, today

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
			doc = frappe.get_doc(
				{
					"doctype": "WD Invitation Task",
					"wedding": wedding,
					"household": h,
					"channel": c,
					"status": "Not Required",
				}
			)
			# Already confirmed against existing_pairs above — see the flag's
			# own comment on WDInvitationTask._check_duplicate for why this
			# skips a redundant per-row duplicate query.
			doc.flags.skip_duplicate_check = True
			doc.insert()
			created += 1

	return {"created": created}


def _log_attempt(wedding, household, channel, invitation_task, result, details, logged_by=None):
	"""WD Invitation Log is the append-only attempt history behind a task's
	current status — every status-changing action below writes one of these
	alongside updating the task, so 'what happened and when' is never lost
	to a later overwrite (matches this module's own 'nothing overwrites
	anything' design note, previously only honoured by the mock frontend)."""
	attempt_number = frappe.db.count("WD Invitation Log", {"wedding": wedding, "household": household, "channel": channel}) + 1
	frappe.get_doc(
		{
			"doctype": "WD Invitation Log",
			"wedding": wedding,
			"household": household,
			"channel": channel,
			"invitation_task": invitation_task,
			"attempt_number": attempt_number,
			"entry_date": today(),
			"result": result,
			"logged_by": logged_by or frappe.session.user,
			"details": details,
		}
	).insert()


@frappe.whitelist()
def get_pending_acknowledgements(wedding):
	"""Every WD Invitation Task sitting at Delivered — the Acknowledgement
	Inbox's actual data source, replacing the frontend's hardcoded sample
	dates/runners."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	tasks = frappe.get_all(
		"WD Invitation Task",
		filters={"wedding": wedding, "status": "Delivered"},
		fields=["name", "household", "channel", "delivered_date", "delivery_reference"],
	)
	if not tasks:
		return []

	household_ids = {t.household for t in tasks}
	households = {
		h.name: h
		for h in frappe.get_all(
			"WD Guest",
			filters={"name": ["in", list(household_ids)]},
			fields=["name", "household_name", "owner_in_family", "sub_group"],
		)
	}
	sub_group_ids = {h.sub_group for h in households.values() if h.sub_group}
	sub_group_labels = {}
	if sub_group_ids:
		for row in frappe.get_all("WD Sub Group", filters={"name": ["in", list(sub_group_ids)]}, fields=["name", "sub_group_name"]):
			sub_group_labels[row.name] = row.sub_group_name

	channel_ids = {t.channel for t in tasks}
	channel_names = {
		c.name: c.channel_name
		for c in frappe.get_all("WD Invitation Channel", filters={"name": ["in", list(channel_ids)]}, fields=["name", "channel_name"])
	}

	today_date = getdate()
	out = []
	for t in tasks:
		h = households.get(t.household)
		if not h:
			continue
		days_waiting = date_diff(today_date, t.delivered_date) if t.delivered_date else None
		out.append(
			{
				"task": t.name,
				"household": t.household,
				"household_name": h.household_name,
				"sub_group_name": sub_group_labels.get(h.sub_group),
				"owner": h.owner_in_family,
				"channel": t.channel,
				"channel_name": channel_names.get(t.channel, t.channel),
				"delivered_date": t.delivered_date,
				"delivered_by": t.delivery_reference,
				"days_waiting": days_waiting,
			}
		)
	out.sort(key=lambda r: r["days_waiting"] or 0, reverse=True)
	return out


@frappe.whitelist()
def confirm_acknowledgement(wedding, household, channel, method):
	frappe.has_permission("Wedding", doc=wedding, throw=True)
	task = update_invitation_task(wedding, household, channel, status="Acknowledged")
	_log_attempt(wedding, household, channel, task.get("name"), result="Success", details=f"Receipt acknowledged via {method}")
	return task


@frappe.whitelist()
def get_invitation_history(wedding, household):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	logs = frappe.get_all(
		"WD Invitation Log",
		filters={"wedding": wedding, "household": household},
		fields=["name", "channel", "entry_date", "result", "logged_by", "details", "creation"],
		order_by="entry_date desc, creation desc",
	)
	channel_ids = {r.channel for r in logs}
	channel_names = {
		c.name: c.channel_name
		for c in frappe.get_all("WD Invitation Channel", filters={"name": ["in", list(channel_ids)]}, fields=["name", "channel_name"])
	} if channel_ids else {}

	return [{**r, "channel_name": channel_names.get(r.channel, r.channel)} for r in logs]


@frappe.whitelist()
def add_invitation_log(
	wedding,
	household,
	channel,
	status=None,
	mode=None,
	assigned_to=None,
	planned_date=None,
	completed_date=None,
	received_by=None,
	accompanied_by=None,
	courier_awb=None,
	notes=None,
):
	"""Invitation history drawer's 'Add Entry' — updates the task's current
	status/dates and appends one attempt record describing what happened,
	same split as everywhere else in this module (current state vs. history)."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	# `mode` ("In person"/"Courier"/"Via relative"/...) is the drawer's own
	# free-form vocabulary for *this attempt* — WD Invitation Task.delivery_mode
	# is a Link to WD Patrika Delivery Mode (a household-level, mostly-unseeded
	# master list for the main card specifically) and isn't the same concept,
	# so `mode` stays narrative-only, folded into the log's `details` below
	# rather than written to that Link field.
	date_field = {"Delivered": "delivered_date", "Sent": "sent_date", "Planned": "planned_date", "Acknowledged": "acknowledged_date", "Failed": "failed_date"}.get(status)
	task = update_invitation_task(
		wedding,
		household,
		channel,
		status=status,
		delivery_reference=received_by or courier_awb,
		assigned_to=assigned_to,
		notes=notes,
	)
	if date_field and completed_date:
		frappe.db.set_value("WD Invitation Task", task.get("name"), date_field, completed_date)

	details = f"{mode or 'Update'} — {status or 'logged'}"
	if received_by:
		details += f" (Received by {received_by})"
	if accompanied_by and accompanied_by != "Nothing":
		details += f", with {accompanied_by}"
	if courier_awb:
		details += f", AWB: {courier_awb}"
	if notes:
		details += f". Note: {notes}"

	result = "Success" if status in ("Delivered", "Acknowledged") else "Issue" if status == "Failed" else "Pending"
	_log_attempt(wedding, household, channel, task.get("name"), result=result, details=details, logged_by=assigned_to)

	return task


@frappe.whitelist()
def record_doorstep_delivery(wedding, household, outcome, received_by=None, note=None):
	"""Mobile field-capture screen — always the 'main' patrika channel, one
	tap per doorstep. Status mapping mirrors the frontend's own outcome
	classification (kept in sync deliberately rather than trusting a raw
	status string from the client)."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	# Exact match against the frontend's fixed outcome buttons (see
	# FieldCaptureMobile.tsx) rather than substring checks — a prior version
	# checked "✓"/"family member" before "Wrong", so an outcome combining
	# both (e.g. a future "Wrong address — left with family member" option)
	# would have silently classified as Delivered instead of Failed.
	OUTCOME_STATUS = {
		"Met in person ✓": "Delivered",
		"Given to family member": "Delivered",
		"Nobody home": "Sent",
		"Wrong address": "Failed",
	}
	is_wrong_address = outcome == "Wrong address"
	status = OUTCOME_STATUS.get(outcome, "Sent")

	task = update_invitation_task(
		wedding,
		household,
		"main",
		status=status,
		delivery_reference=received_by,
		failure_reason=outcome if is_wrong_address else None,
	)
	if status == "Delivered":
		frappe.db.set_value("WD Invitation Task", task.get("name"), "delivered_date", today())

	details = f"Doorstep: {outcome}"
	if received_by:
		details += f" (Recipient: {received_by})"
	if note:
		details += f" — {note}"
	result = "Success" if is_success else "Issue" if is_wrong_address else "Pending"
	_log_attempt(wedding, household, "main", task.get("name"), result=result, details=details)

	return task


@frappe.whitelist()
def list_delivery_runs(wedding):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	runs = frappe.get_all(
		"WD Delivery Run",
		filters={"wedding": wedding},
		fields=["name", "area_name", "assigned_to", "run_date", "items_description"],
		order_by="run_date asc, creation asc",
	)
	if not runs:
		return []

	run_names = [r.name for r in runs]
	rows = frappe.get_all(
		"WD Delivery Run Household",
		filters={"parent": ["in", run_names]},
		fields=["name", "parent", "household", "delivered"],
		order_by="idx asc",
	)
	household_ids = {r.household for r in rows}
	household_names = {
		h.name: h.household_name
		for h in frappe.get_all("WD Guest", filters={"name": ["in", list(household_ids)]}, fields=["name", "household_name"])
	} if household_ids else {}

	rows_by_run = {}
	for r in rows:
		rows_by_run.setdefault(r.parent, []).append(
			{"name": r.name, "household": r.household, "household_name": household_names.get(r.household, r.household), "delivered": bool(r.delivered)}
		)

	return [{**run, "households": rows_by_run.get(run.name, [])} for run in runs]


@frappe.whitelist()
def create_delivery_run(wedding, area_name, assigned_to, run_date=None, items_description=None, households=None):
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	if isinstance(households, str):
		households = frappe.parse_json(households)
	households = households or []

	run = frappe.get_doc(
		{
			"doctype": "WD Delivery Run",
			"wedding": wedding,
			"area_name": area_name,
			"assigned_to": assigned_to,
			"run_date": run_date,
			"items_description": items_description,
			"households": [{"household": h} for h in households],
		}
	).insert()
	return run.as_dict()


@frappe.whitelist()
def toggle_delivery_run_item(wedding, run, household, delivered):
	"""Ticking a household in a run also marks the household delivered on
	the main patrika channel — same cross-effect the mock UI's own comment
	promised ('Ticking a household here writes a Delivered entry to its
	log') but never actually implemented."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)
	delivered = frappe.parse_json(delivered) if isinstance(delivered, str) else bool(delivered)

	run_doc = frappe.get_doc("WD Delivery Run", run)
	if run_doc.wedding != wedding:
		frappe.throw(_("This run does not belong to this wedding."))

	row = next((h for h in run_doc.households if h.household == household), None)
	if not row:
		frappe.throw(_("{0} is not part of this run.").format(household))
	row.delivered = 1 if delivered else 0
	run_doc.save()

	if delivered:
		task = update_invitation_task(wedding, household, "main", status="Delivered", delivery_reference=f"Delivery run: {run_doc.area_name}")
		frappe.db.set_value("WD Invitation Task", task.get("name"), "delivered_date", today())
		_log_attempt(wedding, household, "main", task.get("name"), result="Success", details=f"Delivered on run ({run_doc.area_name}, {run_doc.assigned_to})")

	return {"ok": True}

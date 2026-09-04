"""
Transport execution: arrival/departure clustering, the vehicle occupancy
ledger, and allocation suggestions.

Design notes, mirroring api/tasks.py's split:
  - Plain REST (/api/resource/WD Transport Movement,
    /api/resource/WD Vehicle Assignment) covers ordinary CRUD.
  - These bespoke methods are for the cross-doctype work a form can't do:
    matching guests who share a flight before any movement exists, the
    vehicle-availability query against the WD Vehicle Assignment ledger, and
    the two operations (merge/split) that reassign several records at once.
  - Every write here checks `frappe.has_permission("Wedding", ...)` for
    membership only, then performs the actual mutation via normal
    `.insert()`/`.save()` (never `ignore_permissions=True`) — the specific
    "does this user's Wedding Member role allow writing this doctype" check
    is already enforced by permissions.py's per-doctype hooks, so it isn't
    duplicated here. Matches api/tasks.py's bulk_update_task_status.
"""
import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate

from wedding_plan.wedding_plan.doctype.wd_vehicle_assignment.wd_vehicle_assignment import DEFAULT_TURNAROUND_MINUTES


def _as_list(value):
	if isinstance(value, str):
		return frappe.parse_json(value)
	return value or []


def _as_dict(value):
	if isinstance(value, str):
		return frappe.parse_json(value) if value else {}
	return value or {}


@frappe.whitelist()
def suggest_movement_clusters(wedding, date):
	"""Groups households sharing a flight/train on `date` that aren't yet on
	a WD Transport Movement, so a coordinator can create one movement for
	all of them in one action instead of one at a time. Never creates
	anything itself — see create_movement_from_cluster for that."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	guests = frappe.get_all(
		"WD Guest",
		filters={
			"wedding": wedding,
			"pickup_required": 1,
			"arrival_mode": ["in", ["Air", "Train"]],
			"flight_train_number": ["is", "set"],
			"arrival_datetime": ["is", "set"],
		},
		fields=["name", "household_name", "arrival_mode", "flight_train_number", "arrival_datetime", "pax", "pickup_point"],
	)
	target_date = getdate(date)
	guests = [g for g in guests if getdate(g.arrival_datetime) == target_date]
	if not guests:
		return []

	already_clustered = set(
		frappe.get_all(
			"WD Pickup",
			filters={"wedding": wedding, "movement": ["is", "set"]},
			pluck="guest",
		)
	)
	guests = [g for g in guests if g.name not in already_clustered]

	groups = {}
	for g in guests:
		groups.setdefault((g.arrival_mode, g.flight_train_number), []).append(g)

	clusters = [
		{
			"mode": mode,
			"flight_train_number": flight_train_number,
			"eta_planned": min(m.arrival_datetime for m in members),
			"suggested_pax": sum(m.pax or 0 for m in members),
			"guests": [
				{"guest": m.name, "household_name": m.household_name, "pax": m.pax, "pickup_point": m.pickup_point}
				for m in members
			],
		}
		for (mode, flight_train_number), members in groups.items()
	]
	clusters.sort(key=lambda c: -len(c["guests"]))
	return clusters


@frappe.whitelist()
def create_movement_from_cluster(wedding, guest_names, movement_fields=None):
	"""Accepts a cluster suggestion (or a hand-picked list of households):
	creates one WD Transport Movement, then creates or updates each
	household's WD Pickup row to point at it."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	guest_names = _as_list(guest_names)
	if not guest_names:
		frappe.throw(_("Select at least one household."))
	fields = _as_dict(movement_fields)

	movement = frappe.get_doc(
		{
			"doctype": "WD Transport Movement",
			"wedding": wedding,
			"movement_type": fields.get("movement_type") or "Arrival Pickup",
			**{k: v for k, v in fields.items() if k not in ("wedding", "movement_type")},
		}
	)
	movement.insert()

	for guest in guest_names:
		guest_doc = frappe.db.get_value("WD Guest", guest, ["wedding", "pax", "pickup_point", "arrival_mode"], as_dict=True)
		if not guest_doc or guest_doc.wedding != wedding:
			continue
		pickup_name = frappe.db.get_value("WD Pickup", {"wedding": wedding, "guest": guest, "movement": ["is", "not set"]})
		if pickup_name:
			pickup = frappe.get_doc("WD Pickup", pickup_name)
			pickup.movement = movement.name
			pickup.save()
		else:
			frappe.get_doc(
				{
					"doctype": "WD Pickup",
					"wedding": wedding,
					"guest": guest,
					"movement": movement.name,
					"direction": "Pickup" if movement.movement_type == "Arrival Pickup" else "Drop",
					"mode": guest_doc.arrival_mode,
					"pax_count": guest_doc.pax,
					"point": guest_doc.pickup_point,
				}
			).insert()

	return {"movement": movement.name}


@frappe.whitelist()
def merge_movements(movement_a, movement_b):
	"""Folds movement_b's pickups and vehicle assignments onto movement_a,
	then cancels movement_b. Warns (in the response, not by refusing) if the
	two movements' flight/train numbers differ — merging different flights
	may be intentional (re-timed to arrive together) so it isn't blocked."""
	a = frappe.get_doc("WD Transport Movement", movement_a)
	b = frappe.get_doc("WD Transport Movement", movement_b)
	frappe.has_permission("Wedding", doc=a.wedding, throw=True)
	if b.wedding != a.wedding:
		frappe.throw(_("Both movements must belong to the same wedding."))

	warning = None
	if a.flight_train_number and b.flight_train_number and a.flight_train_number != b.flight_train_number:
		warning = _("Flight/train numbers differ ({0} vs {1}) — confirm this merge was intentional.").format(
			a.flight_train_number, b.flight_train_number
		)

	for pickup_name in frappe.get_all("WD Pickup", filters={"movement": b.name}, pluck="name"):
		pickup = frappe.get_doc("WD Pickup", pickup_name)
		pickup.movement = a.name
		pickup.save()

	for assignment_name in frappe.get_all("WD Vehicle Assignment", filters={"against_type": "Transport Movement", "against_movement": b.name}, pluck="name"):
		assignment = frappe.get_doc("WD Vehicle Assignment", assignment_name)
		assignment.against_movement = a.name
		assignment.save()

	b.status = "Cancelled"
	b.save()

	return {"merged_into": a.name, "warning": warning}


@frappe.whitelist()
def split_movement(movement, pickup_names):
	"""Peels the selected pickups (and their vehicle assignments) off
	`movement` into a new movement, copying the original's descriptive
	fields but resetting status/actuals — the new movement starts Planned."""
	source = frappe.get_doc("WD Transport Movement", movement)
	frappe.has_permission("Wedding", doc=source.wedding, throw=True)

	pickup_names = _as_list(pickup_names)
	if not pickup_names:
		frappe.throw(_("Select at least one pickup to split off."))

	new_movement = frappe.get_doc(
		{
			"doctype": "WD Transport Movement",
			"wedding": source.wedding,
			"movement_type": source.movement_type,
			"mode": source.mode,
			"flight_train_number": source.flight_train_number,
			"pnr": source.pnr,
			"terminal_or_platform": source.terminal_or_platform,
			"coach_seat": source.coach_seat,
			"origin": source.origin,
			"destination": source.destination,
			"eta_planned": source.eta_planned,
			"coordinator": source.coordinator,
		}
	)
	new_movement.insert()

	for pickup_name in pickup_names:
		pickup = frappe.get_doc("WD Pickup", pickup_name)
		if pickup.movement != source.name:
			continue
		pickup.movement = new_movement.name
		pickup.save()

		for assignment_name in frappe.get_all(
			"WD Vehicle Assignment",
			filters={"against_type": "Transport Movement", "against_movement": source.name, "against_pickup": pickup_name},
			pluck="name",
		):
			assignment = frappe.get_doc("WD Vehicle Assignment", assignment_name)
			assignment.against_movement = new_movement.name
			assignment.save()

	return {"new_movement": new_movement.name}


def _busy_vehicle_names(wedding, window_start, window_end):
	"""Vehicle names committed (any non-final WD Vehicle Assignment) with an
	overlapping [dispatch_at, expected_release_at] window — the same
	occupancy query the doctype's own validate() uses for its warning,
	factored out here so the suggestion endpoint and the conflict warning
	can't drift apart."""
	if not (window_start and window_end):
		return set()
	start, end = get_datetime(window_start), get_datetime(window_end)
	rows = frappe.get_all(
		"WD Vehicle Assignment",
		filters={"wedding": wedding, "status": ["not in", ["Completed", "Released", "Cancelled"]]},
		fields=["vehicle", "dispatch_at", "expected_release_at"],
	)
	busy = set()
	for r in rows:
		if not (r.dispatch_at and r.expected_release_at):
			continue
		if get_datetime(r.dispatch_at) < end and get_datetime(r.expected_release_at) > start:
			busy.add(r.vehicle)
	return busy


@frappe.whitelist()
def suggest_vehicles(wedding, window_start, window_end, pax_count=0, luggage_count=0, needs_vip=False):
	"""Rule-based, override-first (§8 of the implementation plan): filters
	vehicles free in the window per the WD Vehicle Assignment ledger,
	prioritizes vip_suitable ones when needed, then greedily fills by
	capacity. Returns a suggestion only — never creates an assignment."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	pax_count = int(pax_count or 0)
	needs_vip = frappe.parse_json(needs_vip) if isinstance(needs_vip, str) else bool(needs_vip)

	vehicles = frappe.get_all(
		"WD Vehicle",
		filters={"wedding": wedding},
		fields=["name", "vehicle_number", "vehicle_type", "capacity", "vip_suitable", "driver_name", "driver_phone"],
	)
	busy = _busy_vehicle_names(wedding, window_start, window_end)
	candidates = [v for v in vehicles if v.name not in busy and (v.capacity or 0) > 0]
	candidates.sort(key=lambda v: (needs_vip and not v.vip_suitable, -(v.capacity or 0)))

	remaining = pax_count
	suggestion = []
	for v in candidates:
		if remaining <= 0:
			break
		suggestion.append(
			{
				"vehicle": v.name,
				"vehicle_number": v.vehicle_number,
				"vehicle_type": v.vehicle_type,
				"capacity": v.capacity,
				"vip_suitable": v.vip_suitable,
				"driver_name": v.driver_name,
				"driver_phone": v.driver_phone,
				"expected_release_at": add_to_date(get_datetime(window_start), minutes=DEFAULT_TURNAROUND_MINUTES) if window_start else None,
			}
		)
		remaining -= v.capacity or 0

	return {"suggested": suggestion, "unmet_pax": max(remaining, 0)}


@frappe.whitelist()
def movement_board(wedding, date):
	"""Day board data for arrival/departure clusters: every movement whose
	eta falls on `date`, with its pickups and vehicle assignments rolled
	up — backs the movement cards on /live and the movement grid in
	/w/execute."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	movements = frappe.get_all(
		"WD Transport Movement",
		filters={"wedding": wedding},
		fields=[
			"name", "movement_type", "mode", "flight_train_number", "pnr", "terminal_or_platform",
			"origin", "destination", "eta_planned", "eta_current", "status", "coordinator", "notes",
		],
	)
	target_date = getdate(date)
	# Cancelled movements (a manual cancel, or emptied out by a merge) have
	# nothing operationally useful to show on a live board.
	movements = [m for m in movements if m.status != "Cancelled" and m.eta_current and getdate(m.eta_current) == target_date]
	if not movements:
		return []

	names = [m.name for m in movements]
	pickups = frappe.get_all(
		"WD Pickup",
		filters={"movement": ["in", names]},
		fields=["name", "movement", "guest", "pax_count", "status", "vehicle", "greeter_name"],
	)
	assignments = frappe.get_all(
		"WD Vehicle Assignment",
		filters={"against_type": "Transport Movement", "against_movement": ["in", names]},
		fields=["name", "against_movement", "vehicle", "driver_name", "driver_phone", "status",
				"dispatch_at", "expected_release_at", "assigned_pax"],
	)
	household_names = {
		row.name: row.household_name
		for row in frappe.get_all("WD Guest", filters={"name": ["in", [p.guest for p in pickups if p.guest]]}, fields=["name", "household_name"])
	}

	pickups_by_movement, assignments_by_movement = {}, {}
	for p in pickups:
		# frappe._dict, not a plain dict, so callers can keep using attribute
		# access (p.pax_count) on the enriched rows — {**p, ...} alone would
		# silently downgrade to a plain dict and break that.
		pickups_by_movement.setdefault(p.movement, []).append(frappe._dict({**p, "household_name": household_names.get(p.guest)}))
	for a in assignments:
		assignments_by_movement.setdefault(a.against_movement, []).append(a)

	return [
		{
			**m,
			"pickups": pickups_by_movement.get(m.name, []),
			"vehicle_assignments": assignments_by_movement.get(m.name, []),
			# A cancelled household still shows in the roster (so a coordinator
			# can see it was pulled out), but no longer needs a seat — counting
			# it here would overstate how many vehicles the cluster still needs.
			"total_pax": sum(
				p.pax_count or 0
				for p in pickups_by_movement.get(m.name, [])
				if p.status != "Cancelled"
			),
		}
		for m in movements
	]

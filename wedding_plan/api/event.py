"""
Event Mode's Control Tower surfaces: the Attention feed (§11/§16 of the
implementation plan) and a per-guest/movement readiness check (§9), both
computed aggregations over existing records — no stored readiness/attention
doctype, matching how lib/event/dayBoard.ts's buildDay() already works on
the frontend.
"""
import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

LOOKAHEAD_DEFAULT_MINUTES = 60


@frappe.whitelist()
def arrival_readiness(guest):
	"""Consolidated readiness for one guest's arrival: is a vehicle
	dispatched, is a room allocated, are keys/hamper/luggage ready — plus how
	many minutes until they're expected, so the caller can decide whether
	this is urgent yet."""
	guest_doc = frappe.db.get_value("WD Guest", guest, ["wedding", "household_name"], as_dict=True)
	if not guest_doc:
		frappe.throw(_("Guest {0} not found").format(guest), frappe.DoesNotExistError)
	frappe.has_permission("Wedding", doc=guest_doc.wedding, throw=True)

	pickups = frappe.get_all(
		"WD Pickup",
		filters={"wedding": guest_doc.wedding, "guest": guest, "direction": "Pickup"},
		fields=["name", "status", "eta", "movement", "vehicle"],
		order_by="creation desc",
		limit=1,
	)
	pickup = pickups[0] if pickups else None

	eta = pickup.eta if pickup else None
	transport_ready = bool(pickup and pickup.vehicle)
	if pickup and pickup.movement:
		mv = frappe.db.get_value("WD Transport Movement", pickup.movement, ["eta_current"], as_dict=True)
		if mv and mv.eta_current:
			eta = mv.eta_current
		transport_ready = bool(
			frappe.db.exists(
				"WD Vehicle Assignment",
				{"against_type": "Transport Movement", "against_movement": pickup.movement, "status": ["in", ["Assigned", "Dispatched"]]},
			)
		)

	allotments = frappe.get_all(
		"WD Room Allotment",
		filters={"wedding": guest_doc.wedding, "guest": guest},
		fields=["name", "allotment_status", "keys_handed", "hamper_placed", "luggage_delivered"],
		limit=1,
	)
	allotment = allotments[0] if allotments else None

	minutes_to_eta = None
	if eta:
		minutes_to_eta = int((get_datetime(eta) - now_datetime()).total_seconds() // 60)

	return {
		"guest": guest,
		"household_name": guest_doc.household_name,
		"pickup_status": pickup.status if pickup else None,
		"transport_ready": transport_ready,
		"room_allocated": bool(allotment),
		"keys_ready": bool(allotment and allotment.keys_handed),
		"hamper_luggage_ready": bool(allotment and allotment.hamper_placed and allotment.luggage_delivered),
		"eta": eta,
		"minutes_to_eta": minutes_to_eta,
	}


@frappe.whitelist()
def attention_items(wedding, date, lookahead_minutes=None):
	"""What needs action, right now or soon, for `date`:
	  - delayed: Transport Movements running later than eta_planned
	  - unassigned: Transport Movements with no vehicle assignment yet
	  - rooms_not_ready_soon: arrivals inside the lookahead window whose room
	    keys aren't confirmed yet (point 6 — proactive, before drop-off)
	  - rooms_not_ready_now: arrivals already Dropped whose keys still aren't
	    confirmed (the reactive, more urgent tier)
	  - menu_blocked: WD Menu Items marked Blocked
	  - open_issues: WD Event Issues not yet Resolved
	Convoy Legs are deliberately excluded from automatic delay-detection:
	their only "planned" time fields (must_arrive/depart_by) are free-text
	Data, not a real Datetime, so no reliable delta can be computed from
	them — surfacing a false delay would be worse than surfacing none."""
	frappe.has_permission("Wedding", doc=wedding, throw=True)

	lookahead = int(lookahead_minutes or LOOKAHEAD_DEFAULT_MINUTES)
	target_date = getdate(date)
	now = now_datetime()
	horizon = add_to_date(now, minutes=lookahead)

	movements = frappe.get_all(
		"WD Transport Movement",
		filters={"wedding": wedding},
		fields=["name", "movement_type", "flight_train_number", "eta_planned", "eta_current", "status"],
	)
	today_movements = [m for m in movements if m.eta_current and getdate(m.eta_current) == target_date]

	delayed = [
		m
		for m in today_movements
		if m.status == "Delayed" or (m.eta_planned and get_datetime(m.eta_current) > get_datetime(m.eta_planned))
	]

	unassigned = [
		m
		for m in today_movements
		if m.status not in ("Completed", "Cancelled")
		and not frappe.db.exists("WD Vehicle Assignment", {"against_type": "Transport Movement", "against_movement": m.name})
	]

	pickups = frappe.get_all(
		"WD Pickup",
		filters={"wedding": wedding, "direction": "Pickup"},
		fields=["name", "guest", "eta", "movement", "status"],
	)
	guest_names = list({p.guest for p in pickups if p.guest})
	allotments_by_guest = {}
	household_names = {}
	if guest_names:
		allotments_by_guest = {
			a.guest: a
			for a in frappe.get_all(
				"WD Room Allotment", filters={"wedding": wedding, "guest": ["in", guest_names]}, fields=["guest", "keys_handed"]
			)
		}
		household_names = {g.name: g.household_name for g in frappe.get_all("WD Guest", filters={"name": ["in", guest_names]}, fields=["name", "household_name"])}
	movement_eta = {m.name: m.eta_current for m in movements}

	rooms_not_ready_soon, rooms_not_ready_now = [], []
	for p in pickups:
		eta = movement_eta.get(p.movement) if p.movement else p.eta
		if not eta:
			continue
		allotment = allotments_by_guest.get(p.guest)
		if allotment and allotment.keys_handed:
			continue
		entry = {"guest": p.guest, "household_name": household_names.get(p.guest), "eta": eta, "pickup": p.name}
		if p.status == "Dropped":
			rooms_not_ready_now.append(entry)
		elif now <= get_datetime(eta) <= horizon:
			rooms_not_ready_soon.append(entry)

	menu_names = frappe.get_all("WD Menu", filters={"wedding": wedding}, pluck="name")
	menu_blocked = (
		frappe.get_all("WD Menu Item", filters={"parent": ["in", menu_names], "status": "Blocked"}, fields=["name", "item_name", "category", "parent"])
		if menu_names
		else []
	)

	open_issues = frappe.get_all(
		"WD Event Issue",
		filters={"wedding": wedding, "status": ["!=", "Resolved"]},
		fields=["name", "title", "severity", "status", "related_type"],
		order_by="creation desc",
	)

	return {
		"delayed": delayed,
		"unassigned": unassigned,
		"rooms_not_ready_soon": rooms_not_ready_soon,
		"rooms_not_ready_now": rooms_not_ready_now,
		"menu_blocked": menu_blocked,
		"open_issues": open_issues,
	}

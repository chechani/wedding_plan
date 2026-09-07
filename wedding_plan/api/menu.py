"""
Menu execution: plain REST (/api/resource/WD Menu, /api/resource/WD Menu
Item as its child table) covers ordinary CRUD. This one bespoke method backs
the category-level "Mark all Starters Ready" bulk action — the whole point
of which is not clicking each item individually.
"""
import frappe
from frappe.utils import get_time_str


@frappe.whitelist()
def bulk_set_category_status(menu, category, status):
	"""Sets `status` on every item in `menu` belonging to `category`. Saves
	the parent (not ignore_permissions) so WD Menu's normal role gate
	(Catering Liaison/Venue Commander) applies exactly as it would to any
	other edit of this document."""
	doc = frappe.get_doc("WD Menu", menu)
	frappe.has_permission("Wedding", doc=doc.wedding, throw=True)

	updated = 0
	for item in doc.items:
		if item.category == category:
			item.status = status
			updated += 1

	doc.save()
	return {"updated": updated}


# Ownership types on WD Vehicle that count as the household's own arrangement
# rather than something hired for the event — drives the private/hired driver
# split in calculate_meal_session_plate_count.
_PRIVATE_OWNERSHIP_TYPES = {"Family-owned", "Friend/Relative"}


@frappe.whitelist()
def calculate_meal_session_plate_count(meal_session):
	"""Plate count breakdown for one WD Meal Session: confirmed/attended
	guests of its linked Function (Jain/fasting resolved with a fallback
	through the guest's and household's own dietary defaults, plus the
	earliest serve-before cutoff any of them carries), the caterer's own
	staff, drivers on duty that date (from WD Convoy Leg, split private vs.
	hired by WD Vehicle.ownership_type), and everyone on WD Team. Returns the
	breakdown, not just a total, so the UI can show its work — and persists
	the total on `calculated_plates` so it survives without reopening this
	panel."""
	session = frappe.get_doc("WD Meal Session", meal_session)
	frappe.has_permission("Wedding", doc=session.wedding, throw=True)

	# Guests: each WD Guest Member Function row is one person invited to the
	# session's function; Confirmed/Attended is "expected to actually eat" —
	# Invited alone isn't (nothing said they're coming), Declined/No Show
	# have already said or shown they won't.
	guests = jain_guests = kid_guests = fasting_guests = 0
	guests_note = None
	earliest_serve_before = None
	if session.function:
		member_functions = frappe.get_all(
			"WD Guest Member Function",
			filters={"function": session.function, "status": ["in", ["Confirmed", "Attended"]]},
			fields=["guest_member", "household", "meal_preference", "is_fasting", "serve_before"],
		)
		guests = len(member_functions)

		# Effective diet per row: this Function's own meal_preference, else the
		# guest's usual diet (WD Guest Member.dietary), else the household
		# default (WD Guest.dietary), else Standard. A guest's dietary identity
		# is normally set once at intake, not re-typed per Function — without
		# this fallback, jain_guests only ever sees the rare per-Function
		# override and undercounts almost everyone who is actually Jain.
		blank_rows = [r for r in member_functions if not r.meal_preference]
		member_dietary = {}
		if blank_rows:
			member_names_blank = [r.guest_member for r in blank_rows if r.guest_member]
			member_dietary = {
				row.name: row.dietary
				for row in frappe.get_all(
					"WD Guest Member", filters={"name": ["in", member_names_blank]}, fields=["name", "dietary"]
				)
			}
		household_dietary = {}
		still_blank_households = [
			r.household for r in blank_rows if r.household and not member_dietary.get(r.guest_member)
		]
		if still_blank_households:
			household_dietary = {
				row.name: row.dietary
				for row in frappe.get_all(
					"WD Guest", filters={"name": ["in", still_blank_households]}, fields=["name", "dietary"]
				)
			}

		serve_before_candidates = []
		for r in member_functions:
			diet = r.meal_preference or member_dietary.get(r.guest_member) or household_dietary.get(r.household) or "Standard"
			is_jain = diet == "Jain"
			if is_jain:
				jain_guests += 1
			if r.is_fasting:
				fasting_guests += 1
			# Only Jain/fasting guests carry a real dietary reason to need an
			# early cutoff — a Standard guest's serve_before (if ever set)
			# shouldn't drag the whole session's deadline earlier.
			if r.serve_before and (is_jain or r.is_fasting):
				serve_before_candidates.append(r.serve_before)
		if serve_before_candidates:
			earliest_serve_before = get_time_str(min(serve_before_candidates))

		member_names = [r.guest_member for r in member_functions if r.guest_member]
		if member_names:
			age_groups = frappe.get_all(
				"WD Guest Member", filters={"name": ["in", member_names]}, fields=["age_group"]
			)
			kid_guests = sum(1 for r in age_groups if r.age_group in ("Child", "Infant"))
	else:
		guests_note = "Link a Function to calculate guests"

	# Catering staff: set once on the caterer's own WD Vendor record, reused
	# automatically by every session that vendor serves — see WD Vendor.staff_count.
	catering_staff = 0
	if session.vendor:
		catering_staff = frappe.db.get_value("WD Vendor", session.vendor, "staff_count") or 0

	# Drivers: vehicles actually committed to move people on this date, via
	# WD Convoy Leg (it carries its own `date`, unlike WD Vehicle Assignment
	# which only has one through the movement/leg it's against). One vehicle,
	# one driver — deduplicated so a vehicle running three legs that day
	# doesn't count its driver three times.
	drivers_private = drivers_hired = 0
	if session.date:
		leg_vehicles = frappe.get_all(
			"WD Convoy Leg",
			filters={"wedding": session.wedding, "date": session.date, "vehicle": ["is", "set"]},
			pluck="vehicle",
		)
		vehicle_names = list(set(leg_vehicles))
		if vehicle_names:
			ownership_types = frappe.get_all(
				"WD Vehicle", filters={"name": ["in", vehicle_names]}, fields=["ownership_type"]
			)
			for row in ownership_types:
				if row.ownership_type in _PRIVATE_OWNERSHIP_TYPES:
					drivers_private += 1
				else:
					drivers_hired += 1

	# Other teams: WD Team is a fixed 1-2 person roster per team code (decor,
	# sound, photography...), not itself dated — every team on the wedding is
	# counted, since there's nothing on the doctype saying which sessions a
	# given team is actually present for.
	other_team = 0
	for row in frappe.get_all(
		"WD Team", filters={"wedding": session.wedding}, fields=["member_a_name", "member_b_name"]
	):
		other_team += (1 if row.member_a_name else 0) + (1 if row.member_b_name else 0)

	calculated_total = guests + catering_staff + drivers_private + drivers_hired + other_team
	frappe.db.set_value("WD Meal Session", meal_session, "calculated_plates", calculated_total)

	return {
		"guests": guests,
		"jain_guests": jain_guests,
		"kid_guests": kid_guests,
		"fasting_guests": fasting_guests,
		"earliest_serve_before": earliest_serve_before,
		"guests_note": guests_note,
		"catering_staff": catering_staff,
		"drivers_private": drivers_private,
		"drivers_hired": drivers_hired,
		"other_team": other_team,
		"calculated_total": calculated_total,
	}

# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, get_datetime

from wedding_plan.task_logic import enforce_polymorphic_assignment

# Default trip duration + turnaround assumed when suggesting expected_release_at
# from dispatch_at. A first-version constant, not a maps/distance-API lookup —
# editable per row once a coordinator knows a specific trip runs long.
DEFAULT_TURNAROUND_MINUTES = 90

_AGAINST_FIELD_BY_TYPE = {
	"Pickup": "against_pickup",
	"Transport Movement": "against_movement",
	"Convoy Leg": "against_leg",
}

# Statuses that mean the vehicle is no longer committed by this row.
_INACTIVE_STATUSES = {"Completed", "Released", "Cancelled"}


class WDVehicleAssignment(Document):
	def validate(self):
		enforce_polymorphic_assignment(self, self.against_type, _AGAINST_FIELD_BY_TYPE, _("this vehicle assignment"))
		self._default_driver_from_vehicle()
		self._suggest_expected_release()
		self._warn_on_overlap()

	def _default_driver_from_vehicle(self):
		"""Pre-fill from the vehicle's usual driver, once, when neither is set
		yet — never overwrites a value already entered for this specific trip."""
		if self.driver_name or self.driver_phone or not self.vehicle:
			return
		vehicle = frappe.db.get_value("WD Vehicle", self.vehicle, ["driver_name", "driver_phone"], as_dict=True)
		if vehicle:
			self.driver_name = vehicle.driver_name
			self.driver_phone = vehicle.driver_phone

	def _suggest_expected_release(self):
		"""dispatch_at + a turnaround buffer, only as a starting suggestion —
		never overwrites a value a coordinator has already set or edited."""
		if self.dispatch_at and not self.expected_release_at:
			self.expected_release_at = add_to_date(self.dispatch_at, minutes=DEFAULT_TURNAROUND_MINUTES)

	def _warn_on_overlap(self):
		"""Non-blocking: tells a coordinator the vehicle is already committed
		elsewhere in this window, but never refuses the save — matches the
		app's existing pattern of warnings, not blocks, for double-booking."""
		if not (self.vehicle and self.dispatch_at and self.expected_release_at):
			return

		candidates = frappe.get_all(
			"WD Vehicle Assignment",
			filters={
				"vehicle": self.vehicle,
				"name": ["!=", self.name or ""],
				"status": ["not in", list(_INACTIVE_STATUSES)],
			},
			fields=["name", "dispatch_at", "expected_release_at", "against_type"],
		)
		# self.dispatch_at/expected_release_at may still be plain strings at
		# this point in validate() (set from a dict, not yet cast), while
		# frappe.get_all() already returns real datetime objects for `other` —
		# comparing the two raw would raise TypeError. Coerce both sides.
		self_start = get_datetime(self.dispatch_at)
		self_end = get_datetime(self.expected_release_at)
		for other in candidates:
			if not (other.dispatch_at and other.expected_release_at):
				continue
			other_start = get_datetime(other.dispatch_at)
			other_end = get_datetime(other.expected_release_at)
			overlaps = other_start < self_end and other_end > self_start
			if overlaps:
				frappe.msgprint(
					_("This vehicle is already assigned to another {0} ({1}) in an overlapping window.").format(
						other.against_type, other.name
					),
					indicator="orange",
					alert=True,
				)
				break

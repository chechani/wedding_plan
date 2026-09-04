# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# related_type is optional ("Other"/blank is a valid choice with no linked
# field), so this doesn't reuse task_logic.enforce_polymorphic_assignment —
# that helper always requires a field once a type is chosen, which "Other"
# deliberately doesn't have.
_RELATED_FIELD_BY_TYPE = {
	"Pickup": "related_pickup",
	"Transport Movement": "related_movement",
	"Convoy Leg": "related_leg",
	"Room Allotment": "related_room_allotment",
	"Menu": "related_menu",
	"Function": "related_function",
	"Vehicle": "related_vehicle",
}


class WDEventIssue(Document):
	def validate(self):
		self._clear_unused_related_fields()
		self._require_resolution_when_resolved()

	def _clear_unused_related_fields(self):
		for other_type, field in _RELATED_FIELD_BY_TYPE.items():
			if other_type != self.related_type:
				self.set(field, None)

	def _require_resolution_when_resolved(self):
		if self.status == "Resolved":
			if not self.resolution:
				frappe.throw(_("Add a resolution before marking this issue Resolved."))
			if not self.resolved_at:
				self.resolved_at = now_datetime()
		else:
			self.resolved_at = None

# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, today

from wedding_plan.invitation_logic import validate_transition

_STATUS_DATE_FIELD = {
	"Planned": "planned_date",
	"Sent": "sent_date",
	"Delivered": "delivered_date",
	"Acknowledged": "acknowledged_date",
	"Failed": "failed_date",
}


class WDInvitationTask(Document):
	def validate(self):
		self._check_duplicate()
		self._apply_status_change()

	def _check_duplicate(self):
		duplicate = frappe.db.exists(
			"WD Invitation Task",
			{
				"wedding": self.wedding,
				"household": self.household,
				"channel": self.channel,
				"name": ("!=", self.name or ""),
			},
		)
		if duplicate:
			frappe.throw(
				_("An invitation task for this household and channel already exists ({0}).").format(duplicate)
			)

	def _apply_status_change(self):
		previous_status = None
		if not self.is_new():
			previous_status = frappe.db.get_value("WD Invitation Task", self.name, "status")

		if previous_status is None:
			# Fresh row: only enforce the shape of the status, not a transition
			# (auto-provisioned tasks are created directly at any status by
			# ensure_invitation_tasks / bulk_update).
			previous_status = self.status

		if previous_status != self.status and not self.flags.ignore_status_transition:
			validate_transition(previous_status, self.status)

		if previous_status == self.status and not self.is_new():
			return

		self.last_status_change = now_datetime()

		date_field = _STATUS_DATE_FIELD.get(self.status)
		if date_field and not self.get(date_field):
			self.set(date_field, today())

		if self.status == "Failed":
			self.retry_required = 1
		else:
			self.retry_required = 0
			self.failure_reason = None
			if previous_status == "Failed" and self.status == "Planned":
				self.retry_count = (self.retry_count or 0) + 1

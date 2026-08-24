# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WDInvitationLog(Document):
	def validate(self):
		if self.is_new():
			self.attempt_number = (
				frappe.db.count("WD Invitation Log", {"invitation_task": self.invitation_task}) + 1
			)

		task = frappe.db.get_value(
			"WD Invitation Task", self.invitation_task, ["wedding", "household", "channel"], as_dict=True
		)
		if not task:
			frappe.throw(_("Invitation Task {0} not found.").format(self.invitation_task))
		if (self.wedding, self.household, self.channel) != (task.wedding, task.household, task.channel):
			frappe.throw(_("This log's wedding/household/channel must match its Invitation Task."))

# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WDGifting(Document):
	def validate(self):
		self._check_guest_member()

	def _check_guest_member(self):
		if not self.guest_member:
			return
		guest_member_guest = frappe.db.get_value("WD Guest Member", self.guest_member, "guest")
		if self.guest and guest_member_guest != self.guest:
			frappe.throw(_("Guest Member {0} does not belong to the selected Guest.").format(self.guest_member))

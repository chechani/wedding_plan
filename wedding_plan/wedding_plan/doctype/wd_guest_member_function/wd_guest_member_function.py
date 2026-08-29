# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class WDGuestMemberFunction(Document):
	def validate(self):
		self._set_household()
		self._check_duplicate()
		self._track_status_change()

	def _set_household(self):
		member = frappe.db.get_value("WD Guest Member", self.guest_member, ["guest", "wedding"], as_dict=True)
		if not member:
			frappe.throw(_("Guest member {0} not found.").format(self.guest_member))
		if member.wedding != self.wedding:
			frappe.throw(_("This guest member belongs to a different wedding."))
		self.household = member.guest

		if not self.meal_preference and self.is_new():
			self.meal_preference = frappe.db.get_value("WD Guest Member", self.guest_member, "dietary")

	def _check_duplicate(self):
		# WDGuest._sync_member_attendance (wd_guest.py) already computes the
		# full set of existing (guest_member, function) pairs in one query
		# before looping — every row it inserts is one it already confirmed
		# isn't a duplicate, so it sets this flag to skip re-running the same
		# check per row.
		if self.flags.skip_duplicate_check:
			return
		duplicate = frappe.db.exists(
			"WD Guest Member Function",
			{
				"guest_member": self.guest_member,
				"function": self.function,
				"name": ("!=", self.name or ""),
			},
		)
		if duplicate:
			frappe.throw(
				_("An attendance record for this guest member and function already exists ({0}).").format(duplicate)
			)

	def _track_status_change(self):
		if self.is_new() or self.has_value_changed("status"):
			self.last_status_change = now_datetime()

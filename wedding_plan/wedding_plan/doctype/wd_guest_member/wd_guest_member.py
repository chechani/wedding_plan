# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from wedding_plan.doc_validation import assert_child_belongs_to_parent


class WDGuestMember(Document):
	def validate(self):
		self._check_household_wedding()
		self._reset_stale_access_level()

	def _check_household_wedding(self):
		assert_child_belongs_to_parent(
			"WD Guest", self.guest, "wedding", self.wedding,
			_("This household belongs to a different wedding."),
		)

	def _reset_stale_access_level(self):
		if not self.portal_enabled:
			self.portal_access_level = "None"

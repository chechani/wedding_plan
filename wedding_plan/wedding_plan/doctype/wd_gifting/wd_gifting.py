# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from wedding_plan.doc_validation import assert_child_belongs_to_parent


class WDGifting(Document):
	def validate(self):
		self._check_guest_member()

	def _check_guest_member(self):
		assert_child_belongs_to_parent(
			"WD Guest Member", self.guest_member, "guest", self.guest,
			_("Guest Member {0} does not belong to the selected Guest.").format(self.guest_member),
		)

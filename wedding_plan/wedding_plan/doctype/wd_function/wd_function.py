# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from wedding_plan.doc_validation import assert_child_belongs_to_parent


class WDFunction(Document):
	def validate(self):
		self._check_sub_venue()

	def _check_sub_venue(self):
		assert_child_belongs_to_parent(
			"WD Sub Venue", self.sub_venue, "venue", self.venue,
			_("Sub Venue {0} does not belong to the selected Venue.").format(self.sub_venue),
		)

import frappe
from frappe import _
from frappe.model.document import Document

from wedding_plan.whatsapp.whatsform_client import classify_attachment

_KIND_LABELS = {"image": "Image", "video": "Video", "document": "Document"}


class WDWhatsAppCampaignTemplate(Document):
	def validate(self):
		if not (self.message or self.attachment):
			frappe.throw(_("Add a message or an attachment."))
		self.attachment_kind = _KIND_LABELS.get(classify_attachment(self.attachment), "") if self.attachment else ""

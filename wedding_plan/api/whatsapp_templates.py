"""Reusable WhatsApp campaign templates — a saved message + optional
image/video/document attachment that a campaign can be started from.

Not to be confused with `WD WhatsApp Template` (Meta-approved WhatsApp
Business API templates for the separate, unused `whatsform.in` direct-send
path) — these are personal-WhatsApp (WasenderAPI) campaign starting points,
copied onto a campaign at creation time rather than referenced live; see
`create_whatsapp_campaign`'s `template` param in `api/whatsapp.py`.
"""
import frappe
from frappe import _

from wedding_plan.api.whatsapp import _attach_file


def _template_wedding(template):
    wedding = frappe.db.get_value("WD WhatsApp Campaign Template", template, "wedding")
    if not wedding:
        frappe.throw(_("Template not found."))
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    return wedding


@frappe.whitelist()
def list_whatsapp_templates(wedding):
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    return frappe.get_all(
        "WD WhatsApp Campaign Template",
        filters={"wedding": wedding},
        fields=["name", "template_name", "message", "attachment", "attachment_kind"],
        order_by="creation desc",
    )


@frappe.whitelist()
def create_whatsapp_template(wedding, template_name, message=None, attachment=None):
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    if not (message or attachment):
        frappe.throw(_("Add a message or an attachment."))
    doc = frappe.get_doc({
        "doctype": "WD WhatsApp Campaign Template", "wedding": wedding,
        "template_name": template_name, "message": message,
    }).insert()
    if attachment:
        doc.attachment = _attach_file("WD WhatsApp Campaign Template", doc.name, "attachment", attachment)
        doc.save()  # re-runs validate(), which sets attachment_kind from the file
    return doc.as_dict()


@frappe.whitelist()
def update_whatsapp_template(template, template_name=None, message=None, attachment=None):
    _template_wedding(template)
    doc = frappe.get_doc("WD WhatsApp Campaign Template", template)
    if template_name is not None:
        doc.template_name = template_name
    if message is not None:
        doc.message = message
    if attachment is not None and attachment != doc.attachment:
        previous = doc.attachment
        doc.attachment = _attach_file("WD WhatsApp Campaign Template", doc.name, "attachment", attachment)
        if previous:
            # Orphaned now that `attachment` points elsewhere — nothing else
            # can reference it (campaigns hold their own copy, never this URL).
            frappe.delete_doc("File", frappe.get_value("File", {"file_url": previous}), ignore_permissions=True)
    if not (doc.message or doc.attachment):
        frappe.throw(_("Add a message or an attachment."))
    doc.save()
    return doc.as_dict()


@frappe.whitelist()
def delete_whatsapp_template(template):
    _template_wedding(template)
    # Campaigns already built from this template hold their own independent
    # copy of the message/attachment (see create_whatsapp_campaign) and don't
    # need this row to keep working — `source_template` is purely historical
    # labelling. Clear it first so Frappe's link-integrity check (correctly,
    # in general) doesn't refuse the delete over a reference nothing depends on.
    for campaign in frappe.get_all("WD WhatsApp Campaign", filters={"source_template": template}, pluck="name"):
        frappe.db.set_value("WD WhatsApp Campaign", campaign, "source_template", None)
    frappe.delete_doc("WD WhatsApp Campaign Template", template, ignore_permissions=True)

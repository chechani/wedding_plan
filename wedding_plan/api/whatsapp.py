import json

import frappe
from frappe import _

from wedding_plan.whatsapp.whatsform_client import send_text, send_template


def _log(wedding, template_key, to_phone, payload, status, provider_message_id=None):
    frappe.get_doc({
        "doctype": "WD WhatsApp Message Log",
        "wedding": wedding,
        "direction": "Out",
        "template_key": template_key,
        "to_phone": to_phone,
        "payload": json.dumps(payload, default=str),
        "status": status,
        "provider_message_id": provider_message_id,
    }).insert(ignore_permissions=True)
    frappe.db.commit()


@frappe.whitelist()
def whatsapp_send_text(wedding, to_phone, message):
    if not frappe.has_permission("Wedding", "read", doc=wedding):
        frappe.throw(_("Not permitted"))
    result = send_text(to_phone, message)
    _log(wedding, None, to_phone, {"message": message}, "SENT", result.get("message"))
    return result


@frappe.whitelist()
def whatsapp_send_template(wedding, to_phones, template_key, components=None):
    """to_phones: list (or comma-separated string) of numbers to send the
    approved template to in one call — matches whatsform.in's
    send_template_to_multiple_numbers shape directly."""
    if not frappe.has_permission("Wedding", "read", doc=wedding):
        frappe.throw(_("Not permitted"))
    if isinstance(to_phones, str):
        to_phones = [p.strip() for p in to_phones.split(",") if p.strip()]
    if isinstance(components, str):
        components = json.loads(components)

    result = send_template(template_key, to_phones, components)
    for phone in to_phones:
        _log(wedding, template_key, phone, {"components": components}, "SENT", result.get("message"))
    return result

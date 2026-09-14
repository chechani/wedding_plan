import json

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from wedding_plan.whatsapp.scheduler import RETRYABLE, campaign_counts, sync_campaign_counts
from wedding_plan.whatsapp.whatsform_client import send_template, send_text


def _log(wedding, template_key, to_phone, payload, result, provider_message_id=None):
    status = "SENT" if not result.get("dry_run") else "DRY_RUN"
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


def _campaign_wedding(campaign):
    """Resolve a campaign's wedding and assert send rights on it.

    Anything that puts a message on its way — scheduling, sending the next
    one, retrying — needs "write", not "read": read-only roles (Family
    Readonly, Shadow Readonly) must not be able to trigger a real send.
    """
    wedding = frappe.db.get_value("WD WhatsApp Campaign", campaign, "wedding")
    if not wedding:
        frappe.throw(_("Campaign not found."))
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    return wedding


@frappe.whitelist()
def whatsapp_send_text(wedding, to_phone, message):
    # "write" (not "read") — sending a message is a write-ish action with
    # real cost/guest-facing impact, so read-only roles (Family Readonly,
    # Shadow Readonly) must not be able to trigger it.
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    result = send_text(to_phone, message)
    _log(wedding, None, to_phone, {"message": message}, result, result.get("message"))
    return result


@frappe.whitelist()
def whatsapp_send_template(wedding, to_phones, template_key, components=None):
    """to_phones: list (or comma-separated string) of numbers to send the
    approved template to in one call — matches whatsform.in's
    send_template_to_multiple_numbers shape directly."""
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    if isinstance(to_phones, str):
        to_phones = [p.strip() for p in to_phones.split(",") if p.strip()]
    if isinstance(components, str):
        components = json.loads(components)

    result = send_template(template_key, to_phones, components)
    for phone in to_phones:
        _log(wedding, template_key, phone, {"components": components}, result, result.get("message"))
    return result


@frappe.whitelist()
def list_whatsapp_campaigns(wedding):
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    return frappe.get_all(
        "WD WhatsApp Campaign",
        filters={"wedding": wedding},
        fields=["name", "campaign_name", "message", "media_file", "interval_minutes", "start_at", "status", "next_send_at", "total_count", "sent_count", "failed_count", "skipped_count", "pending_count", "last_error"],
        order_by="creation desc",
    )


@frappe.whitelist()
def create_whatsapp_campaign(wedding, campaign_name, message=None, interval_minutes=10, start_at=None, households=None, media_file=None):
    # Sending is a write-ish action with real, guest-facing cost, so read-only
    # roles must not be able to set a campaign up or fire it.
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    if isinstance(households, str):
        households = frappe.parse_json(households)
    households = households or []
    interval_minutes = max(1, int(interval_minutes))
    start_at = get_datetime(start_at) if start_at else now_datetime()
    if not households:
        frappe.throw(_("Select at least one guest family."))

    guests = frappe.get_all("WD Guest", filters={"wedding": wedding, "name": ["in", households]}, fields=["name", "primary_phone", "household_name"])
    by_id = {row.name: row for row in guests}
    rows = []
    for household in households:
        guest = by_id.get(household)
        if not guest:
            continue
        # A family with no mobile number still gets a row, with the reason on
        # it — the campaign must account for every family that was chosen,
        # not quietly drop the ones it cannot reach.
        if guest.primary_phone:
            rows.append({"household": household, "phone": guest.primary_phone, "status": "Pending"})
        else:
            rows.append({"household": household, "phone": "-", "status": "No Phone", "error": _("No mobile number on this guest family.")})
    if not rows:
        frappe.throw(_("The selected guest families could not be found."))

    campaign = frappe.get_doc({
        "doctype": "WD WhatsApp Campaign", "wedding": wedding, "campaign_name": campaign_name,
        "message": message, "interval_minutes": interval_minutes, "start_at": start_at,
        "next_send_at": None, "status": "Draft", "sent_count": 0, "failed_count": 0,
    }).insert()
    for row in rows:
        frappe.get_doc({"doctype": "WD WhatsApp Campaign Recipient", "wedding": wedding, "campaign": campaign.name, **row}).insert()
    sync_campaign_counts(campaign.name)
    campaign.reload()
    if media_file:
        file_doc = frappe.get_doc("File", {"file_url": media_file})
        if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw(_("Not permitted to use this image."))
        file_doc.attached_to_doctype = "WD WhatsApp Campaign"
        file_doc.attached_to_name = campaign.name
        file_doc.attached_to_field = "media_file"
        file_doc.save(ignore_permissions=True)
        frappe.db.set_value("WD WhatsApp Campaign", campaign.name, "media_file", media_file)
        campaign.media_file = media_file
    return campaign.as_dict()


@frappe.whitelist()
def schedule_whatsapp_campaign(campaign, media_file=None):
     _campaign_wedding(campaign)
     doc = frappe.get_doc("WD WhatsApp Campaign", campaign)
     if media_file:
         file_doc = frappe.get_doc("File", {"file_url": media_file})
         if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
             frappe.throw(_("Not permitted to use this image."))
         file_doc.attached_to_doctype = "WD WhatsApp Campaign"
         file_doc.attached_to_name = doc.name
         file_doc.attached_to_field = "media_file"
         file_doc.save(ignore_permissions=True)
         doc.media_file = media_file
     if not (doc.message or doc.media_file):
         frappe.throw(_("Add a message or upload an image before scheduling."))
     doc.status = "Scheduled"
     doc.next_send_at = now_datetime()
     doc.save(ignore_permissions=True)
     return doc.as_dict()


@frappe.whitelist()
def whatsapp_campaign_recipients(campaign):
    wedding = frappe.db.get_value("WD WhatsApp Campaign", campaign, "wedding")
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    recipients = frappe.get_all(
        "WD WhatsApp Campaign Recipient",
        filters={"campaign": campaign},
        fields=["name", "household", "phone", "status", "sent_at", "account", "error", "attempts", "last_attempt_at", "provider_message_id"],
        order_by="creation asc",
    )
    names = {row.household for row in recipients}
    labels = {row.name: row.household_name for row in frappe.get_all("WD Guest", filters={"name": ["in", list(names)]}, fields=["name", "household_name"])} if names else {}
    return [{**row, "household_name": labels.get(row.household, row.household)} for row in recipients]


@frappe.whitelist()
def whatsapp_campaign_report(campaign):
    """Everything one campaign is accountable for: the counts, and the row
    per guest family behind them."""
    wedding = frappe.db.get_value("WD WhatsApp Campaign", campaign, "wedding")
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    counts = campaign_counts(campaign)
    return {"counts": counts, "recipients": whatsapp_campaign_recipients(campaign)}


@frappe.whitelist()
def retry_whatsapp_campaign_recipients(campaign, recipients=None):
    """Queue the families that did not get the message for another send.

    `recipients` is the list of recipient row names to retry; leave it out to
    retry every family that is not a confirmed Sent (failed, skipped, stuck
    mid-send, or missing a number that has since been added).
    """
    _campaign_wedding(campaign)
    if isinstance(recipients, str):
        recipients = frappe.parse_json(recipients)

    filters = {"campaign": campaign, "status": ["in", list(RETRYABLE)]}
    if recipients:
        filters["name"] = ["in", recipients]
    rows = frappe.get_all("WD WhatsApp Campaign Recipient", filters=filters, fields=["name", "household", "phone", "status"], order_by="creation asc")
    if not rows:
        frappe.throw(_("There is nothing left to retry on this campaign."))

    # A family whose number was missing may have had one added since — pick
    # the current number up rather than retrying against a blank.
    phones = {
        row.name: row.primary_phone
        for row in frappe.get_all("WD Guest", filters={"name": ["in", [r.household for r in rows]]}, fields=["name", "primary_phone"])
    }
    requeued, unreachable = 0, 0
    for row in rows:
        phone = phones.get(row.household)
        if not phone:
            frappe.db.set_value("WD WhatsApp Campaign Recipient", row.name, {
                "status": "No Phone", "error": _("No mobile number on this guest family."),
            })
            unreachable += 1
            continue
        # The previous reason stays on the row until the retry actually runs,
        # so the list still says why each family is being sent to again.
        frappe.db.set_value("WD WhatsApp Campaign Recipient", row.name, {"status": "Pending", "phone": phone})
        requeued += 1

    extra = {}
    if requeued:
        extra = {"status": "Scheduled", "next_send_at": now_datetime(), "last_error": None}
    counts = sync_campaign_counts(campaign, **extra)
    return {"requeued": requeued, "unreachable": unreachable, "counts": counts}


@frappe.whitelist()
def run_whatsapp_campaign_now(campaign):
    _campaign_wedding(campaign)
    return __import__("wedding_plan.whatsapp.scheduler", fromlist=["process_campaign"]).process_campaign(campaign)

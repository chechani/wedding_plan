import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from wedding_plan.whatsapp.scheduler import RETRYABLE, campaign_counts, sync_campaign_counts
from wedding_plan.whatsapp.whatsform_client import send_template, send_text


# Who a campaign goes to. "Guest Family" sends one message per WD Guest
# (household) to its `primary_phone`; "Guest" sends one per WD Guest Member
# to that person's own `mobile`. Either way every recipient row keeps the
# household in `household`, so labels and permissions work the same.
AUDIENCES = ("Guest Family", "Guest")


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


def _attach_file(doctype, name, field, file_url):
    """Point `doctype`/`name`/`field` at an already-uploaded File.

    A file that isn't owned by anything yet (a fresh upload) is reassigned
    directly — the cheap, common case — after checking the caller actually
    owns it, so a client can't hijack an arbitrary stranger's private upload
    by URL. A file that's already attached to a *different* document (most
    commonly: this is a template's attachment, being used to start a
    campaign) is copied instead of stolen — the original keeps working, and
    permission to read it was already established by the caller being able
    to load that other document in the first place.

    `file_url` is not actually unique: Frappe deduplicates identical byte
    content onto one physical path, so a template's attachment and every
    campaign copied from it can share the exact same URL string across
    several distinct File *documents*. Resolving straight from the URL would
    non-deterministically land on any one of them — including, worst case,
    a sibling campaign's own copy, which must never be treated as a source
    to copy from. So: prefer an unattached row (a genuine fresh upload) if
    one exists, else the oldest row not itself owned by a Campaign (the
    original — a template, typically) — a Campaign's own copy is only ever a
    destination here, never a source.
    """
    candidates = frappe.get_all(
        "File",
        filters={"file_url": file_url},
        fields=["name", "attached_to_doctype", "attached_to_name", "owner"],
        order_by="creation asc",
    )
    if not candidates:
        frappe.throw(_("That file could not be found."))
    match = next((c for c in candidates if not c.attached_to_name), None)
    if not match and any(c.attached_to_doctype == doctype and c.attached_to_name == name for c in candidates):
        return file_url  # already exactly where it needs to be
    if not match:
        match = next((c for c in candidates if c.attached_to_doctype != "WD WhatsApp Campaign"), candidates[0])
    file_doc = frappe.get_doc("File", match.name)

    if file_doc.attached_to_name:
        new_file = frappe.get_doc({
            "doctype": "File",
            "file_name": file_doc.file_name,
            "content": file_doc.get_content(),
            "is_private": file_doc.is_private,
            "attached_to_doctype": doctype,
            "attached_to_name": name,
            "attached_to_field": field,
        }).insert(ignore_permissions=True)
        return new_file.file_url

    if file_doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Not permitted to use this file."))
    file_doc.attached_to_doctype = doctype
    file_doc.attached_to_name = name
    file_doc.attached_to_field = field
    file_doc.save(ignore_permissions=True)
    return file_url


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
        fields=["name", "campaign_name", "audience", "message", "media_file", "interval_minutes", "start_at", "status", "next_send_at", "total_count", "sent_count", "failed_count", "skipped_count", "pending_count", "last_error"],
        order_by="creation desc",
    )


@frappe.whitelist()
def whatsapp_campaign_audience(wedding, audience="Guest Family"):
    """Everyone a new campaign could be sent to, plus what the composer
    filters them on, in one round trip.

    Returns `{"functions": [...], "rows": [...]}`. Each row carries
    `invited_functions` (the All/Selective select on WD Guest; always None
    for a member, whose select was replaced by `invited_dates`), member rows
    also carry `invited_dates` (with the Select's options returned as
    `invited_dates_options`), and every row carries `functions`, the
    specific WD Functions it is invited to: `functions_invited` for a family, its `WD Guest Member Function` rows for
    an individual guest. Filtering itself happens in the browser — a wedding
    has hundreds of rows, not hundreds of thousands.
    """
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    if audience not in AUDIENCES:
        frappe.throw(_("Unknown audience: {0}").format(audience))

    functions = frappe.get_all(
        "WD Function", filters={"wedding": wedding},
        fields=["name", "function_type", "date"], order_by="date asc, start_time asc, creation asc",
    )
    families = frappe.get_all(
        "WD Guest", filters={"wedding": wedding},
        fields=["name", "household_name", "primary_phone", "side", "category", "sub_group", "rsvp_status", "invited_functions"],
        order_by="household_name asc", limit_page_length=0,
    )

    invited = defaultdict(list)
    if audience == "Guest Family":
        if families:
            # WD Guest Function is a child table with no `wedding` of its own,
            # so scope it through the parents.
            for row in frappe.get_all(
                "WD Guest Function",
                filters={"parenttype": "WD Guest", "parentfield": "functions_invited", "parent": ["in", [f.name for f in families]]},
                fields=["parent", "wd_function"], limit_page_length=0,
            ):
                invited[row.parent].append(row.wd_function)
        rows = [{
            "name": f.name, "label": f.household_name, "family": f.household_name,
            "phone": f.primary_phone or None, "side": f.side, "category": f.category,
            "sub_group": f.sub_group, "rsvp_status": f.rsvp_status,
            "invited_functions": f.invited_functions or None, "functions": invited.get(f.name, []),
        } for f in families]
    else:
        by_family = {f.name: f for f in families}
        for row in frappe.get_all(
            "WD Guest Member Function", filters={"wedding": wedding},
            fields=["guest_member", "function"], limit_page_length=0,
        ):
            invited[row.guest_member].append(row.function)
        members = frappe.get_all(
            "WD Guest Member", filters={"wedding": wedding},
            fields=["name", "full_name", "guest", "mobile", "relation_to_household", "age_group", "gender", "invited_dates"],
            order_by="full_name asc", limit_page_length=0,
        )
        rows = []
        for m in members:
            family = by_family.get(m.guest) or frappe._dict()
            rows.append({
                "name": m.name, "label": m.full_name, "family": family.household_name or m.guest,
                "phone": m.mobile or None, "side": family.side, "category": family.category,
                "sub_group": family.sub_group, "rsvp_status": family.rsvp_status,
                "relation": m.relation_to_household, "age_group": m.age_group, "gender": m.gender,
                "invited_dates": m.invited_dates or None,
                "invited_functions": None, "functions": invited.get(m.name, []),
            })
    result = {"functions": functions, "rows": rows}
    if audience == "Guest":
        # The filter offers the Select's own options, so a date can be picked
        # even before any member has it.
        field = frappe.get_meta("WD Guest Member").get_field("invited_dates")
        result["invited_dates_options"] = [o for o in (field.options or "").split("\n") if o.strip()] if field else []
    return result


def _family_recipient_rows(wedding, households):
    guests = frappe.get_all("WD Guest", filters={"wedding": wedding, "name": ["in", households]}, fields=["name", "primary_phone"])
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
    return rows


def _member_recipient_rows(wedding, members):
    found = frappe.get_all("WD Guest Member", filters={"wedding": wedding, "name": ["in", members]}, fields=["name", "guest", "mobile"])
    by_id = {row.name: row for row in found}
    rows = []
    for member_id in members:
        member = by_id.get(member_id)
        if not member:
            continue
        base = {"household": member.guest, "guest_member": member.name}
        if member.mobile:
            rows.append({**base, "phone": member.mobile, "status": "Pending"})
        else:
            rows.append({**base, "phone": "-", "status": "No Phone", "error": _("No mobile number on this guest.")})
    return rows


@frappe.whitelist()
def create_whatsapp_campaign(wedding, campaign_name, message=None, interval_minutes=10, start_at=None, households=None, media_file=None, template=None, audience="Guest Family", members=None):
    """`template` (a `WD WhatsApp Campaign Template` name) pre-fills `message`
    and `media_file` when those aren't given explicitly — as an independent
    copy at creation time, not a live link. Editing or deleting the template
    afterward never reaches back into a campaign already built from it.

    `audience` "Guest Family" (the default, and the only option before it
    existed) reads `households`; "Guest" reads `members` (WD Guest Member
    names) and sends to each person's own `mobile`.

    A message is optional: an attachment alone (image, video, PDF) is a
    complete campaign. One of the two is required.
    """
    # Sending is a write-ish action with real, guest-facing cost, so read-only
    # roles must not be able to set a campaign up or fire it.
    if not frappe.has_permission("Wedding", "write", doc=wedding):
        frappe.throw(_("Not permitted"))
    audience = audience or "Guest Family"
    if audience not in AUDIENCES:
        frappe.throw(_("Unknown audience: {0}").format(audience))
    selected = members if audience == "Guest" else households
    if isinstance(selected, str):
        selected = frappe.parse_json(selected)
    selected = selected or []
    interval_minutes = max(1, int(interval_minutes))
    start_at = get_datetime(start_at) if start_at else now_datetime()
    if not selected:
        frappe.throw(_("Select at least one guest.") if audience == "Guest" else _("Select at least one guest family."))

    if template:
        # Only the message text is auto-filled here; the attachment is not —
        # the caller (the composer) already stages the template's attachment
        # into its own `media_file` when the family hasn't cleared it, and
        # `_attach_file` below copies rather than steals when that URL turns
        # out to belong to another document (the template). Auto-filling
        # `media_file` here too, from `template` alone, would silently bring
        # an attachment back after the caller had explicitly removed it.
        template_doc = frappe.get_doc("WD WhatsApp Campaign Template", template)
        if template_doc.wedding != wedding:
            frappe.throw(_("Template not found."))
        if message is None:
            message = template_doc.message

    message = (message or "").strip() or None
    if not (message or media_file):
        frappe.throw(_("Add a message or an attachment."))

    rows = _member_recipient_rows(wedding, selected) if audience == "Guest" else _family_recipient_rows(wedding, selected)
    if not rows:
        frappe.throw(_("The selected guests could not be found.") if audience == "Guest" else _("The selected guest families could not be found."))

    campaign = frappe.get_doc({
        "doctype": "WD WhatsApp Campaign", "wedding": wedding, "campaign_name": campaign_name,
        "audience": audience, "message": message, "interval_minutes": interval_minutes, "start_at": start_at,
        "source_template": template or None,
        "next_send_at": None, "status": "Draft", "sent_count": 0, "failed_count": 0,
    }).insert()
    for row in rows:
        frappe.get_doc({"doctype": "WD WhatsApp Campaign Recipient", "wedding": wedding, "campaign": campaign.name, **row}).insert()
    sync_campaign_counts(campaign.name)
    campaign.reload()
    if media_file:
        final_url = _attach_file("WD WhatsApp Campaign", campaign.name, "media_file", media_file)
        frappe.db.set_value("WD WhatsApp Campaign", campaign.name, "media_file", final_url)
        campaign.media_file = final_url
    return campaign.as_dict()


@frappe.whitelist()
def schedule_whatsapp_campaign(campaign, media_file=None, start_at=None):
     """Move a Draft campaign to Scheduled.

     `start_at` is when the *first* message should go out; leave it out (or
     pass a moment already in the past) to start right away, as before. The
     per-recipient gap (`interval_minutes`) only ever applies *between* sends
     — see `process_campaign` — so however far out `start_at` is, the first
     family is messaged the moment the campaign becomes due, not one interval
     after that.
     """
     _campaign_wedding(campaign)
     doc = frappe.get_doc("WD WhatsApp Campaign", campaign)
     if media_file:
         doc.media_file = _attach_file("WD WhatsApp Campaign", doc.name, "media_file", media_file)
     if not (doc.message or doc.media_file):
         frappe.throw(_("Add a message or an attachment before scheduling."))
     doc.status = "Scheduled"
     doc.start_at = get_datetime(start_at) if start_at else now_datetime()
     doc.next_send_at = doc.start_at
     doc.save(ignore_permissions=True)
     return doc.as_dict()


@frappe.whitelist()
def whatsapp_campaign_recipients(campaign):
    wedding = frappe.db.get_value("WD WhatsApp Campaign", campaign, "wedding")
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    recipients = frappe.get_all(
        "WD WhatsApp Campaign Recipient",
        filters={"campaign": campaign},
        fields=["name", "household", "guest_member", "phone", "status", "sent_at", "account", "error", "attempts", "last_attempt_at", "provider_message_id"],
        order_by="creation asc",
    )
    names = {row.household for row in recipients}
    labels = {row.name: row.household_name for row in frappe.get_all("WD Guest", filters={"name": ["in", list(names)]}, fields=["name", "household_name"])} if names else {}
    member_ids = [row.guest_member for row in recipients if row.guest_member]
    member_labels = {row.name: row.full_name for row in frappe.get_all("WD Guest Member", filters={"name": ["in", member_ids]}, fields=["name", "full_name"])} if member_ids else {}
    return [{
        **row,
        "household_name": labels.get(row.household, row.household),
        # Who the message went to: the person on a Guest campaign, the
        # family otherwise.
        "recipient_name": member_labels.get(row.guest_member, row.guest_member) if row.guest_member else labels.get(row.household, row.household),
    } for row in recipients]


@frappe.whitelist()
def whatsapp_campaign_report(campaign):
    """Everything one campaign is accountable for: the counts, and the row
    per guest family behind them."""
    wedding = frappe.db.get_value("WD WhatsApp Campaign", campaign, "wedding")
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    counts = campaign_counts(campaign)
    return {"counts": counts, "recipients": whatsapp_campaign_recipients(campaign)}


def _resume_if_failed(campaign):
    """Put a Failed campaign that still has Pending rows back on the queue.

    A campaign fails as a whole when no sender account was enabled, and its
    rows stay Pending. Nothing else restarts it: the scheduler skips Failed
    campaigns, and retry only requeues Failed/Skipped/No Phone rows. Returns
    how many Pending rows were resumed (0 if nothing changed).
    """
    if frappe.db.get_value("WD WhatsApp Campaign", campaign, "status") != "Failed":
        return 0
    pending = frappe.db.count("WD WhatsApp Campaign Recipient", filters={"campaign": campaign, "status": "Pending"})
    if pending:
        sync_campaign_counts(campaign, status="Scheduled", next_send_at=now_datetime(), last_error=None)
    return pending


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
    rows = frappe.get_all("WD WhatsApp Campaign Recipient", filters=filters, fields=["name", "household", "guest_member", "phone", "status"], order_by="creation asc")
    resumed = _resume_if_failed(campaign)
    if not rows and resumed:
        return {"requeued": 0, "unreachable": 0, "resumed": resumed, "counts": campaign_counts(campaign)}
    if not rows:
        frappe.throw(_("There is nothing left to retry on this campaign."))

    # A family (or guest) whose number was missing may have had one added
    # since — pick the current number up rather than retrying against a blank.
    family_ids = [r.household for r in rows if not r.guest_member]
    member_ids = [r.guest_member for r in rows if r.guest_member]
    family_phones = {
        row.name: row.primary_phone
        for row in frappe.get_all("WD Guest", filters={"name": ["in", family_ids]}, fields=["name", "primary_phone"])
    } if family_ids else {}
    member_phones = {
        row.name: row.mobile
        for row in frappe.get_all("WD Guest Member", filters={"name": ["in", member_ids]}, fields=["name", "mobile"])
    } if member_ids else {}
    requeued, unreachable = 0, 0
    for row in rows:
        phone = member_phones.get(row.guest_member) if row.guest_member else family_phones.get(row.household)
        if not phone:
            frappe.db.set_value("WD WhatsApp Campaign Recipient", row.name, {
                "status": "No Phone",
                "error": _("No mobile number on this guest.") if row.guest_member else _("No mobile number on this guest family."),
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
    return {"requeued": requeued, "unreachable": unreachable, "resumed": resumed, "counts": counts}


@frappe.whitelist()
def run_whatsapp_campaign_now(campaign):
    _campaign_wedding(campaign)
    _resume_if_failed(campaign)
    return __import__("wedding_plan.whatsapp.scheduler", fromlist=["process_campaign"]).process_campaign(campaign)

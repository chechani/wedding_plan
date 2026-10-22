import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from wedding_plan.guest_import import normalise_phone
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
        fields=["name", "campaign_name", "audience", "message", "media_file", "interval_minutes", "send_mode", "start_at", "status", "next_send_at", "total_count", "sent_count", "failed_count", "skipped_count", "pending_count", "last_error"],
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
    `invited_dates_options`; every filter's full choices are in
    `filter_options`), and every row carries `functions`, the
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
    filter_fields = AUDIENCE_FILTER_FIELDS["Guest Family"] + (AUDIENCE_FILTER_FIELDS["Guest"] if audience == "Guest" else [])
    filter_options = {key: _field_choices(doctype, fieldname, wedding) for key, doctype, fieldname in filter_fields}
    result = {"functions": functions, "rows": rows, "filter_options": filter_options}
    if audience == "Guest":
        # Kept for a frontend that predates `filter_options`.
        result["invited_dates_options"] = filter_options["invited_dates"]
    return result


# Composer filter (row key) -> the field its values come from. The filter
# offers every value the field allows, not just the ones some guest already
# has, so e.g. a Relation can be picked before anyone is tagged with it.
AUDIENCE_FILTER_FIELDS = {
    "Guest Family": [
        ("side", "WD Guest", "side"),
        ("category", "WD Guest", "category"),
        ("rsvp_status", "WD Guest", "rsvp_status"),
        ("invited_functions", "WD Guest", "invited_functions"),
    ],
    "Guest": [
        ("relation", "WD Guest Member", "relation_to_household"),
        ("age_group", "WD Guest Member", "age_group"),
        ("invited_dates", "WD Guest Member", "invited_dates"),
    ],
}


def _field_choices(doctype, fieldname, wedding):
    """Every value a Select or Link field can hold, in the field's own order.

    A Link lists the linked records, scoped to this wedding when the linked
    doctype has a `wedding` field. Any other field type has no fixed choices.
    """
    field = frappe.get_meta(doctype).get_field(fieldname)
    if not field:
        return []
    if field.fieldtype == "Select":
        return [option for option in (field.options or "").split("\n") if option.strip()]
    if field.fieldtype == "Link" and field.options:
        filters = {"wedding": wedding} if frappe.get_meta(field.options).has_field("wedding") else {}
        return frappe.get_all(field.options, filters=filters, pluck="name", order_by="name asc", limit_page_length=0)
    return []


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


def _resolve_start(mode, start_at):
    """(send_mode, start_at) for the planner's Immediate / Scheduled choice.

    No `mode` (an older frontend) keeps the old rule: a given `start_at` is
    the start, a blank one means now.
    """
    if mode not in (None, "", "immediate", "scheduled"):
        frappe.throw(_("Unknown schedule mode: {0}").format(mode))
    if mode == "scheduled":
        if not start_at:
            frappe.throw(_("Pick the date and time to start sending."))
        # A minute of slack for the time spent between picking and clicking.
        if get_datetime(start_at) < add_to_date(now_datetime(), minutes=-1):
            frappe.throw(_("The start time has already passed. Pick a later time, or send immediately."))
        return "Scheduled", get_datetime(start_at)
    if mode == "immediate" or not start_at:
        return "Immediate", now_datetime()
    return "Scheduled", get_datetime(start_at)


@frappe.whitelist()
def create_whatsapp_campaign(wedding, campaign_name, message=None, interval_minutes=10, start_at=None, households=None, media_file=None, template=None, audience="Guest Family", members=None, mode=None, ignored=None, ignore_against=None):
    """`template` (a `WD WhatsApp Campaign Template` name) pre-fills `message`
    and `media_file` when those aren't given explicitly — as an independent
    copy at creation time, not a live link. Editing or deleting the template
    afterward never reaches back into a campaign already built from it.

    `audience` "Guest Family" (the default, and the only option before it
    existed) reads `households`; "Guest" reads `members` (WD Guest Member
    names) and sends to each person's own `mobile`.

    A message is optional: an attachment alone (image, video, PDF) is a
    complete campaign. One of the two is required.

    `mode` ("immediate" / "scheduled") is decided here, before anything is
    created: a scheduled campaign must come with a future `start_at`. The
    campaign is still created as a Draft, so recipients can be reviewed
    (removed, ignored) before it is started.

    `ignored` lists selected guests (same ids as `households` / `members`)
    to record as Ignored instead of Pending: the composer's "ignore existing
    campaigns" check, matched on phone number against `ignore_against`. They
    stay on the campaign, with where they were already sent, but are never
    sent to unless included again.
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
    send_mode, start_at = _resolve_start(mode, start_at)
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
    ignored = set(frappe.parse_json(ignored) if isinstance(ignored, str) else (ignored or []))
    if ignored:
        by_phone = _sent_by_phone(wedding, against=_parse_against(ignore_against))
        for row in rows:
            if row["status"] == "Pending" and (row.get("guest_member") if audience == "Guest" else row["household"]) in ignored:
                row["status"], row["error"] = "Ignored", _already_sent_reason(by_phone.get(normalise_phone(row["phone"])))
    if not rows:
        frappe.throw(_("The selected guests could not be found.") if audience == "Guest" else _("The selected guest families could not be found."))

    campaign = frappe.get_doc({
        "doctype": "WD WhatsApp Campaign", "wedding": wedding, "campaign_name": campaign_name,
        "audience": audience, "message": message, "interval_minutes": interval_minutes, "send_mode": send_mode, "start_at": start_at,
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
def schedule_whatsapp_campaign(campaign, media_file=None, start_at=None, mode=None):
     """Move a Draft campaign to Scheduled.

     `mode` is the planner's explicit choice: "immediate" starts now whatever
     `start_at` says; "scheduled" requires a `start_at` that is still ahead.
     Without `mode` (an older frontend), `start_at` is when the *first*
     message should go out; leave it out (or pass a moment already in the
     past) to start right away, as before. The
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
     if not frappe.db.exists("WD WhatsApp Campaign Recipient", {"campaign": doc.name, "status": "Pending"}):
         frappe.throw(_("Nobody on this campaign is waiting to be sent to."))
     doc.send_mode, doc.start_at = _resolve_start(mode, start_at)
     doc.status = "Scheduled"
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


# A row that has gone out (or is going out right now) is the record of a real
# message; it can be neither removed nor ignored.
LOCKED = ("Sent", "Sending")


def _campaign_rows(campaign, recipients):
    if isinstance(recipients, str):
        recipients = frappe.parse_json(recipients)
    if not recipients:
        frappe.throw(_("Select at least one recipient."))
    return frappe.get_all(
        "WD WhatsApp Campaign Recipient",
        filters={"campaign": campaign, "name": ["in", recipients]},
        fields=["name", "phone", "status"],
    )


def _sent_by_phone(wedding, campaign=None, against=None):
    """Who already got a message from this wedding's campaigns (other than
    `campaign`), keyed by normalised phone number (the matching rule: one
    number, one person, whichever audience or guest record it was sent
    through). `against` limits it to those campaigns; `[]` matches nothing."""
    filters = {"wedding": wedding, "status": "Sent"}
    if campaign:
        filters["campaign"] = ["!=", campaign]
    if against is not None:
        against = [name for name in against if name != campaign]
        if not against:
            return {}
        filters["campaign"] = ["in", against]
    sent = frappe.get_all(
        "WD WhatsApp Campaign Recipient", filters=filters,
        fields=["name", "campaign", "household", "guest_member", "phone", "sent_at", "account"],
        order_by="sent_at desc", limit_page_length=0,
    )
    titles = dict(frappe.get_all(
        "WD WhatsApp Campaign", filters={"name": ["in", list({row.campaign for row in sent})]},
        fields=["name", "campaign_name"], as_list=True,
    )) if sent else {}
    by_phone = defaultdict(list)
    for row in sent:
        phone = normalise_phone(row.phone)
        if phone:
            by_phone[phone].append({
                "campaign": row.campaign, "campaign_name": titles.get(row.campaign, row.campaign),
                "recipient": row.name, "household": row.household, "guest_member": row.guest_member,
                "sent_at": row.sent_at, "account": row.account,
            })
    return by_phone


def _parse_against(against):
    if isinstance(against, str):
        against = frappe.parse_json(against)
    return against


def _already_sent_reason(hits):
    if not hits:
        return _("Ignored before sending.")
    return _("Already sent in {0}").format(", ".join(
        f"{hit['campaign_name']} ({frappe.utils.format_datetime(hit['sent_at'])})" if hit["sent_at"] else hit["campaign_name"]
        for hit in hits
    ))[:500]


def _campaigns_with_sends(wedding, exclude=None):
    """The campaigns a planner can pick to ignore against: any that has
    actually sent something."""
    filters = {"wedding": wedding, "sent_count": [">", 0]}
    if exclude:
        filters["name"] = ["!=", exclude]
    return frappe.get_all(
        "WD WhatsApp Campaign", filters=filters,
        fields=["name", "campaign_name", "audience", "status", "start_at", "sent_count"],
        order_by="creation desc",
    )


@frappe.whitelist()
def whatsapp_audience_overlap(wedding, audience="Guest Family", against=None):
    """For the composer, before a campaign exists: which of the guests it
    could be sent to already got a message in the `against` campaigns,
    matched on phone number. `matches` is keyed like the audience rows (WD
    Guest name for families, WD Guest Member name for guests)."""
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    if audience not in AUDIENCES:
        frappe.throw(_("Unknown audience: {0}").format(audience))
    by_phone = _sent_by_phone(wedding, against=_parse_against(against))
    if audience == "Guest":
        people = frappe.get_all("WD Guest Member", filters={"wedding": wedding}, fields=["name", "mobile as phone"], limit_page_length=0)
    else:
        people = frappe.get_all("WD Guest", filters={"wedding": wedding}, fields=["name", "primary_phone as phone"], limit_page_length=0)
    matches = {}
    for person in people:
        hits = by_phone.get(normalise_phone(person.phone)) if person.phone else None
        if hits:
            matches[person.name] = hits
    return {"campaigns": _campaigns_with_sends(wedding), "matches": matches}


@frappe.whitelist()
def whatsapp_campaign_overlap(campaign, against=None):
    """Which recipients of `campaign` were already sent a message by another
    campaign of the same wedding, matched on phone number.

    `against` limits the check to those campaign names; leave it out to check
    every other campaign. Returns `campaigns` (the ones that can be checked
    against, for the picker) and `matches` ({recipient row: [where it was
    sent]}), only for rows that can still be ignored or included.
    """
    wedding = frappe.db.get_value("WD WhatsApp Campaign", campaign, "wedding")
    frappe.has_permission("Wedding", doc=wedding, throw=True)
    campaigns = _campaigns_with_sends(wedding, exclude=campaign)
    by_phone = _sent_by_phone(wedding, campaign, _parse_against(against))
    matches = {}
    for row in frappe.get_all(
        "WD WhatsApp Campaign Recipient",
        filters={"campaign": campaign, "status": ["not in", list(LOCKED)]},
        fields=["name", "phone"], limit_page_length=0,
    ):
        found = by_phone.get(normalise_phone(row.phone))
        if found:
            matches[row.name] = found
    return {"campaigns": campaigns, "matches": matches}


@frappe.whitelist()
def ignore_whatsapp_campaign_recipients(campaign, recipients, ignore=1, against=None):
    """Mark waiting recipients Ignored (with where they were already sent), or
    put Ignored ones back to Pending. Only Pending rows can be ignored and
    only Ignored rows included, so a send that already happened, failed, or
    is in flight is never rewritten."""
    wedding = _campaign_wedding(campaign)
    ignore = frappe.utils.cint(ignore)
    rows = _campaign_rows(campaign, recipients)
    changed = 0
    if ignore:
        by_phone = _sent_by_phone(wedding, campaign, _parse_against(against))
        for row in rows:
            if row.status != "Pending":
                continue
            reason = _already_sent_reason(by_phone.get(normalise_phone(row.phone)))
            frappe.db.set_value("WD WhatsApp Campaign Recipient", row.name, {"status": "Ignored", "error": reason})
            changed += 1
    else:
        for row in rows:
            if row.status != "Ignored":
                continue
            frappe.db.set_value("WD WhatsApp Campaign Recipient", row.name, {"status": "Pending", "error": None})
            changed += 1
        # Including someone on a campaign that had already run out of people
        # to send to puts it back to work.
        if changed and frappe.db.get_value("WD WhatsApp Campaign", campaign, "status") == "Completed":
            return {"changed": changed, "counts": sync_campaign_counts(campaign, status="Scheduled", next_send_at=now_datetime())}
    return {"changed": changed, "counts": sync_campaign_counts(campaign)}


@frappe.whitelist()
def remove_whatsapp_campaign_recipients(campaign, recipients):
    """Take recipients off a campaign before they are sent to.

    Sent and in-flight rows are refused: they are the record of a message
    that really went out. If that leaves a running campaign with nobody
    waiting, it is marked Completed straight away.
    """
    _campaign_wedding(campaign)
    rows = _campaign_rows(campaign, recipients)
    locked = [row for row in rows if row.status in LOCKED]
    if locked:
        frappe.throw(_("{0} of the selected recipients already got the message (or are being sent it) and cannot be removed.").format(len(locked)))
    for row in rows:
        frappe.delete_doc("WD WhatsApp Campaign Recipient", row.name, ignore_permissions=True)
    extra = {}
    status = frappe.db.get_value("WD WhatsApp Campaign", campaign, "status")
    if status in ("Scheduled", "Running") and not frappe.db.exists("WD WhatsApp Campaign Recipient", {"campaign": campaign, "status": "Pending"}):
        extra = {"status": "Completed", "next_send_at": None}
    return {"removed": len(rows), "counts": sync_campaign_counts(campaign, **extra)}


def _resume_if_failed(campaign):
    """Put a Failed or Paused campaign that still has Pending rows back on the queue.

    A campaign fails as a whole when no sender account was enabled, and pauses
    when the sender's WhatsApp session is not connected; either way its rows
    stay Pending. Nothing else restarts it: the scheduler skips both, and retry
    only requeues rows that were attempted. Returns how many Pending rows were
    resumed (0 if nothing changed).
    """
    if frappe.db.get_value("WD WhatsApp Campaign", campaign, "status") not in ("Failed", "Paused"):
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

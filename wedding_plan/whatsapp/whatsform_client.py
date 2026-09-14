"""
Client for the ONE shared whatsform.in installation (per the user: "we will
use their API based on their one installation" — not a per-wedding account).

whatsform.in is itself a Frappe app (`frappe_whatsapp`, confirmed by reading
c:\\Frontends\\whatsform\\web_whatsform_in\\src, its own React frontend) exposing
RPC-style endpoints under /api/method/frappe_whatsapp.whatsapp_chat.*, using
standard Frappe token auth: `Authorization: token <api_key>:<api_secret>`.

Endpoints below are taken directly from that source (src/Components/Config/
url.ts + docType.ts + the two send call sites in src/Components/Contact/),
not guessed:
  - send_outgoing_text_message  {mobile_no, message}
  - send_template_to_multiple_numbers  {template, mobile_numbers, components,
    header_type, media_type, media_url, filename, filedata, media_name}

Configure via site_config.json:
  "whatsform_base_url": "https://your-site.whatsform.in",
  "whatsform_api_key": "...",
  "whatsform_api_secret": "...",
  "whatsform_dry_run": true   # log instead of calling, until the above are real

Not used by the WhatsApp Campaign feature below `send_wasender` — that goes
through WasenderAPI directly and has its own (no longer dry-run-able)
sending logic. This is a separate, currently-unused direct-send path.
"""
import json
import mimetypes

import frappe
import requests

SEND_TEXT_PATH = "/api/method/frappe_whatsapp.whatsapp_chat.send_outgoing_text_message"
SEND_TEMPLATE_PATH = "/api/method/frappe_whatsapp.whatsapp_chat.send_template_to_multiple_numbers"


class WhatsformNotConfigured(Exception):
    pass


def classify_attachment(file_url_or_path: str) -> str:
    """"image" / "video" / "document" from a file's name alone — used both to
    pick the right WasenderAPI payload field and to label an attachment in
    the desk UI. Anything not recognized as image/video falls back to
    "document" (WasenderAPI's own catch-all: "most common document types are
    supported (PDF, DOCX, XLSX, etc.)")."""
    mime, _ = mimetypes.guess_type(file_url_or_path or "")
    if mime and mime.startswith("image/"):
        return "image"
    if mime and mime.startswith("video/"):
        return "video"
    return "document"


def _config():
    base_url = frappe.conf.get("whatsform_base_url")
    api_key = frappe.conf.get("whatsform_api_key")
    api_secret = frappe.conf.get("whatsform_api_secret")
    dry_run = frappe.conf.get("whatsform_dry_run", True)
    return base_url, api_key, api_secret, dry_run


def _post(path: str, payload: dict) -> dict:
    base_url, api_key, api_secret, dry_run = _config()

    if dry_run or not base_url or not api_key or not api_secret:
        frappe.logger("wedding_plan.whatsapp").info(
            f"[DRY RUN] whatsform.in {path} <- {json.dumps(payload, default=str)}"
        )
        return {"dry_run": True, "path": path, "payload": payload}

    resp = requests.post(
        base_url.rstrip("/") + path,
        json=payload,
        headers={"Authorization": f"token {api_key}:{api_secret}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def send_text(mobile_no: str, message: str) -> dict:
    return _post(SEND_TEXT_PATH, {"mobile_no": mobile_no, "message": message})


def send_template(template: str, mobile_numbers: list, components: list | None = None, header_type: str = "") -> dict:
    return _post(SEND_TEMPLATE_PATH, {
        "template": template,
        "mobile_numbers": mobile_numbers,
        "components": components or [],
        "header_type": header_type,
        "media_type": "",
        "media_url": "",
        "filename": "",
        "filedata": "",
        "media_name": "",
    })


def send_wasender(account, to_phone: str, message: str | None, attachment_path: str | None = None) -> dict:
    """Send a text, or a text with an image/video/document attached, through
    WasenderAPI.

    The key is read server-side from a Frappe Password field. It is never
    accepted from the browser, stored in a campaign, or written to a log.
    """
    api_key = account.get_password("api_key")
    if not api_key:
        raise WhatsformNotConfigured("WhatsApp sender account has no API key")

    payload = {"to": to_phone, **({"text": message} if message else {})}

    if attachment_path:
        with open(attachment_path, "rb") as attachment_file:
            media_response = requests.post(
                frappe.conf.get("wasender_upload_url", "https://wasenderapi.com/api/upload"),
                data=attachment_file,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": mimetypes.guess_type(attachment_path)[0] or "application/octet-stream",
                },
                timeout=60,
            )
        media_response.raise_for_status()
        media_url = media_response.json().get("publicUrl")
        if not media_url:
            raise WhatsformNotConfigured("WasenderAPI did not return a public attachment URL")

        kind = classify_attachment(attachment_path)
        if kind == "image":
            payload["imageUrl"] = media_url
        elif kind == "video":
            payload["videoUrl"] = media_url
        else:
            payload["documentUrl"] = media_url
            payload["fileName"] = attachment_path.rsplit("/", 1)[-1]

    response = requests.post(
        frappe.conf.get("wasender_api_url", "https://wasenderapi.com/api/send-message"),
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

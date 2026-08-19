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
"""
import json

import frappe
import requests

SEND_TEXT_PATH = "/api/method/frappe_whatsapp.whatsapp_chat.send_outgoing_text_message"
SEND_TEMPLATE_PATH = "/api/method/frappe_whatsapp.whatsapp_chat.send_template_to_multiple_numbers"


class WhatsformNotConfigured(Exception):
    pass


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


def send_template(template: str, mobile_numbers: list, components: list = None, header_type: str = "") -> dict:
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

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
import os
import re

import frappe
import requests

SEND_TEXT_PATH = "/api/method/frappe_whatsapp.whatsapp_chat.send_outgoing_text_message"
SEND_TEMPLATE_PATH = "/api/method/frappe_whatsapp.whatsapp_chat.send_template_to_multiple_numbers"

# A WasenderAPI error body is normally a few hundred bytes of JSON, but a proxy
# in front of it can answer with a full HTML page. Cap what reaches the Error
# Log so one bad gateway can't bloat the table; the head of the body is where
# the diagnosis is anyway.
WASENDER_BODY_LOG_LIMIT = 4000
# What the campaign shows next to a family's name. The recipient row's `error`
# field holds 500 chars, so stay comfortably inside it.
WASENDER_ERROR_MESSAGE_LIMIT = 400

# Belt-and-braces: we never put a key into a log ourselves, but an upstream
# error body can echo the request that caused it (some gateways include the
# Authorization header in their 4xx payload). Anything token-shaped is scrubbed
# on its way to the Error Log. Two shapes to catch: a labelled field
# ("api_key": "...", Authorization: ...)
# and a bare auth scheme (Bearer <token>) with no label in front of it. The
# labelled branch also swallows an inner scheme, so {"Authorization": "Bearer
# sk_live_x"} redacts the token and not just the word "Bearer".
_SECRET_PATTERN = re.compile(
    r"(?i)(?:"
    r"(?P<key>\b(?:authorization|api[_-]?key|api[_-]?secret|apikey|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|token|password|passwd|pwd|secret|session[_-]?id|sid|cookie)[\"']?\s*[:=]\s*[\"']?"
    r"(?:bearer\s+|basic\s+|token\s+)?)"
    r"|(?P<scheme>\b(?:bearer|basic)\s+)"
    r")(?P<value>[^\s\"',;}\]]+)"
)


class WhatsformNotConfigured(Exception):
    pass


class WasenderError(Exception):
    """A non-2xx reply from WasenderAPI, carrying what WasenderAPI actually said.

    `str(...)` is deliberately the one-line reason worth showing a planner
    ("WasenderAPI HTTP 422: The to field must be a valid number."), so a caller
    that knows nothing about this class still reports something useful.
    """

    def __init__(self, message, status_code=None, endpoint=None, response_body=None, parsed=None):
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.response_body = response_body
        self.parsed = parsed


class WasenderSessionError(WasenderError):
    """The sender account's WhatsApp session is not connected.

    WasenderAPI reports this with an HTTP 200 and nothing but a `message`, so
    it has to be read out of the body. Every later send on that account fails
    the same way until someone reconnects it, which is why the campaign
    pauses on this instead of carrying on through the guest list.
    """


# How WasenderAPI words a disconnected session ("Your Whatsapp Session is not
# connected please connect your session first.").
_SESSION_DOWN_PATTERN = re.compile(r"(?i)\bsession\b.*\b(?:not\s+connected|disconnected|expired|logged\s+out)\b")


def _redact(text: str) -> str:
    def mask(match):
        return (match.group("key") or match.group("scheme") or "") + "***redacted***"

    return _SECRET_PATTERN.sub(mask, text or "")


def _truncate(text: str, limit: int = WASENDER_BODY_LOG_LIMIT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… [truncated, {len(text)} chars total]"


def _flatten_errors(errors) -> str:
    """Render WasenderAPI's `errors` shapes as one line.

    Laravel-style validation comes back as {"to": ["The to field is required."]};
    other endpoints send a plain list. Both need to survive into a 500-char
    field, so they collapse to "field: detail | field: detail".
    """
    if isinstance(errors, dict):
        parts = []
        for field, detail in errors.items():
            if isinstance(detail, (list, tuple)):
                detail = "; ".join(str(item) for item in detail)
            parts.append(f"{field}: {detail}")
        return " | ".join(parts)
    if isinstance(errors, (list, tuple)):
        return " | ".join(str(item) for item in errors)
    return str(errors).strip() if errors else ""


def _wasender_error_message(parsed, body: str) -> str:
    """The most specific thing WasenderAPI said about the rejection.

    Its bodies vary by failure mode — `message` for business rejections,
    `error`/`detail` for auth and routing, `errors` for field validation — and
    more than one can be present, so all of them are kept, de-duplicated
    (`error` frequently just repeats `message`). Anything not JSON falls back
    to the raw body.
    """
    candidates = []
    if isinstance(parsed, dict):
        for key in ("message", "error", "detail", "description", "reason"):
            value = parsed.get(key)
            if isinstance(value, (dict, list, tuple)):
                value = _flatten_errors(value)
            if value is not None and str(value).strip():
                candidates.append(str(value).strip())
        validation = _flatten_errors(parsed.get("errors"))
        if validation:
            candidates.append(validation)
    elif isinstance(parsed, (list, tuple)) and parsed:
        candidates.append(_flatten_errors(parsed))
    elif parsed not in (None, "") and not isinstance(parsed, (dict, list, tuple)):
        candidates.append(str(parsed).strip())

    seen, unique = set(), []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)

    return " | ".join(unique) if unique else (body or "").strip()


def _safe_response_headers(response) -> dict:
    """Only the headers that explain a rejection — never anything echoed back
    from our own request."""
    wanted = ("content-type", "retry-after", "x-request-id", "x-ratelimit-remaining", "x-ratelimit-reset")
    return {key: value for key, value in response.headers.items() if key.lower() in wanted}


def _check_wasender_response(response, endpoint: str, reference: str, request_info: dict) -> None:
    """Log and raise what WasenderAPI actually returned, on a non-2xx reply.

    Runs immediately before the existing `raise_for_status()`: on a successful
    call it inspects `response.ok` and returns, touching nothing. On a failure
    it records the status, the (redacted, truncated) body, the parsed JSON, the
    endpoint, the recipient and the safe request shape in the Error Log, then
    raises `WasenderError` chained off the original `requests.HTTPError` so the
    traceback still shows where the call was made.
    """
    if response.ok:
        return

    body = response.text or ""
    try:
        parsed = response.json()
    except ValueError:
        parsed = None

    detail = _redact(_wasender_error_message(parsed, body)) or response.reason or "no error detail in response body"
    summary = _truncate(f"WasenderAPI HTTP {response.status_code}: {detail}", WASENDER_ERROR_MESSAGE_LIMIT)

    try:
        response.raise_for_status()
    except requests.HTTPError as http_error:
        log = [
            f"Endpoint: {endpoint}",
            f"HTTP status: {response.status_code} {response.reason or ''}".strip(),
            f"Reference (recipient): {reference}",
            f"Request (no credentials): {json.dumps(request_info, default=str)}",
            "Request headers sent: Authorization (redacted), Content-Type",
            f"Response headers: {json.dumps(_safe_response_headers(response), default=str)}",
            f"Parsed JSON: {_truncate(_redact(json.dumps(parsed, default=str, indent=2))) if parsed is not None else '<body was not JSON>'}",
            f"Response body: {_truncate(_redact(body)) or '<empty>'}",
            f"Extracted error: {detail}",
            "",
            _redact(frappe.get_traceback()),
        ]
        frappe.log_error(
            title=f"WasenderAPI HTTP {response.status_code}: {endpoint.rsplit('/', 1)[-1]}",
            message="\n".join(log),
        )
        raise WasenderError(
            summary,
            status_code=response.status_code,
            endpoint=endpoint,
            response_body=_truncate(_redact(body)),
            parsed=parsed,
        ) from http_error


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
        upload_url = frappe.conf.get("wasender_upload_url", "https://wasenderapi.com/api/upload")
        content_type = mimetypes.guess_type(attachment_path)[0] or "application/octet-stream"
        with open(attachment_path, "rb") as attachment_file:
            media_response = requests.post(
                upload_url,
                data=attachment_file,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": content_type,
                },
                timeout=60,
            )
        _check_wasender_response(
            media_response,
            endpoint=upload_url,
            reference=to_phone,
            request_info={
                "file_name": attachment_path.rsplit("/", 1)[-1],
                "content_type": content_type,
                "size_bytes": os.path.getsize(attachment_path) if os.path.exists(attachment_path) else None,
            },
        )
        media_response.raise_for_status()
        media_url = media_response.json().get("publicUrl")
        if not media_url:
            # A 2xx with no URL in it — show what came back instead, or the
            # next failure is "did not return a public attachment URL" again
            # with nothing to go on.
            raise WhatsformNotConfigured(
                "WasenderAPI did not return a public attachment URL. "
                f"Upload response: {_truncate(_redact(media_response.text), WASENDER_ERROR_MESSAGE_LIMIT)}"
            )

        kind = classify_attachment(attachment_path)
        if kind == "image":
            payload["imageUrl"] = media_url
        elif kind == "video":
            payload["videoUrl"] = media_url
        else:
            payload["documentUrl"] = media_url
            payload["fileName"] = attachment_path.rsplit("/", 1)[-1]

    send_url = frappe.conf.get("wasender_api_url", "https://wasenderapi.com/api/send-message")
    response = requests.post(
        send_url,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    _check_wasender_response(
        response,
        endpoint=send_url,
        reference=to_phone,
        request_info={
            "to": to_phone,
            "payload_fields": sorted(payload),
            "has_attachment": bool(attachment_path),
            "attachment_kind": classify_attachment(attachment_path) if attachment_path else None,
            "message_length": len(message or ""),
        },
    )
    response.raise_for_status()
    result = response.json()
    _check_wasender_accepted(result, endpoint=send_url, account=account)
    return result


def _check_wasender_accepted(result, endpoint: str, account) -> None:
    """Raise on a 2xx reply that still did not send the message.

    A disconnected session comes back as HTTP 200 with only a `message`, which
    used to be recorded as Sent with that message stored as the provider id.
    """
    if not isinstance(result, dict):
        return
    detail = _redact(_wasender_error_message(result, ""))
    if _SESSION_DOWN_PATTERN.search(detail):
        raise WasenderSessionError(
            _truncate(f"WhatsApp session for sender account {account.name} is not connected: {detail}", WASENDER_ERROR_MESSAGE_LIMIT),
            status_code=200,
            endpoint=endpoint,
            parsed=result,
        )
    if result.get("success") is False:
        raise WasenderError(
            _truncate(f"WasenderAPI rejected the message: {detail or 'no reason given'}", WASENDER_ERROR_MESSAGE_LIMIT),
            status_code=200,
            endpoint=endpoint,
            parsed=result,
        )

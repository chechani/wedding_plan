"""
Re-exports so the frontend's REST calls stay short:
  /api/method/wedding_plan.api.register
  /api/method/wedding_plan.api.login
  /api/method/wedding_plan.api.me
  /api/method/wedding_plan.api.create_wedding_and_join
  /api/method/wedding_plan.api.add_wedding_member
  /api/method/wedding_plan.api.dashboard_stats
  /api/method/wedding_plan.api.import_excel
  /api/method/wedding_plan.api.download_import_template
  /api/method/wedding_plan.api.whatsapp_send_text
  /api/method/wedding_plan.api.whatsapp_send_template
Every other read/write (guests, rooms, run sheet, teams, vendors, meal
sessions, convoy legs, ...) goes through Frappe's standard REST API —
GET/POST/PUT/DELETE /api/resource/<DocType>[/<name>] — which is already
tenant-scoped by wedding_plan/permissions.py, so no bespoke CRUD endpoint is
needed for those.
"""
from wedding_plan.api.auth import register, login, me  # noqa: F401
from wedding_plan.api.weddings import create_wedding_and_join, add_wedding_member, dashboard_stats  # noqa: F401
from wedding_plan.api.imports import import_excel, download_import_template  # noqa: F401
from wedding_plan.api.whatsapp import whatsapp_send_text, whatsapp_send_template  # noqa: F401

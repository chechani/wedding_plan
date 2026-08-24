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
  /api/method/wedding_plan.api.get_invitation_channels
  /api/method/wedding_plan.api.get_invitation_matrix
  /api/method/wedding_plan.api.invitation_dashboard_stats
  /api/method/wedding_plan.api.update_invitation_task
  /api/method/wedding_plan.api.bulk_update_invitation_tasks
  /api/method/wedding_plan.api.ensure_invitation_tasks
  /api/method/wedding_plan.api.task_board
  /api/method/wedding_plan.api.task_dashboard_stats
  /api/method/wedding_plan.api.bulk_update_task_status
  /api/method/wedding_plan.api.function_headcount_stats
  /api/method/wedding_plan.api.provision_guest_portal_user
  /api/method/wedding_plan.api.guest_login
  /api/method/wedding_plan.api.get_my_profile
  /api/method/wedding_plan.api.get_my_functions
  /api/method/wedding_plan.api.update_my_contact_info
  /api/method/wedding_plan.api.update_my_function_status
  /api/method/wedding_plan.api.upload_my_document
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
from wedding_plan.api.invitations import (  # noqa: F401
	get_invitation_channels,
	get_invitation_matrix,
	invitation_dashboard_stats,
	update_invitation_task,
	bulk_update_invitation_tasks,
	ensure_invitation_tasks,
)
from wedding_plan.api.tasks import (  # noqa: F401
	task_board,
	task_dashboard_stats,
	bulk_update_task_status,
)
from wedding_plan.api.guests import function_headcount_stats  # noqa: F401
from wedding_plan.api.guest_portal import (  # noqa: F401
	provision_guest_portal_user,
	guest_login,
	get_my_profile,
	get_my_functions,
	update_my_contact_info,
	update_my_function_status,
	upload_my_document,
)

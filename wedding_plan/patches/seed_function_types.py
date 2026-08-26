"""One-time seed of WD Function Type — a shared reference list (not
wedding-scoped) of standard Indian wedding event types, so the Function
Type picker on WD Function isn't empty on a fresh install. Idempotent:
only inserts names that don't already exist, so re-running (or a planner
adding their own custom types afterward) is safe.
"""
import frappe

FUNCTION_TYPES = [
	"Roka / Engagement",
	"Tilak",
	"Haldi",
	"Mehendi",
	"Sangeet",
	"Ring Ceremony",
	"Cocktail Night",
	"Sundowner",
	"Ganesh Puja / Griha Shanti",
	"Mayra / Bhaat",
	"Baraat",
	"Milni",
	"Varmala / Jaimala",
	"Phera / Vivaah",
	"Reception",
	"Bidai",
	"Griha Pravesh",
	"Satyanarayan Puja",
]


def execute():
	for name in FUNCTION_TYPES:
		if not frappe.db.exists("WD Function Type", name):
			frappe.get_doc({"doctype": "WD Function Type", "function_type_name": name}).insert(ignore_permissions=True)
	frappe.db.commit()

"""
Seeds the Task Field Library master/lookup data: the 19 Task categories
(the spec's own section 1 says "eighteen buckets" but section 3's table
lists 14 kept + 5 added = 19 — the table is authoritative), their
sub-types (each optionally mapped to the detail doctype WD Task.validate()
auto-creates when that sub-type is picked — see wd_task.py
_ensure_subtype_detail), the section-5 master option lists, and the
checklist template items transcribed from every "Checklist" block in the
spec. Run once, idempotently (get-or-create throughout, safe to re-run):

    bench --site <site> execute wedding_plan.setup.seed_task_masters.run
"""
import frappe


def _get_or_create(doctype, name_field, name_value, extra=None):
	existing = frappe.db.exists(doctype, name_value)
	if existing:
		return existing
	doc = frappe.get_doc({"doctype": doctype, name_field: name_value, **(extra or {})})
	doc.insert(ignore_permissions=True)
	return doc.name


def _seed_master_list(doctype, name_field, values):
	for v in values:
		_get_or_create(doctype, name_field, v)


MASTER_LISTS = {
	("WD Vendor Type", "vendor_type_name"): [
		"Decorator", "Sound", "Light", "Pyro/SFX", "LED/Video", "Caterer", "Pandit",
		"Photography", "Videography", "Choreographer", "Anchor", "Makeup Artist",
		"Mehendi Artist", "Transport", "Generator", "Tent/Furniture", "Florist", "Other",
	],
	("WD Task Status", "status_name"): [
		"Not Started", "In Progress", "Blocked", "Awaiting Vendor", "Awaiting Approval", "Done", "Cancelled",
	],
	("WD Service Style", "service_style_name"): [
		"Buffet", "Sit-down thali", "Stall format", "Plated", "Live counters only",
	],
	("WD Meal Session Type", "session_type_name"): [
		"Breakfast", "Lunch", "High tea", "Dinner", "Late-night", "Midnight snack",
	],
	("WD Crockery Type", "crockery_type_name"): [
		"Disposable", "Melamine", "Steel thali", "Bone china", "Leaf plate", "Copper",
	],
	("WD Flower Type", "flower_type_name"): [
		"Genda (marigold)", "Rose", "Orchid", "Carnation", "Mogra / jasmine",
		"Rajnigandha", "Lily", "Chrysanthemum", "Anthurium", "Gladiolus",
	],
	("WD Sound Element", "sound_element_name"): [
		"Line array tops", "Dual bass", "Monitors", "Side fills", "Cordless mic", "Wired mic",
		"Lapel / collar mic", "Console", "Mixer", "DI box", "Jack to jack", "CDJ player",
		"Laptop", "Extension board", "Operator",
	],
	("WD Light Element", "light_element_name"): [
		"LED PAR", "Warm white on DMX", "Sharpie", "Wash", "Blinder", "Strobe", "Follow spot",
		"Moving head", "Smoke / haze machine", "Light console", "Box truss", "V truss",
	],
	("WD SFX Type", "sfx_type_name"): [
		"Cold pyro", "CO2 jet", "Confetti blaster", "Flower shower", "Sparkler", "Dry ice",
		"Smoke", "Bubble machine",
	],
	("WD Permit Type", "permit_type_name"): [
		"Loudspeaker beyond 10 PM", "Liquor", "Fire NOC", "Road & traffic for baraat",
		"Drone (DGCA)", "Music licence (PPL)", "Music licence (IPRS)", "Music licence (Novex)",
		"Municipal", "FSSAI of caterer", "Generator",
	],
	("WD Hamper Tier", "hamper_tier_name"): [
		"VIP", "Premium", "Standard", "Kids", "Vendor & staff",
	],
	("WD Payment Mode", "payment_mode_name"): [
		"Cash", "UPI", "NEFT", "RTGS", "Cheque", "Card",
	],
	("WD Unit", "unit_name"): [
		"pax", "plates", "nights", "rooms", "kg", "stems", "pieces", "ft", "ft x ft", "sq ft",
		"running ft", "nos", "kVA", "kW", "litres", "hours", "minutes", "per kg", "per stem",
	],
}

# (category, [subtype names], display order matches spec section 4 letters).
# Subtypes with no detail doctype either aren't covered by the spec's field
# tables (Booking & Contract / Advance & Payment / Catering & F&B — the PDF's
# own TOC bookmarks for A/B/C are broken, no field tables were supplied) or
# are covered by extending an existing doctype instead of a task-linked
# detail sheet (Room Block, Pickup/Drop, Crate, Run Sheet Item, Risk — see
# the plan's "Extend in place" table) — those existing panels stay
# independent of a specific task, same as they work today.
CATEGORIES = {
	"Booking & Contract": [],
	"Advance & Payment": [],
	"Catering & F&B": [],
	"Décor & Styling": [
		("Function décor element sheet", "WD Task Decor Detail"),
		("Floral order", "WD Task Floral Order"),
		("Mandap & ritual décor", "WD Task Mandap Decor"),
	],
	"Logistics & Setup": [
		("Sound setup", "WD Task Sound Detail"),
		("Lighting setup", "WD Task Lighting Detail"),
		("LED & video", "WD Task LED Video Detail"),
		("Pyro & SFX", "WD Task Pyro SFX Detail"),
		("Power & generator", "WD Task Power Generator Detail"),
		("Stage, truss & load-in", "WD Task Stage Truss Loadin"),
	],
	"Ritual & Puja Arrangements": [
		("Ritual / muhurat", "WD Task Ritual Muhurat Detail"),
		("Samagri checklist", ""),
	],
	"Attire & Grooming": [
		("Outfit", "WD Task Outfit Detail"),
		("Makeup, hair & mehendi", "WD Task Makeup Hair Mehendi Detail"),
	],
	"Entertainment & Artists": [
		("Anchor brief", "WD Anchor Brief"),
		("Choreography", "WD Task Choreography Detail"),
	],
	"Photography & Content": [
		("Coverage plan", "WD Task Coverage Plan Detail"),
	],
	"Travel & Accommodation": [
		("Room block & allotment", ""),
		("Pickup / drop", ""),
	],
	"Guest & Vendor Communication": [
		("Broadcast / briefing", "WD Task Broadcast Detail"),
	],
	"Gifting, Shagun & Hampers": [
		("Hamper tier / shagun counter", "WD Task Hamper Detail"),
	],
	"Inventory & Stores": [
		("Crate / material movement", ""),
	],
	"Day-of Coordination": [
		("Run sheet item", ""),
		("Cue sheet", "WD Task Cue Sheet Item"),
	],
	"Compliance & Permits": [
		("Permit", "WD Task Permit Detail"),
	],
	"Documentation": [
		("Document / registration", "WD Task Document Detail"),
	],
	"Finance & Settlement": [
		("Final settlement", "WD Task Final Settlement Detail"),
	],
	"Contingency & Backup": [
		("Risk & backup plan", ""),
	],
	"Other": [],
}

# Checklist template items, transcribed verbatim from each spec sub-type's
# "Checklist" block (section 4, D through R). Keyed by subtype name — must
# match CATEGORIES above exactly.
CHECKLISTS = {
	"Function décor element sheet": [
		"Reference images approved in writing by the family, numbered and attached",
		"Fabric ironed, material neat and clean — write it into the contract as your sheet already does",
		"Stage load tested before anyone stands on it",
		"All console tables masked in black",
		"Cables taped down on every guest path",
		"Set complete and photographed one hour before guests arrive",
		"Strike time agreed and who removes what",
		"Rented versus owned marked on every item",
		"Decorator's detailed action plan received for the largest function",
	],
	"Floral order": [
		"Order placed at least 10 days ahead for anything not local",
		"Mandi rate checked independently the week before",
		"Delivery scheduled before 6 AM on the function day",
		"Water, cold storage and shade arranged on site",
		"Varmala design approved by the couple in a photo",
		"Petal quantity fixed for every shower moment",
		"Backup flower and colour agreed in writing",
		"Wilting plan for outdoor daytime functions",
	],
	"Mandap & ritual décor": [
		"Mandap size confirmed against the guest seating plan, not just the stage",
		"Havan ventilation and fire extinguisher within reach",
		"Fresh white cover, not reused",
		"Pandit ji shown the mandap layout in advance and asked to approve it",
		"Seating for elders with backs, not only floor cushions",
		"Bride's entry aisle walked once before the function",
		"Mandap lit for cameras without strobes",
	],
	"Sound setup": [
		"Tech rider collected from every artist and forwarded to the sound vendor in writing",
		"Sound check completed before the first guest arrives",
		"Pandit ji's lapel tested at the mandap, in position",
		"Feedback checked with the hall empty and again when filling",
		"One spare cordless mic and spare batteries on the console",
		"Operator briefed on the cue sheet, not just handed a playlist",
		"Backup laptop carrying the identical playlist",
		"After-10 PM plan agreed: ambient level or written permission",
		"Music licence position checked for live and recorded music",
	],
	"Lighting setup": [
		"Choreographer's list captured verbatim and separately from the base rig",
		"Truss size confirmed with the decorator after the stage design is frozen",
		"Follow spot operator briefed on entry cues by name",
		"Smoke tested against venue fire alarms before the function",
		"Light levels checked on camera, not by eye — photographers see differently",
		"No strobes during phera or any ritual",
	],
	"LED & video": [
		"Content delivered and test-played two days before",
		"Aspect ratio matched to the actual panel, not assumed",
		"Live feed cabled and tested where a camera view is essential",
		"Name and family slides spell-checked by a family member",
		"Backup copy on a second drive at the console",
	],
	"Pyro & SFX": [
		"Ceiling height and smoke alarms checked for every indoor effect",
		"Safety distance marked physically on the floor",
		"Trained technician present, not a helper",
		"Two extinguishers within reach of every pyro position",
		"Wind assessed 15 minutes before an outdoor cue",
		"Go/no-go authority named — one person, and their word is final",
		"Guests in synthetic and flowing fabrics kept back from the line",
	],
	"Power & generator": [
		"Total load added up across all vendors, not estimated",
		"DG tested under load, not just started",
		"Fuel topped up before every evening function",
		"Earthing checked, especially for outdoor lawn setups",
		"Technician physically present, not on call",
		"Console and LED on UPS so a flicker does not restart the show",
	],
	"Stage, truss & load-in": [
		"Load-in order sequenced so décor finishes before truss and sound",
		"Service lift blocking window communicated to every other vendor",
		"Gate passes issued for anything leaving",
		"Stage walked and jumped on before performers use it",
		"Strike time agreed and labour booked for it too",
	],
	"Ritual / muhurat": [
		"Muhurat confirmed with the pandit in writing, with a start and an end",
		"Samagri responsibility settled — family, pandit or decorator",
		"Samagri bought a week ahead, not the morning of",
		"Couple briefed on the ritual order so they know what comes next",
		"Elder seating with back support arranged at the mandap",
		"Pandit ji's lapel mic tested in position",
		"Everything upstream timed backwards from the muhurat",
	],
	"Outfit": [
		"Two bridal trials completed, second one with jewellery and footwear",
		"Every outfit packed in a labelled bag by function and wearer",
		"Bags moved to the venue ahead of the wearer, not with them",
		"Steaming done at the venue, not at home three days early",
		"Safas counted against the actual baraat headcount plus 10%",
		"Emergency kit: safety pins, double-sided tape, thread, scissors, stain wipes",
		"Changing room allotted and locked at each venue",
	],
	"Makeup, hair & mehendi": [
		"Bridal makeup trial done with the actual outfit and jewellery",
		"Call times worked backwards from the ritual, with a 45-minute buffer",
		"Family makeup queue sequenced and posted so nobody waits blind",
		"Mehendi artist count set against hands, plus two extra",
		"Bride's mehendi scheduled separately and earlier",
		"Touch-up artist available at the bride's shadow's call",
	],
	"Anchor brief": [
		"Running order shared 48 hours ahead and rehearsed",
		"Name list with pronunciations checked by a family member",
		"Anchor briefed on what NOT to mention",
		"Roving mic tested across the full ground for a carnival-style event",
		"Anchor and choreographer aligned on entry cues",
		"Backup anchor identified for a multi-day wedding",
	],
	"Choreography": [
		"Every act timed in rehearsal, not estimated",
		"Total running time agreed with a hard stop",
		"Music files collected on two drives, named in order",
		"Stage size frozen before the decorator builds",
		"Choreographer's light list handed to the lighting vendor as a separate sheet",
		"Rehearsal done with actual sound and lights at least once",
	],
	"Coverage plan": [
		"Second crew booked for every day where two venues are live at once",
		"Family photo list written by name and given to one caller with a mic",
		"Backed up to two drives every night before anyone sleeps",
		"Drone permission checked, especially near restricted areas",
		"Delivery dates written into the contract with a penalty",
		"Teaser or reel deadline agreed separately from the full delivery",
	],
	"Broadcast / briefing": [
		"No more than five broadcasts to guests in total, or they mute the group",
		"Dress code and weather warning included for outdoor winter functions",
		"Map links tested from an actual phone",
		"Vendor briefings done by call and confirmed in writing",
		"Elders and VIPs called personally, never broadcast to",
	],
	"Hamper tier / shagun counter": [
		"No perishables in a hamper that sits in a warm room for two days",
		"Nothing liquid for guests flying back with cabin baggage",
		"10% buffer packed on every tier",
		"Every envelope logged with the giver's name before it leaves the counter",
		"Two people on the counter at all times",
		"Reconciled and handed to finance after every function, not at the end",
		"Jewellery and cash move under the two-person rule, one carries and one logs",
	],
	"Cue sheet": [
		"Cue sheet written and shared with every operator before the function",
		"Standby calls agreed — nobody fires on a guess",
		"Anchor's exact trigger line written down, not described",
		"Every cue has a fallback that does not stop the show",
		"Walked through once with all operators present",
	],
	"Permit": [
		"Loudspeaker position confirmed against the 10 PM restriction, in writing",
		"Music licence position checked for both recorded and live performance",
		"Fire NOC and extinguishers in place where pyro is planned",
		"Road permission taken where the baraat uses a public road",
		"Caterer's FSSAI licence copy collected",
		"Physical copies of every permit at each venue, with a named holder",
		"Applied at least three weeks ahead — none of these are same-day",
	],
	"Document / registration": [
		"Registration route decided early — Hindu Marriage Act or Special Marriage Act",
		"Notice period accounted for if applicable",
		"Witnesses confirmed with ID copies before the date",
		"Wedding photographs of the ceremony kept aside for the application",
		"All vendor contracts and GST documents filed in one folder",
		"Originals held by one named person, scanned copies shared",
	],
	"Final settlement": [
		"Every plate slip collected and totalled before the caterer's final bill is opened",
		"Extras matched to an approval with a name against each one",
		"Overtime calculated against the contract rate, not negotiated fresh",
		"Rented items reconciled before the final payment is released",
		"Retention held until returns and deliverables are complete",
		"No settlement conversation held in front of guests",
	],
}


def run():
	for (doctype, name_field), values in MASTER_LISTS.items():
		_seed_master_list(doctype, name_field, values)

	for category, subtypes in CATEGORIES.items():
		_get_or_create("WD Task Category", "category_name", category)
		for subtype_name, detail_doctype in subtypes:
			subtype_id = frappe.db.exists("WD Task Subtype", {"subtype_name": subtype_name, "category": category})
			if not subtype_id:
				subtype_doc = frappe.get_doc({
					"doctype": "WD Task Subtype",
					"subtype_name": subtype_name,
					"category": category,
					"detail_doctype": detail_doctype,
				})
				subtype_doc.insert(ignore_permissions=True)
				subtype_id = subtype_doc.name

			for i, item in enumerate(CHECKLISTS.get(subtype_name, [])):
				if not frappe.db.exists("WD Task Checklist Template Item", {"subtype": subtype_id, "item": item}):
					frappe.get_doc({
						"doctype": "WD Task Checklist Template Item",
						"subtype": subtype_id,
						"item": item,
						"sort_order": i,
					}).insert(ignore_permissions=True)

	frappe.db.commit()

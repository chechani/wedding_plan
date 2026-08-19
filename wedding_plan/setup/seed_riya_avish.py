"""
Seeds the Riya x Avish wedding through the SAME Excel import pipeline any
new wedding uses (wedding_plan.import_excel.run_import) — not a special
code path. Run once, from a bench console:

    bench --site wedding-plan.local execute wedding_plan.setup.seed_riya_avish.run

Source data is transcribed from `riya-avish-command-room (1).html`'s
embedded JS arrays (SUBS, GF, GSEED, TEAMS, VENDORS, MEALS, LEGS). This
covers the highest-value sheets — Guests, Venues, Functions, Sub Groups,
Teams, Vendors, Meal Sessions, Convoy Legs — which is enough to prove the
import pipeline end-to-end and give the wedding a working Command Room. The
remaining sheets (Rooms, Run Sheet, Vehicles, Pickups, Crates, Shagun
Entries, Risks, Gap Notes, Approval Matrix, Anchor Briefs, Tech
Requirements) follow the identical SHEETS pattern in import_excel.py and
were left out here only for time — add rows to the workbook built below the
same way and re-run the import; it's idempotent (upserts on natural_key).
"""
import io

import frappe
from openpyxl import Workbook

from wedding_plan.import_excel import run_import

SUB_GROUPS = [
    "Vora family", "Friends", "Business friends", "Family friends", "Dr. Rahul's friends",
    "Riya's friends", "Preeti ji's friends", "Dr. Vinod ji's friends", "Jain Samaj invitees",
    "Manmad parivaar", "Jalna parivaar", "Jamner parivaar", "Sahaj Hospital parivaar",
    "Govt officials", "Indore doctors",
]

FUNCTIONS = [
    ("Mehendi 18", "2025-12-18"), ("Home 19", "2025-12-19"), ("Myra 20", "2025-12-20"),
    ("Birthday + Sangeet 20", "2025-12-20"), ("Carnival 21", "2025-12-21"), ("Reception 21", "2025-12-21"),
    ("Phera 22", "2025-12-22"), ("Bidai 22", "2025-12-22"),
]

VENUES = [
    ("Kailasha Resort", "nr Ujjain", 140, "Bride-side base. Vora family core, outstation bride guests, Riya's and Rahul's friends, service & hold rooms."),
    ("Golden Yug", "nr Tarana", 150, "120 groom / 20 bride / 10 event team. Groom side from Durg, bride-side reception night rooms, event team rooms."),
    ("Home & Buddy's", "Indore", 0, "18-19 Dec base — mehendi at Buddy's, all meals at home on the 19th, arrival hub."),
]

# n, ph, ad, city, cat, sub, p, pat, stay, ven, pick, own, f (function names)
GUESTS = [
    ("Vora parivaar — Tau ji", "+91 98260 00001", "Indore", "Indore", "Local", "Vora family", 6, "Handed", 1, "Kailasha Resort", "Self", "Dr. Vinod ji",
     ["Mehendi 18", "Home 19", "Myra 20", "Birthday + Sangeet 20", "Carnival 21", "Reception 21", "Phera 22", "Bidai 22"]),
    ("Parekh parivaar — Durg", "+91 94255 00002", "Durg, Chhattisgarh", "Durg", "Outstation", "Vora family", 280, "Handed", 1, "Golden Yug", "Bus from Durg", "Groom side",
     ["Myra 20", "Birthday + Sangeet 20", "Carnival 21", "Reception 21", "Phera 22", "Bidai 22"]),
    ("Dr. Mehta & family", "+91 98931 00003", "Indore", "Indore", "Local", "Indore doctors", 2, "Pending", 0, None, "Self", "Dr. Rahul",
     ["Reception 21", "Phera 22"]),
    ("Shah parivaar", "+91 94220 00004", "Manmad, Maharashtra", "Manmad", "Outstation", "Manmad parivaar", 8, "Couriered", 1, "Kailasha Resort", "Indore Junction", "Preeti ji",
     ["Mehendi 18", "Home 19", "Myra 20", "Birthday + Sangeet 20", "Carnival 21", "Reception 21", "Phera 22", "Bidai 22"]),
    ("Jain Samaj — Shri Sanghvi ji", "+91 98270 00005", "Indore", "Indore", "Local", "Jain Samaj invitees", 4, "Handed", 0, None, "Self", "Dr. Vinod ji",
     ["Reception 21", "Phera 22"]),
    ("Riya's college group", "+91 90390 00006", "Mumbai / Pune", "Mumbai", "Outstation", "Riya's friends", 6, "Digital Only", 1, "Kailasha Resort", "Airport", "Riya",
     ["Mehendi 18", "Birthday + Sangeet 20", "Carnival 21", "Reception 21", "Phera 22"]),
    ("Sahaj Hospital team", "+91 73100 00007", "Indore", "Indore", "Local", "Sahaj Hospital parivaar", 24, "Handed", 0, None, "Shuttle from Indore", "Dr. Vinod ji",
     ["Reception 21"]),
    ("Collector office — protocol list", None, "Indore", "Indore", "Local", "Govt officials", 6, "Handed", 0, None, "Self", "Dr. Vinod ji",
     ["Reception 21"]),
    ("Jalna parivaar — Doshi", "+91 94230 00008", "Jalna, Maharashtra", "Jalna", "Outstation", "Jalna parivaar", 7, "Couriered", 1, "Kailasha Resort", "Indore Junction", "Preeti ji",
     ["Myra 20", "Birthday + Sangeet 20", "Carnival 21", "Reception 21", "Phera 22", "Bidai 22"]),
    ("Jamner parivaar — Kothari", "+91 94040 00009", "Jamner, Maharashtra", "Jamner", "Outstation", "Jamner parivaar", 5, "Pending", 1, "Kailasha Resort", "Bus stand", "Preeti ji",
     ["Birthday + Sangeet 20", "Carnival 21", "Reception 21", "Phera 22"]),
    ("Business associates — textile", "+91 98261 00010", "Indore", "Indore", "Local", "Business friends", 10, "Pending", 0, None, "Self", "Dr. Vinod ji",
     ["Reception 21"]),
    ("Preeti ji's mandal", "+91 98932 00011", "Indore", "Indore", "Local", "Preeti ji's friends", 12, "Handed", 0, None, "Shuttle from Indore", "Preeti ji",
     ["Mehendi 18", "Birthday + Sangeet 20", "Reception 21"]),
]

# key, name, role_label, scope
TEAMS = [
    ("dir", "Event Direction", "Mohit", "Owns the master run sheet, the vendor contracts and the final word on timing."),
    ("vckr", "Venue Commander · Kailasha", "Lead", "Final say on everything at Kailasha."),
    ("vcgy", "Venue Commander · Golden Yug", "Lead", "Final say on everything at Golden Yug."),
    ("plan", "Planning team", "Lead", "Builds and reprints the run sheet daily."),
    ("conv", "Convoy Controller · transport", "Lead", "Every vehicle, every leg, every bus captain."),
    ("accom", "Accommodation team", "2 leads, one per venue", "Room charts, key envelopes, check-in and checkout."),
    ("coord", "Coordination team", "Lead + floor coordinators", "One floor coordinator per live function."),
    ("inv", "Inventory team", "Lead + 2 custodians", "The home store, then Kailasha store and Golden Yug store."),
    ("guest", "Guest relations & patrika", "Lead", "The fifteen sub-group lists, patrika distribution and reconciliation."),
    ("cater", "Catering liaison", "2, one per venue", "Counts to Vimal ji 24 hours ahead in writing."),
    ("tech", "Technical — sound, LED, pyro, SFX", "2, one per venue", "Rig checks two hours before every function."),
    ("fin", "Finance & vendor payments", "Lead", "Payment schedule for every vendor, cash floats to leads."),
    ("gift", "Gifting, shagun & valuables", "Lead + 1", "Shagun counter at reception with a two-person rule."),
    ("med", "Medical & safety", "Lead", "Doctor on call at each venue, first-aid kits, ambulance number."),
]

# name, scope, where_needed
VENDORS = [
    ("Catering — Mr. Vimal Lalawat", "All sessions 20–22 Dec at both venues", "Kailasha + Golden Yug"),
    ("Catering — Buddy's Cafe", "High tea + dinner, 18 Dec", "Buddy's, Indore"),
    ("Catering — home team", "All meals 19 Dec", "Vora residence"),
    ("Pandit ji", "Grah shanti, toran, milni, phera, bidai", "Home + Kailasha"),
    ("Decoration", "Mehendi, Myra, sangeet, carnival, reception, mandap", "All venues"),
    ("Sound, LED, pyro, SFX", "Two rigs — one per venue, 20–22 Dec", "Kailasha + Golden Yug"),
    ("Choreographer + entry event team", "Myra, sangeet, carnival, reception, procession, phera", "Both venues"),
    ("Anchors x6-7", "Different anchor per event", "Per anchor brief"),
    ("Photography + video", "Two crews needed on 20 and 22 Dec mornings", "Both venues"),
    ("Makeup artist", "Bride from 18 Dec, family from 20 Dec, groom side at GY", "Both venues"),
    ("Mehendi artists", "18 Dec — bride separately from morning", "Home + Buddy's"),
    ("Mentalist", "20 Dec, 2-4 PM", "Golden Yug"),
    ("Live band", "21 Dec reception", "Golden Yug lawn"),
    ("Transport fleet", "Buses, tempo travellers, cars, 18-22 Dec", "Indore, both venues, Durg run"),
]

# date, session_name, time, venue, vendor, who_eats, guaranteed_plates, rate
MEALS = [
    ("2025-12-18", "High tea", "17:00", "Home & Buddy's", "Catering — Buddy's Cafe", "Mehendi guests", 150, 400),
    ("2025-12-18", "Dinner", "20:30", "Home & Buddy's", "Catering — Buddy's Cafe", "Mehendi guests", 150, 800),
    ("2025-12-19", "Breakfast", "08:30", "Home & Buddy's", "Catering — home team", "Family + early arrivals", 60, 0),
    ("2025-12-19", "Lunch", "13:00", "Home & Buddy's", "Catering — home team", "Family + arrivals", 80, 0),
    ("2025-12-19", "High tea", "17:00", "Home & Buddy's", "Catering — home team", "Family + arrivals", 80, 0),
    ("2025-12-19", "Dinner", "20:00", "Home & Buddy's", "Catering — home team", "Family + arrivals", 100, 0),
    ("2025-12-20", "Breakfast", "09:00", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side", 280, 250),
    ("2025-12-20", "Breakfast", "09:00", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Bride side", 220, 250),
    ("2025-12-20", "Lunch ?", "13:00", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side — assumed", 280, 450),
    ("2025-12-20", "Lunch", "13:30", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Bride side + Myra", 260, 450),
    ("2025-12-20", "High tea", "16:00", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side", 280, 200),
    ("2025-12-20", "High tea", "16:00", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Bride side", 220, 200),
    ("2025-12-20", "Dinner — Sangeet", "22:00", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Both sides", 520, 1100),
    ("2025-12-21", "Breakfast", "08:30", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side", 280, 250),
    ("2025-12-21", "Breakfast", "08:30", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Bride side", 220, 250),
    ("2025-12-21", "Carnival lunch", "13:00", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Both sides — stall format", 520, 750),
    ("2025-12-21", "High tea", "17:00", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side", 280, 200),
    ("2025-12-21", "High tea", "17:00", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Bride side", 220, 200),
    ("2025-12-21", "Dinner — Reception", "21:30", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Both sides + local guests", 900, 1300),
    ("2025-12-22", "Breakfast", "07:30", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side", 280, 250),
    ("2025-12-22", "Breakfast", "07:30", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Bride side", 220, 250),
    ("2025-12-22", "Lunch — Phera", "13:30", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Both sides", 560, 900),
    ("2025-12-22", "High tea ?", "15:30", "Kailasha Resort", "Catering — Mr. Vimal Lalawat", "Both sides — assumed", 400, 200),
    ("2025-12-22", "Dinner — farewell", "18:00", "Golden Yug", "Catering — Mr. Vimal Lalawat", "Groom side + bride family", 330, 900),
]

# leg_no, date, from_venue, to_venue, must_arrive, depart_by, notes
LEGS = [
    ("1", "2025-12-20", None, "Golden Yug", "07:00", "previous evening", "Durg -> Golden Yug. Overnight run. Groom side, full."),
    ("2", "2025-12-20", None, "Kailasha Resort", "09:00", "08:00", "Indore home -> Kailasha. Bride family + local guests."),
    ("3", "2025-12-20", "Golden Yug", "Kailasha Resort", "19:45", "18:30", "For birthday and sangeet. Groom side, full."),
    ("4", "2025-12-20", "Kailasha Resort", "Golden Yug", "00:45", "23:30", "Midnight return. Groom side, full."),
    ("5", "2025-12-21", "Golden Yug", "Kailasha Resort", "11:00", "10:15", "For carnival. Groom side, full."),
    ("6", "2025-12-21", "Kailasha Resort", "Golden Yug", "16:00", "15:30", "Return to rest before reception. Groom side, full."),
    ("7", "2025-12-21", "Kailasha Resort", "Golden Yug", "19:15", "18:30", "For reception. Bride side."),
    ("8", "2025-12-21", "Golden Yug", "Kailasha Resort", "00:15", "23:15", "After reception. Bride side."),
    ("9", "2025-12-22", "Golden Yug", "Kailasha Resort", "11:45", "10:45", "Muhurat leg. No slack before the 12:15 phera. Baraat, full."),
    ("10", "2025-12-22", "Kailasha Resort", "Golden Yug", "17:30", "16:15", "After bidai, for the farewell dinner. Bride + groom side."),
    ("11", "2025-12-22", "Golden Yug", None, None, "21:00", "Departure to Durg. Groom side, full."),
]


def _sheet(wb, name, headers, rows):
    ws = wb.create_sheet(name)
    ws.append(headers)
    for row in rows:
        ws.append(row)


def build_workbook() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)

    _sheet(wb, "SubGroups", ["sub_group_name"], [(s,) for s in SUB_GROUPS])
    _sheet(wb, "Venues", ["venue_name", "location", "rooms_total", "notes"], VENUES)
    _sheet(wb, "Functions", ["function_name", "date"], FUNCTIONS)
    _sheet(wb, "Guests", [
        "household_name", "primary_phone", "address", "city", "category", "sub_group", "pax",
        "patrika_status", "stay_required", "venue", "pickup_point", "owner_in_family", "functions_invited",
    ], [
        (n, ph, ad, city, cat, sub, p, pat, stay, ven, pick, own, ", ".join(f))
        for (n, ph, ad, city, cat, sub, p, pat, stay, ven, pick, own, f) in GUESTS
    ])
    _sheet(wb, "Teams", ["team_key", "team_name", "role_label", "scope"], TEAMS)
    _sheet(wb, "Vendors", ["vendor_name", "scope", "where_needed"], VENDORS)
    _sheet(wb, "MealSessions", [
        "date", "session_name", "time", "venue", "vendor", "who_eats", "guaranteed_plates", "rate",
    ], MEALS)
    _sheet(wb, "ConvoyLegs", [
        "leg_no", "date", "from_venue", "to_venue", "must_arrive", "depart_by", "notes",
    ], LEGS)

    return wb


def run():
    """bench --site <site> execute wedding_plan.setup.seed_riya_avish.run"""
    from wedding_plan.api.weddings import create_wedding_and_join

    if not frappe.db.exists("Wedding", "riya-avish-2025"):
        create_wedding_and_join(
            slug="riya-avish-2025",
            couple_names="Riya Vora x Avish Parekh",
            start_date="2025-12-18",
            end_date="2025-12-22",
            venues_summary="Kailasha Resort (Ujjain), Golden Yug (Tarana), Home & Buddy's (Indore)",
        )
        frappe.db.commit()

    wb = build_workbook()
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())

    result = run_import("riya-avish-2025", path)
    os.remove(path)
    print(result)
    return result

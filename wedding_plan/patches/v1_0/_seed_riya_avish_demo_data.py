"""One-off, hand-run enrichment of the real Riya & Avish wedding (744uf0i1sm)
with additional realistic, connected records so every module/workflow in the
app has something to show. NOT registered in patches.txt / hooks - run once
by hand via:
    bench --site <site> execute wedding_plan.patches.v1_0._seed_riya_avish_demo_data.execute
Idempotent where practical (checks before inserting) so re-running is safe.
"""
import frappe

W = "744uf0i1sm"


def _ensure(doctype, filters, values):
	name = frappe.db.get_value(doctype, filters)
	if name:
		return name
	doc = frappe.get_doc({"doctype": doctype, **filters, **values})
	doc.insert(ignore_permissions=True)
	return doc.name


def _child(rows):
	return [dict(r) for r in rows]


def execute():
	frappe.set_user("ca.bc.chechani@gmail.com")

	# ------------------------------------------------------------------
	# 1. Small corrections to existing records
	# ------------------------------------------------------------------
	frappe.db.set_value("Wedding", W, "status", "Active")
	frappe.db.set_value("WD Meal Session", "7d39qc98c5", "date", "2026-12-21")
	frappe.db.set_value("WD Meal Session", "7d357fsgtm", "date", "2026-12-22")
	frappe.db.set_value("WD Meal Session", "7d3rakb7t8", "date", "2026-12-21")
	frappe.db.set_value("WD Convoy Leg", "abcpgpsn29", "vehicle", "cjltrffg7a")

	# ------------------------------------------------------------------
	# 2. Main ceremony function (function type backfilled separately by
	#    the existing seed_function_types patch -> "Phera / Vivaah")
	# ------------------------------------------------------------------
	CEREMONY = _ensure(
		"WD Function",
		{"wedding": W, "function_type": "Phera / Vivaah"},
		dict(
			date="2026-12-22", start_time="10:00:00", end_time="13:00:00",
			venue="Sangam Farm", sub_venue="rb1di2nemq",
			notes=("Jain Vivah Vidhi - phera and vivah sanskar per family rivaj, "
				"Namokar Mantra recitation; no havan/agni per Jain custom. "
				"Followed by ashirwad from elders."),
		),
	)

	# ------------------------------------------------------------------
	# 3. Second real collaborator -> proper Wedding Member
	# ------------------------------------------------------------------
	_ensure("Wedding Member", {"wedding": W, "user": "vicepresident@sahajtherapy.com"},
		dict(role="Event Director"))

	# ------------------------------------------------------------------
	# 4. Vendors for genuine gaps
	# ------------------------------------------------------------------
	VENDOR_PHOTO = _ensure("WD Vendor", {"wedding": W, "vendor_name": "Frame & Focus Studio"},
		dict(scope="Candid + Traditional Photography, Cinematic Videography, Drone",
			where_needed="All Main Venues", contact_name="Rohit Mehta",
			contact_phone="9814523670", advance_amount=150000.0, vendor_type="Photography"))
	VENDOR_MAKEUP = _ensure("WD Vendor", {"wedding": W, "vendor_name": "Glow Bridal Studio"},
		dict(scope="Bridal Makeup, Family Makeup, Hair Styling, Mehendi",
			where_needed="Hotel White Season - Bridal Suite", contact_name="Kavita Mehta",
			contact_phone="9845123670", advance_amount=35000.0, vendor_type="Makeup Artist"))
	VENDOR_PANDIT = _ensure("WD Vendor", {"wedding": W, "vendor_name": "Kantilal Shastri - Vivah Vidhi Specialist"},
		dict(scope="Muhurat timing, Phera vidhi, Vivah sanskar per Jain rivaj",
			where_needed="Sangam Farm - Grand Banquet Hall", contact_name="Kantilal Shastri",
			contact_phone="9928541230", advance_amount=11000.0, vendor_type="Pandit"))

	# ------------------------------------------------------------------
	# 5. Stores
	# ------------------------------------------------------------------
	STORE_HWS = _ensure("WD Store", {"wedding": W, "store_name": "Hotel White Season - Back Store Room"},
		dict(venue="Hotel White Season", location="Ground floor, behind Banquet hall 1"))
	STORE_SF = _ensure("WD Store", {"wedding": W, "store_name": "Sangam Farm - Decor & Equipment Store"},
		dict(venue="Sangam Farm", location="Rear of Grand Banquet Hall"))

	frappe.db.commit()
	print("CHECKPOINT 1: masters/function/vendors/stores done")

	# ==================================================================
	# 6. Give subtype to existing tasks with a genuinely matching detail
	#    record already attached -> hook clones checklist items and
	#    reuses (never duplicates) that detail row.
	# ==================================================================
	SUBTYPE = {r.subtype_name: r.name for r in frappe.get_all("WD Task Subtype", fields=["name", "subtype_name"])}

	for task_name, subtype_label in [
		("r22p3vnklq", "Cue sheet"),
		("our0bu6q6o", "Anchor brief"),
		("n3sqlbik4f", "Makeup, hair & mehendi"),
		("mphc963tt6", "Outfit"),
		("mk3dv6cpe6", "Outfit"),
		("sobi33em3u", "Permit"),
		("f9ckk8jkf3", "Stage, truss & load-in"),
		("u0b17ld3rg", "Floral order"),
	]:
		task = frappe.get_doc("WD Task", task_name)
		if not task.subtype:
			task.subtype = SUBTYPE[subtype_label]
			task.save(ignore_permissions=True)

	frappe.db.commit()
	print("CHECKPOINT 2: subtypes assigned to existing tasks")

	# ==================================================================
	# 7. New tasks for subtypes with no clean existing representative
	# ==================================================================
	def new_task(title, category, subtype_label, **kw):
		existing = frappe.db.get_value("WD Task", {"wedding": W, "title": title})
		if existing:
			return existing
		doc = frappe.get_doc(dict(
			doctype="WD Task", wedding=W, title=title, category=category,
			subtype=SUBTYPE[subtype_label], status=kw.pop("status", "Not Started"),
			priority=kw.pop("priority", "Medium"), **kw,
		))
		doc.insert(ignore_permissions=True)
		return doc.name

	T_CHOREO = new_task(
		"Sangeet Rehearsal & Choreography", "Entertainment & Artists", "Choreography",
		function="dgv6h5v7mm", status="In Progress",
		assigned_to_type="Person", assigned_person="ca.bc.chechani@gmail.com",
		contact_name="Nidhi Jain", contact_phone="9845632120",
	)
	T_DOC = new_task(
		"Marriage Registration & Document Filing", "Documentation", "Document / registration",
		due_date="2026-12-28",
		assigned_to_type="Person", assigned_person="ca.bc.chechani@gmail.com",
		contact_name="Bhagchand", contact_phone="8875627151",
	)
	T_COVER = new_task(
		"Photography & Videography Coverage Plan", "Photography & Content", "Coverage plan",
		assigned_to_type="Vendor", assigned_vendor=VENDOR_PHOTO,
	)
	T_RITUAL = new_task(
		"Ritual Muhurat & Samagri Arrangement", "Ritual & Puja Arrangements", "Ritual / muhurat",
		function=CEREMONY, priority="High",
		assigned_to_type="Vendor", assigned_vendor=VENDOR_PANDIT,
	)
	T_HAMPER = new_task(
		"Guest Welcome Hamper & Shagun Counter Setup", "Gifting, Shagun & Hampers", "Hamper tier / shagun counter",
		assigned_to_type="Team", assigned_team="lvl2ush88g",
	)
	T_BROADCAST = new_task(
		"Guest & Vendor Broadcast Messaging", "Guest & Vendor Communication", "Broadcast / briefing",
		assigned_to_type="Team", assigned_team="lvl2ush88g",
	)
	T_MANDAP = new_task(
		"Mandap & Ritual Decor Setup", "Décor & Styling", "Mandap & ritual décor",
		function=CEREMONY,
		assigned_to_type="Vendor", assigned_vendor="9215b6ftjl",
	)
	T_SOUND = new_task(
		"Sound & Mic Setup for Ceremonies", "Logistics & Setup", "Sound setup",
		function=CEREMONY,
		assigned_to_type="Vendor", assigned_vendor="921fe6rq8k",
	)

	frappe.db.commit()
	print("CHECKPOINT 3: new tasks created:", T_CHOREO, T_DOC, T_COVER, T_RITUAL, T_HAMPER, T_BROADCAST, T_MANDAP, T_SOUND)

	# ==================================================================
	# 8. Fill in the meaningful business fields + child rows on detail
	#    sheets (both reused-existing and freshly auto-created).
	# ==================================================================

	# -- Cue Sheet Item (reused: rqmntde9o0, task r22p3vnklq) --
	cue = frappe.get_doc("WD Task Cue Sheet Item", {"task": "r22p3vnklq"})
	cue.update(dict(
		cue_number="12", cue_name="Bride & Groom Grand Entry",
		time_trigger="19:15", music_track_timestamp="0:00-2:30",
		light_cue="Spotlight follow + gold wash", who_executes="Sharma Sound & Events + Anchor",
		standby_call_seconds=120, backup_if_fails="Anchor vamps with mic until cue confirmed",
	))
	cue.save(ignore_permissions=True)

	# -- Anchor Brief (reused: our0bu6q6o) --
	anchor = frappe.get_doc("WD Anchor Brief", {"task": "our0bu6q6o"})
	anchor.update(dict(
		function=CEREMONY, style_required="Ritual-literate", language_mix="Hindi + Marwari, light English for younger guests",
		duration_hours=3.0, mic_type="Handheld",
		do_not_say_list="No jokes about height/weight of the couple; do not rush the parents' stage moment",
	))
	if not anchor.names_to_announce:
		anchor.set("names_to_announce", _child([
			dict(person_name="Bhagchand Chechani", relation="Father of the Groom", pronunciation="BHAAG-chand"),
			dict(person_name="R.K. Soni", relation="Father of the Bride", pronunciation="R-K So-ni"),
		]))
	anchor.save(ignore_permissions=True)

	# -- Choreography Detail (orphan on our0bu6q6o, left as-is; fill it too since it's genuinely about choreography) --
	choreo_detail_name = frappe.db.get_value("WD Task Choreography Detail", {"task": "our0bu6q6o"})
	if choreo_detail_name:
		chor = frappe.get_doc("WD Task Choreography Detail", choreo_detail_name)
		chor.update(dict(
			rehearsal_venue_sound="Hotel White Season - Royal Lawn",
			entry_sequence_design="Cousins group dance, then bride & groom entry on a mashup track",
			total_running_time_min=25,
		))
		if not chor.performances:
			chor.set("performances", _child([
				dict(act_name="Cousins' Sangeet Mashup", performers="Surbhi, Dinesh & cousins", song="Bollywood mashup", duration="6 min"),
				dict(act_name="Bride & Groom Entry", performers="Riya & Avish", song="Couple's chosen entry track", duration="3 min"),
			]))
		if not chor.rehearsal_dates:
			chor.set("rehearsal_dates", _child([dict(rehearsal_date="2026-12-15"), dict(rehearsal_date="2026-12-19")]))
		chor.save(ignore_permissions=True)

	# -- Makeup Hair Mehendi Detail x2 (reused, task n3sqlbik4f) --
	makeup_names = frappe.get_all("WD Task Makeup Hair Mehendi Detail", filters={"task": "n3sqlbik4f"}, fields=["name"])
	makeup_fill = [
		dict(artist=VENDOR_MAKEUP, service="Bridal makeup", call_time="06:00:00", duration_per_person_min=120,
			number_of_people=1, assistants_provided=2, trial_date="2026-11-20", trial_approved=1,
			location="pvqgp5b98j"),
		dict(artist=VENDOR_MAKEUP, service="Family makeup", call_time="08:00:00", duration_per_person_min=45,
			number_of_people=6, assistants_provided=2, location="pvqgp5b98j"),
	]
	for row, fill in zip(makeup_names, makeup_fill):
		doc = frappe.get_doc("WD Task Makeup Hair Mehendi Detail", row.name)
		doc.update(fill)
		doc.save(ignore_permissions=True)

	# -- Outfit Detail (reused: groom nv0m7i2ur1 on mphc963tt6, bride nv05g85i3h on mk3dv6cpe6) --
	groom_outfit = frappe.get_doc("WD Task Outfit Detail", {"task": "mphc963tt6"})
	groom_outfit.update(dict(
		wearer="Avish", outfit_type_colour="Ivory & gold sherwani with maroon safa",
		designer_shop_contact="Rajwada Sherwani House, Bhilwara - 9414785236",
		order_date="2026-10-15", trial_1="2026-11-10", trial_2="2026-12-05",
		final_delivery_date="2026-12-15", jewellery_set="Kundan buttons + brooch",
		safa_pagdi_count=1, safa_colour="Maroon with gold border",
		steaming_ironing_done=1, packed_in_bag_no="G-1", carried_by="lvm66fa95n",
		changing_room_at_venue="rb1di2nemq", backup_outfit="Plain cream bandhgala",
	))
	groom_outfit.save(ignore_permissions=True)

	bride_outfit = frappe.get_doc("WD Task Outfit Detail", {"task": "mk3dv6cpe6"})
	bride_outfit.update(dict(
		wearer="Riya", outfit_type_colour="Red & gold banarasi lehenga",
		designer_shop_contact="Meenakari Bridal Couture, Jaipur - 9928541230",
		order_date="2026-10-01", trial_1="2026-11-05", trial_2="2026-12-01",
		final_delivery_date="2026-12-14", jewellery_set="Kundan-meena bridal set with maang tikka",
		kaleere_chooda=1, steaming_ironing_done=1, packed_in_bag_no="B-1",
		carried_by="lvm66fa95n", changing_room_at_venue="rb1di2nemq",
		backup_outfit="Simpler red saree",
	))
	bride_outfit.save(ignore_permissions=True)

	# -- Permit Detail (reused: t3s3mq6vlu, task sobi33em3u) --
	permit = frappe.get_doc("WD Task Permit Detail", {"task": "sobi33em3u"})
	permit.update(dict(
		permit_type="Loudspeaker beyond 10 PM", issuing_authority="Bhilwara Municipal Corporation",
		applied_on="2026-11-25", fee_paid=2500.0, reference_number="BMC/2026/LS/4471",
		validity_from="2026-12-19", validity_to="2026-12-23", copy_on_site_with="lvm66fa95n",
		contact_at_authority="Inspector R.S. Meena - 9414125478",
	))
	permit.save(ignore_permissions=True)

	# -- Stage Truss Loadin (reused: kohfbbjg1g, task f9ckk8jkf3) --
	stage = frappe.get_doc("WD Task Stage Truss Loadin", "kohfbbjg1g")
	stage.update(dict(trucks_labour_count=6, store_room=STORE_HWS))
	stage.save(ignore_permissions=True)

	# -- Floral Order x3 (reused, task u0b17ld3rg): add flower_type child rows --
	flower_map = {
		"d5h576l6nt": ["Genda (marigold)"],
		"d5h2d7je6d": ["Rajnigandha", "Mogra / jasmine"],
		"d5hem05vgh": ["Rose", "Lily"],
	}
	for order_name, flowers in flower_map.items():
		order = frappe.get_doc("WD Task Floral Order", order_name)
		if not order.flower_type:
			order.set("flower_type", _child([dict(flower_type=f) for f in flowers]))
			order.save(ignore_permissions=True)

	frappe.db.commit()
	print("CHECKPOINT 4: existing detail sheets filled")

	# -- New task detail sheets: Choreography detail for T_CHOREO --
	choreo2 = frappe.get_doc("WD Task Choreography Detail", {"task": T_CHOREO})
	choreo2.update(dict(
		choreographer=None, rehearsal_venue_sound="Sangam Farm - Poolside Area",
		entry_sequence_design="Cousins' sangeet performance followed by couple's choreographed entry",
		stage_riser_requirement="12ft x 8ft riser, 2ft height", total_running_time_min=20,
	))
	choreo2.set("performances", _child([
		dict(act_name="Youth Group Dance", performers="Cousins & friends", song="Mixed Bollywood medley", duration="5 min"),
	]))
	choreo2.set("rehearsal_dates", _child([dict(rehearsal_date="2026-12-16"), dict(rehearsal_date="2026-12-20")]))
	choreo2.save(ignore_permissions=True)

	# -- Document Detail for T_DOC --
	doc_detail = frappe.get_doc("WD Task Document Detail", {"task": T_DOC})
	doc_detail.update(dict(
		document_type="Marriage registration", owner_team="lvl2ush88g", required_by="2026-12-28",
		status="Not started", where_original_kept="Chechani residence - family locker",
		registration_appointment="2026-12-29 11:00:00", notice_period_applicable="30 days under Special Marriage Act (if applicable)",
	))
	doc_detail.set("witnesses", _child([
		dict(witness_name="Dinesh Chechani", id_proof="Aadhaar", contact="7785246932"),
		dict(witness_name="R.K. Soni", id_proof="Aadhaar", contact="8541236987"),
	]))
	doc_detail.save(ignore_permissions=True)

	# -- Coverage Plan Detail for T_COVER --
	cover = frappe.get_doc("WD Task Coverage Plan Detail", {"task": T_COVER})
	cover.update(dict(
		parallel_venue_coverage_needed=1, crew_photo=2, crew_video=2, crew_candid=2,
		drone=1, drone_permission_ref="Applied - DGCA NPNT", coverage_hours=40,
		phone_free_moments="Phera and vidaai", backup_drives=3,
		delivery_raw="2026-12-27", delivery_edited="2027-01-15", delivery_album="2027-02-01", delivery_reel="2026-12-24",
	))
	cover.set("family_photo_list", _child([
		dict(grouping="Bride's immediate family", names="Riya, R.K. Soni, Mrs. Soni, kailash Soni, Deepa Soni", caller="Guest Relations team"),
		dict(grouping="Groom's immediate family", names="Avish, Bhagchand, Mr. & Mrs. Chechani, Dinesh, Surbhi", caller="Guest Relations team"),
	]))
	cover.save(ignore_permissions=True)

	# -- Ritual Muhurat Detail for T_RITUAL --
	ritual = frappe.get_doc("WD Task Ritual Muhurat Detail", {"task": T_RITUAL})
	ritual.update(dict(
		ritual="Phera / Vivaah", muhurat_start="2026-12-22 10:00:00", muhurat_end="2026-12-22 11:30:00",
		fixed_or_flexible="Fixed", pandit_ji=VENDOR_PANDIT, number_of_pandits=1, dakshina=11000.0,
		samagri_responsibility="Family", time_allowed_minutes=90, prasad_count=300,
		photography_restrictions="No flash during mantra recitation",
		language_of_recitation="Namokar Mantra + Marwari rivaj, no Vedic havan (Jain custom)",
	))
	ritual.set("samagri_items", _child([
		dict(item="Kalash", quantity=1, unit="nos", arranged_by="Family", stored_at=STORE_SF, verified_by_pandit=1),
		dict(item="Coconut", quantity=5, unit="nos", arranged_by="Family", stored_at=STORE_SF),
		dict(item="Agarbatti & dhoop", quantity=2, unit="pieces", arranged_by="Family", stored_at=STORE_SF),
		dict(item="Phool mala (fresh)", quantity=4, unit="nos", arranged_by="Vendor", stored_at=STORE_SF),
	]))
	ritual.set("seating_on_mandap", _child([
		dict(person_name="Riya", role="Bride"),
		dict(person_name="Avish", role="Groom"),
		dict(person_name="R.K. Soni", role="Father of the Bride"),
		dict(person_name="Bhagchand Chechani", role="Father of the Groom"),
	]))
	ritual.save(ignore_permissions=True)

	# -- Hamper Detail for T_HAMPER --
	hamper = frappe.get_doc("WD Task Hamper Detail", {"task": T_HAMPER})
	hamper.update(dict(
		tier="Standard", packing_type_tag="Welcome box", quantity_to_pack=30,
		packed_by="lvl2ush88g", packed_date="2026-12-18", stored_at=STORE_HWS,
		delivery_point="Room before arrival", delivered_count=0,
	))
	hamper.set("recipient_group", _child([dict(sub_group="mnq471msdk"), dict(sub_group="mnqcansp72")]))
	hamper.set("contents", _child([
		dict(item="Mithai box", quantity=1, unit="pieces", source="Local sweet shop", cost=250.0),
		dict(item="Dry fruit pouch", quantity=1, unit="pieces", source="Local sweet shop", cost=180.0),
		dict(item="Welcome letter + itinerary card", quantity=1, unit="pieces", cost=10.0),
	]))
	hamper.save(ignore_permissions=True)

	# -- Broadcast Detail for T_BROADCAST --
	broadcast = frappe.get_doc("WD Task Broadcast Detail", {"task": T_BROADCAST})
	broadcast.update(dict(
		audience="Sub-group", channel="WhatsApp broadcast",
		message_content="Reminder: Haldi ceremony starts 9 AM sharp at Sangam Farm, Poolside Area. Please wear yellow!",
		scheduled_datetime="2026-12-20 18:00:00", sent_by="lvl2ush88g",
		delivered_count=28, read_count=22, replies_needing_action=2, follow_up_required=1,
	))
	broadcast.save(ignore_permissions=True)

	# -- Mandap Decor for T_MANDAP --
	mandap = frappe.get_doc("WD Task Mandap Decor", {"task": T_MANDAP})
	mandap.update(dict(
		mandap_size="20ft x 20ft", mandap_height=14.0, mandap_style="Floral",
		mattress_fresh_cover=1, chowki=2, havan_kund=0, gadi_bichat=1, gadi_bichat_area=400.0,
		low_height_chairs=6, centre_aisle=1, centre_aisle_length=40.0,
		seating_mix="Gadi-bichat for elders, chairs for the rest", candle_stands=12,
		toran_entry_items=1, urli_placement="Entrance and mandap steps",
		samela_tent_size="60ft x 40ft", groom_sofa_steps=3, fire_clearance_indoor_havan=0,
	))
	mandap.save(ignore_permissions=True)

	# -- Sound Detail for T_SOUND --
	sound = frappe.get_doc("WD Task Sound Detail", {"task": T_SOUND})
	sound.update(dict(
		setup_ready_time="08:00:00", pax=500, artist="Live shehnai + DJ for reception crossover",
		line_array_tops=4, dual_bass=2, monitors=2, cordless_mics=3, cordless_mic_brand="Shure",
		wired_mics=2, collar_lapel_mics=2, console_mixer="Yamaha CL5", sound_operator="Sharma Sound & Events crew",
		power_arrangement_by="Vendor", curfew_time="22:30:00", decibel_limit=75,
	))
	sound.save(ignore_permissions=True)

	frappe.db.commit()
	print("CHECKPOINT 5: new task detail sheets filled")

	# ==================================================================
	# 9. Household-level functions_invited (WD Guest, multiselect),
	#    derived from the real per-member WD Guest Member Function data.
	# ==================================================================
	household_functions = {
		"tf88o2dq1m": ["otv7booo2h", "od4qndchqk", "dgv6h5v7mm", "qtachej2s4", "nu7c8drk1g", CEREMONY, "sd0alhd708"],  # Chechani (host side) - all functions
		"tf8tju1ib1": ["qtachej2s4", "od4qndchqk", "otv7booo2h", "dgv6h5v7mm", CEREMONY],  # Pagariya
		"tf8pj5q1cn": ["od4qndchqk", "dgv6h5v7mm", CEREMONY],  # Ranka
		"tf8o32o88f": ["sd0alhd708", "dgv6h5v7mm", "nu7c8drk1g", "od4qndchqk", CEREMONY],  # Soni
	}
	for guest_name, fns in household_functions.items():
		guest = frappe.get_doc("WD Guest", guest_name)
		if not guest.functions_invited:
			guest.set("functions_invited", _child([dict(wd_function=f) for f in fns]))
			guest.save(ignore_permissions=True)

	# ------------------------------------------------------------------
	# 10. Pickup guest members + fill pending pickup fields
	# ------------------------------------------------------------------
	pickup1 = frappe.get_doc("WD Pickup", "vt0asu5o63")  # Pagariya
	if not pickup1.guest_members:
		pickup1.set("guest_members", _child([dict(guest_member="3p4g89ti7l")]))
	pickup1.update(dict(mode="Road", pax_count=4, luggage_count=3, eta="2026-12-19 19:30:00"))
	pickup1.save(ignore_permissions=True)

	pickup2 = frappe.get_doc("WD Pickup", "cg8o3c4brq")  # Ranka
	if not pickup2.guest_members:
		pickup2.set("guest_members", _child([dict(guest_member="3hisatg5e1")]))
	pickup2.update(dict(mode="Train", pax_count=5, luggage_count=4, eta="2026-12-19 17:00:00"))
	pickup2.save(ignore_permissions=True)

	# ------------------------------------------------------------------
	# 11. Room allotment occupants
	# ------------------------------------------------------------------
	occupant_map = {
		"tk465951jb": ["3p4g89ti7l"],
		"ss9mglnjgi": ["2l2al5sqcv", "ltcr7ko0u2"],
		"ss9eqf0v8i": ["3b3e6av76l", "mt68hent5d"],
	}
	for allotment_name, members in occupant_map.items():
		allotment = frappe.get_doc("WD Room Allotment", allotment_name)
		if not allotment.guest_occupants:
			allotment.set("guest_occupants", _child([dict(guest_member=m) for m in members]))
			allotment.save(ignore_permissions=True)

	frappe.db.commit()
	print("CHECKPOINT 6: guest functions_invited, pickup guests, room occupants done")

	# ------------------------------------------------------------------
	# 12. Menus + menu items on the (now correctly dated) meal sessions
	# ------------------------------------------------------------------
	def new_menu(function, meal_session, service_label, venue, service_time, expected_count, items):
		existing = frappe.db.get_value("WD Menu", {"wedding": W, "service_label": service_label})
		if existing:
			return existing
		doc = frappe.get_doc(dict(
			doctype="WD Menu", wedding=W, function=function, meal_session=meal_session,
			service_label=service_label, venue=venue, service_time=service_time,
			expected_count=expected_count,
			items=_child([dict(item_name=n, category=c, status=s, notes=note or None) for n, c, s, note in items]),
		))
		doc.insert(ignore_permissions=True)
		return doc.name

	# Wedding is ~3.5 months out (today 2026-09-05, event 2026-12-20/22), so
	# most menu items are realistically still Pending confirmation with the
	# caterer rather than already Ready - the mix is what actually exercises
	# the "mark ready as it firms up" execution checklist.
	new_menu("sd0alhd708", "7d3rakb7t8", "Reception Dinner - Sangam Farm", "Sangam Farm", "2026-12-21 20:00:00", 500, [
		("Jain Paneer Butter Masala (no onion-garlic)", "Jain / Special Diet", "Blocked",
			"Caterer needs to confirm no-onion-garlic prep line is separate from the main kitchen."),
		("Dal Baati Churma", "Indian Main Course", "Ready", ""),
		("Missi Roti & Bajra Roti", "Breads", "Pending", ""),
		("Live Chaat Counter (Jain)", "Live Counters", "In Progress", ""),
		("Ghevar & Rabri", "Sweets & Desserts", "Pending", ""),
		("Buttermilk & Jaljeera", "Beverages", "Pending", ""),
	])
	new_menu("dgv6h5v7mm", "7d357fsgtm", "Reception Breakfast - Hotel White Season", "Hotel White Season", "2026-12-22 08:00:00", 250, [
		("Poha & Kachori", "Starters", "In Progress", ""),
		("South Indian Live Counter (no onion-garlic)", "Live Counters", "Pending", ""),
		("Tea, Coffee & Fresh Juice", "Beverages", "Ready", ""),
		("Kids Cereal & Sandwich Counter", "Kids Menu", "Pending", ""),
	])
	new_menu("qtachej2s4", "7d3rakb7t8", "Mehndi Lunch - Hotel White Season", "Hotel White Season", "2026-12-20 13:00:00", 300, [
		("Jain Thali", "Jain / Special Diet", "Ready", ""),
		("Paneer Tikka", "Starters", "In Progress", ""),
		("Rasmalai", "Sweets & Desserts", "Pending", ""),
		("Masala Chaas", "Beverages", "Pending", ""),
	])

	# ------------------------------------------------------------------
	# 13. Transport movements for outstation families
	# ------------------------------------------------------------------
	OWNER_MEMBER = frappe.db.get_value("Wedding Member", {"wedding": W, "user": "vicepresident@sahajtherapy.com"})

	def new_movement(**kw):
		existing = frappe.db.get_value("WD Transport Movement", {"wedding": W, "notes": kw.get("notes")})
		if existing:
			return existing
		doc = frappe.get_doc(dict(doctype="WD Transport Movement", wedding=W, **kw))
		doc.insert(ignore_permissions=True)
		return doc.name

	new_movement(movement_type="Arrival Pickup", mode="Train", flight_train_number="12981 Chetak Express",
		pnr="A1B2C3", terminal_or_platform="Platform 2", origin="Udaipur", destination="Bhilwara",
		eta_planned="2026-12-19 17:00:00", status="Planned", coordinator=OWNER_MEMBER,
		notes="Ranka family arrival")
	new_movement(movement_type="Arrival Pickup", mode="Road", origin="Jaipur", destination="Bhilwara",
		eta_planned="2026-12-19 19:30:00", status="Planned", coordinator=OWNER_MEMBER,
		notes="Soni family arrival by car")
	new_movement(movement_type="Departure Drop", mode="Train", flight_train_number="12982 Chetak Express",
		pnr="D4E5F6", terminal_or_platform="Platform 1", origin="Bhilwara", destination="Udaipur",
		eta_planned="2026-12-23 11:00:00", status="Planned", coordinator=OWNER_MEMBER,
		notes="Ranka family departure")

	# ------------------------------------------------------------------
	# 14. Vehicle assignment (formal dispatch record, distinct from the
	#     quick vehicle link already on Pickup/Convoy Leg)
	# ------------------------------------------------------------------
	if not frappe.db.exists("WD Vehicle Assignment", {"wedding": W, "against_leg": "abcpgpsn29"}):
		frappe.get_doc(dict(
			doctype="WD Vehicle Assignment", wedding=W, vehicle="cjl97nkq2d",
			against_type="Convoy Leg", against_leg="abcpgpsn29",
			driver_name="Deepak", driver_phone="885236547", assigned_pax=6,
			dispatch_at="2026-12-21 18:30:00", expected_release_at="2026-12-21 21:00:00",
			status="Assigned", notes="Bride & groom's car, baraat convoy",
		)).insert(ignore_permissions=True)

	# ------------------------------------------------------------------
	# 15. WhatsApp templates + message log
	# ------------------------------------------------------------------
	def new_template(key, body, variables, status="Approved"):
		if frappe.db.exists("WD WhatsApp Template", {"template_key": key}):
			return
		frappe.get_doc(dict(doctype="WD WhatsApp Template", template_key=key, body=body,
			variables=variables, approval_status=status)).insert(ignore_permissions=True)

	new_template("rsvp_confirmation",
		"Dear {{guest_name}}, thank you for confirming your presence at Riya & Avish's wedding on 20-22 Dec 2026 at Bhilwara. We can't wait to celebrate with you!",
		"guest_name")
	new_template("t7_reminder",
		"Hi {{guest_name}}, just 7 days to go! Functions start 20 Dec at {{venue}}. Your room is confirmed. Call {{contact}} for any help.",
		"guest_name, venue, contact")
	new_template("thank_you",
		"Dear {{guest_name}}, thank you so much for being part of Riya & Avish's wedding celebrations. Your presence made it special!",
		"guest_name")

	def new_wa_log(**kw):
		doc = frappe.get_doc(dict(doctype="WD WhatsApp Message Log", wedding=W, **kw))
		doc.insert(ignore_permissions=True)
		return doc.name

	if frappe.db.count("WD WhatsApp Message Log") == 0:
		new_wa_log(direction="Out", template_key="rsvp_confirmation", to_phone="8856325647",
			from_phone="9156485236", payload="Dear Ranka Family, thank you for confirming...",
			status="Delivered", provider_message_id="wamid.RANKA001")
		new_wa_log(direction="Out", template_key="t7_reminder", to_phone="9985632475",
			from_phone="9156485236", payload="Hi Soni Family, just 7 days to go!...",
			status="Read", provider_message_id="wamid.SONI001")
		new_wa_log(direction="In", template_key="", to_phone="9156485236", from_phone="9985632475",
			payload="Thank you, we will reach by evening on 19th.", status="Received",
			provider_message_id="wamid.SONI002")

	# ------------------------------------------------------------------
	# 16. Event issue (execution-day tracking)
	# ------------------------------------------------------------------
	if frappe.db.count("WD Event Issue") == 0:
		frappe.get_doc(dict(
			doctype="WD Event Issue", wedding=W, title="Ranka family pickup running late",
			description="Train delayed by 40 minutes; greeter informed, family kept updated over WhatsApp.",
			severity="Medium", related_type="Pickup", related_pickup="cg8o3c4brq",
			issue_owner=OWNER_MEMBER, status="Resolved", resolution="Pickup adjusted, family reached hotel by 6 PM.",
			resolved_at="2026-12-19 18:15:00",
		)).insert(ignore_permissions=True)

	# ------------------------------------------------------------------
	# 17. A settlement "extra" line, to show that sub-feature too
	# ------------------------------------------------------------------
	settlement = frappe.get_doc("WD Task Final Settlement Detail", "v5uedbtbj5")
	if not settlement.approved_extras:
		settlement.set("approved_extras", _child([
			dict(item="Extra marigold strings for entrance gate", approved_by="Bhagchand", amount=3500.0),
		]))
		settlement.save(ignore_permissions=True)

	frappe.db.commit()
	print("CHECKPOINT 7: menus, transport, vehicle assignment, whatsapp, event issue, settlement extra done")

	# ==================================================================
	# 18. Every function should have at least a menu and a checklist item
	#     to show in the new Setup > Functions detail sidebar - fill the
	#     four functions with no menu yet and the three with no checklist.
	# ==================================================================
	MEHNDI_2 = "nu7c8drk1g"
	HALDI = "od4qndchqk"
	MAYRA = "otv7booo2h"

	new_menu(HALDI, None, "Haldi Morning Refreshments", "Sangam Farm", "2026-12-21 09:00:00", 150, [
		("Fresh fruit platter", "Starters", "Pending", ""),
		("Sonth ka paani / jaljeera", "Beverages", "Pending", ""),
		("Ladoo (turmeric-stained hands, fresh sweets)", "Sweets & Desserts", "Pending", ""),
	])
	new_menu(MAYRA, None, "Mayra Lunch", "Sangam Farm", "2026-12-21 13:00:00", 120, [
		("Rajasthani thali (no onion-garlic on request)", "Jain / Special Diet", "Pending", ""),
		("Gatte ki sabzi", "Indian Main Course", "Pending", ""),
		("Churma ladoo", "Sweets & Desserts", "Pending", ""),
	])
	new_menu(MEHNDI_2, None, "Mehndi Morning Snacks", "Hotel White Season", "2026-12-20 11:00:00", 100, [
		("Tea & coffee", "Beverages", "Pending", ""),
		("Namkeen mix", "Starters", "Pending", ""),
	])
	new_menu(CEREMONY, None, "Vivah Vidhi Prasad & Refreshments", "Sangam Farm", "2026-12-22 09:30:00", 80, [
		("Prasad (dry fruits & mishri)", "Sweets & Desserts", "Pending", ""),
		("Water & buttermilk for the mandap party", "Beverages", "Pending", ""),
	])

	def new_checklist_item(function, category, item, **kw):
		if frappe.db.exists("WD Function Checklist Item", {"wedding": W, "function": function, "item": item}):
			return
		frappe.get_doc(dict(
			doctype="WD Function Checklist Item", wedding=W, function=function,
			category=category, item=item, status=kw.pop("status", "Pending"), **kw,
		)).insert(ignore_permissions=True)

	new_checklist_item("sd0alhd708", "Decoration", "Stage floral backdrop refreshed for reception", status="In Progress",
		responsible_type="Vendor", responsible_vendor="9215b6ftjl", contact_name="Amit", contact_phone="7459632513")
	new_checklist_item("sd0alhd708", "Catering & Snacks", "Live counters staffed and stocked", status="Pending",
		responsible_type="Vendor", responsible_vendor="921olrmdda")
	new_checklist_item(MAYRA, "Activity & Entertainment", "Mayra gifts (bhaat) laid out for maternal uncles", status="Pending",
		responsible_type="Team", responsible_team="lvl2ush88g")
	new_checklist_item(MAYRA, "Decoration", "Seating for the ritual arranged under the mandap", status="Ready",
		responsible_type="Team", responsible_team="lvltktlupo")
	new_checklist_item(CEREMONY, "Decoration", "Mandap flowers and samagri placed before muhurat", status="Pending",
		responsible_type="Vendor", responsible_vendor=VENDOR_PANDIT)
	new_checklist_item(CEREMONY, "Other", "Pandit ji and family witnesses confirmed arrival", status="Pending",
		responsible_type="Team", responsible_team="lvm66fa95n")

	frappe.db.commit()
	print("CHECKPOINT 8: menus and checklist items backfilled so every function has both")

	# ==================================================================
	# 19. Dress code: not every function has one (a vendor-coordination
	#     task never would), so this deliberately only covers the two
	#     functions where a family would actually plan one - Mehndi
	#     (colour-coded, both sides) and the main Reception (formal).
	# ==================================================================
	def ensure_dress_code(function, **kw):
		name = frappe.db.get_value("WD Function Dress Code", {"function": function})
		if name:
			return name
		doc = frappe.get_doc(dict(doctype="WD Function Dress Code", wedding=W, function=function, **kw))
		doc.insert(ignore_permissions=True)
		return doc.name

	ensure_dress_code(
		"qtachej2s4",  # Mehndi (evening)
		groom_side_applicable=1,
		groom_side_male_dress="Mustard kurta with a printed Jaipuri jacket",
		groom_side_female_dress="Green or yellow lehenga, floral jewellery optional",
		bride_side_applicable=1,
		bride_side_male_dress="Pink or orange bandhgala",
		bride_side_female_dress="Pink or orange lehenga - avoid mustard, that's the groom side's colour",
		notes="Colour-blocked by side so photos read clearly - groom side in yellow/green, bride side in pink/orange.",
	)
	ensure_dress_code(
		"dgv6h5v7mm",  # Reception (Hotel White Season)
		groom_side_applicable=1,
		groom_side_male_dress="Black tuxedo or indo-western bandhgala",
		groom_side_female_dress="Pastel gown or elegant saree",
		bride_side_applicable=1,
		bride_side_male_dress="Black or navy bandhgala",
		bride_side_female_dress="Pastel saree or gown, coordinated with groom side",
		notes="Formal, coordinated pastel/black palette across both sides.",
	)

	frappe.db.commit()
	print("CHECKPOINT 9: dress code plans seeded for Mehndi and Reception")

	# ==================================================================
	# 20. Bug fix: 4 of the original vendors carry a vendor_type value
	#     that predates WD Vendor Type becoming a Link field - stale
	#     free text that doesn't match any current master row. Harmless
	#     until something calls doc.save() on one of them (as the new
	#     vendor-documents sidebar does), which then throws
	#     LinkValidationError and blocks the save entirely. Normalise to
	#     the closest existing master value rather than adding new ones,
	#     since the two-vendor-type case (Sharma Sound & Events does both
	#     Sound and Light) has to collapse into one Link either way.
	# ==================================================================
	VENDOR_TYPE_FIXES = {
		"Raj Travels": "Transport",           # was "Tempo Traveller"
		"Flower Decor Studio": "Decorator",   # was "Decoration"
		"Sharma Sound & Events": "Sound",     # was "Sound & Lighting"
		"Royal Caterers": "Caterer",          # was "Catering"
	}
	for vendor_name, correct_type in VENDOR_TYPE_FIXES.items():
		name = frappe.db.get_value("WD Vendor", {"wedding": W, "vendor_name": vendor_name})
		if name and frappe.db.get_value("WD Vendor", name, "vendor_type") != correct_type:
			frappe.db.set_value("WD Vendor", name, "vendor_type", correct_type)

	frappe.db.commit()
	print("CHECKPOINT 10: stale vendor_type values normalised to the current master list")
	print("ALL DONE")

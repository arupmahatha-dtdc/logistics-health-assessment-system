import os
from datetime import datetime, date
import streamlit as st
import pandas as pd

from db import get_session, engine
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import Base, User, Survey, Response, CategoryScore, AIFeedback
from scoring import compute_question_score, compute_survey_scores
from ai import generate_feedback
from survey_definitions import FRAMEWORK
from mappings_loader import load_mappings, get_zones, get_regions, get_cities, get_branches

# Create tables on first run
Base.metadata.create_all(bind=engine)


LEVELS = ["Zone", "Region", "City", "Branch"]
LEVEL_INDEX = {lvl: idx for idx, lvl in enumerate(LEVELS)}


def _allowed_levels_for_role(user_role: str) -> list:
	if user_role == "Admin":
		return LEVELS
	start = LEVEL_INDEX.get(user_role, LEVEL_INDEX["Branch"])  # default deepest
	return LEVELS[start:]


def render_survey() -> None:
	st.title("Survey")
	# Row 1: Assessment level + Period
	col_lvl, col_period = st.columns([1,1])
	with col_lvl:
		user_role = st.session_state.get("user_role", "Branch")
		allowed_levels = _allowed_levels_for_role(user_role)
		default_index = 0  # first allowed is user's own level
		role_level = st.selectbox(
			"Assessment Level",
			options=allowed_levels,
			index=default_index,
			help="You can view lower levels. Submission is allowed only for your own level.",
		)
	with col_period:
		default_month_start = date.today().replace(day=1)
		period_date = st.date_input("Period (YYYY-MM)", value=default_month_start)
		period = period_date.strftime("%Y-%m")

	m = load_mappings()
	user_role = st.session_state.get("user_role")
	user_zone = st.session_state.get("user_zone_id")
	user_region = st.session_state.get("user_region_id")
	user_city = st.session_state.get("user_city_id")
	user_branch = st.session_state.get("user_branch_id")

	# Assessment level-based disabling of lower selectors
	disable_region_by_level = (role_level == "Zone")
	disable_city_by_level = (role_level in ["Zone", "Region"])
	disable_branch_by_level = (role_level in ["Zone", "Region", "City"])

	# Row 2: Zone / Region / City / Branch in one row with role-based restriction
	col_zone, col_region, col_city, col_branch = st.columns([1,1,1,1])
	# Zones (restrict by role)
	zones_all = get_zones(m)
	zones = zones_all
	if user_role in ["Zone","Region","City","Branch"] and user_zone:
		zones = [z for z in zones_all if z == user_zone]
	zone_default = zones[0] if zones else None
	with col_zone:
		zone = st.selectbox("Zone", options=zones, index=0 if zone_default in zones else 0, disabled=(user_role in ["Region","City","Branch"]))

	# Regions (restrict by role) + disabled by assessment level
	regions_all = get_regions(m, zone)
	regions = regions_all
	if user_role in ["Region","City","Branch"] and user_region:
		regions = [r for r in regions_all if r == user_region]
	region_default = regions[0] if regions else None
	with col_region:
		region = st.selectbox("Region", options=regions, index=0 if region_default in regions else 0, disabled=((user_role in ["City","Branch"]) or disable_region_by_level))

	# Cities (restrict by role) + disabled by assessment level
	cities_all = get_cities(m, zone, region)
	cities = cities_all
	if user_role in ["City","Branch"] and user_city:
		cities = [c for c in cities_all if c == user_city]
	city_default = cities[0] if cities else None
	with col_city:
		city = st.selectbox("City", options=cities, index=0 if city_default in cities else 0, disabled=((user_role in ["Branch"]) or disable_city_by_level))

	# Branches (restrict by role) + disabled by assessment level
	branches_all = get_branches(m, zone, region, city)
	branches = branches_all
	if user_role in ["Branch"] and user_branch:
		branches = [b for b in branches_all if b == user_branch]
	branch_default = branches[0] if branches else None
	with col_branch:
		branch = st.selectbox(
			"Branch (Code)",
			options=branches,
			index=0 if branch_default in branches else 0,
			format_func=lambda b: f"{b} - {m.get(zone, {}).get(region, {}).get(city, {}).get(b, '')}",
			disabled=disable_branch_by_level
		)

	# View-only if not user's own level (Admins are view-only by requirement)
	view_only = (role_level != user_role) or (user_role == "Admin")
	if view_only:
		st.info("Viewing data for a lower level. Inputs are disabled; submission is only allowed for your own level.")

	categories = FRAMEWORK.get(role_level, [])
	if not categories:
		st.error("Framework missing for this level.")
		return

	with st.form("survey_form"):
		st.caption("Enter actuals. Targets and scoring logic are predefined.")
		inputs = {}
		question_index = 0
		for cat in categories:
			st.subheader(f"{cat['name']}")
			for q in cat["questions"]:
				question_index += 1
				col1, col2 = st.columns([2,1])
				with col1:
					st.write(f"Q{question_index}. {q['text']}")
				with col2:
					val = st.number_input("Actual Value", min_value=0.0, value=0.0, key=f"act_{question_index}", label_visibility="collapsed", disabled=view_only)
					inputs[question_index] = {"actual": val, "target": q["target"], "formula": q["formula"], "weight": q["weight"], "cat_name": cat["name"]}
		sub = st.form_submit_button("Submit Survey", disabled=view_only)

	if not sub:
		return

	# Persist responses and computed scores
	with get_session() as db:
		survey = Survey(
			user_id=st.session_state["user_id"],
			role_level=role_level,
			period=period,
			zone_id=zone,
			region_id=region,
			city_id=city,
			branch_id=branch,
		)
		db.add(survey)
		db.flush()

		cat_scores = {}
		for idx, meta in inputs.items():
			act = float(meta["actual"]) if meta["actual"] is not None else 0.0
			target = float(meta["target"]) if meta["target"] is not None else 0.0
			is_lib = (meta["formula"] == "LIB")
			score = compute_question_score(act, target, lower_is_better=is_lib) if meta["formula"] != "RAW_PERCENT" else max(0.0, min(100.0, act))
			raw_val = act
			db.add(Response(survey_id=survey.id, question_id=idx, raw_value=raw_val, score=score))
			cat_scores.setdefault(meta["cat_name"], []).append((score, meta["weight"]))

		# Aggregate
		overall, per_cat = compute_survey_scores({i: v for i, v in enumerate(cat_scores.values(), start=1)})
		survey.overall_score = overall
		for cat_idx, _ in enumerate(categories, start=1):
			cscore = per_cat.get(cat_idx, 0.0)
			db.add(CategoryScore(survey_id=survey.id, category_id=cat_idx, category_score=cscore))

		# AI feedback
		fb_overall, fb_categories, fb_questions = generate_feedback(db, survey.id)
		for text in fb_questions:
			db.add(AIFeedback(survey_id=survey.id, level="question", feedback_text=text))
		for cid, text in fb_categories.items():
			db.add(AIFeedback(survey_id=survey.id, level="category", category_id=cid, feedback_text=text))
		db.add(AIFeedback(survey_id=survey.id, level="overall", feedback_text=fb_overall))

	st.success(f"Submitted. Overall score: {overall:.1f}")

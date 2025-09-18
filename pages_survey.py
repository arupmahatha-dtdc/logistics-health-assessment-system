import os
import time
from datetime import datetime, date
import streamlit as st
import pandas as pd
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

from db import get_session, engine, cleanup_connections, handle_db_error, get_session_with_retry
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


def _retry_db_operation(operation_func, max_retries=3, delay=1, operation_name="database operation"):
	"""Helper function for database operation retries with exponential backoff"""
	for attempt in range(max_retries):
		try:
			return operation_func()
		except (SQLAlchemyError, OperationalError, IntegrityError) as e:
			if attempt < max_retries - 1:
				st.warning(f"{operation_name} failed (attempt {attempt + 1}/{max_retries}): {handle_db_error(e, operation_name)}. Retrying in {delay} seconds...")
				time.sleep(delay)
				delay *= 2  # Exponential backoff
			else:
				st.error(f"Failed {operation_name} after {max_retries} attempts: {handle_db_error(e, operation_name)}")
				raise
		except Exception as e:
			if attempt < max_retries - 1:
				st.warning(f"Unexpected error during {operation_name} (attempt {attempt + 1}/{max_retries}): {str(e)}. Retrying in {delay} seconds...")
				time.sleep(delay)
				delay *= 2  # Exponential backoff
			else:
				st.error(f"Failed {operation_name} after {max_retries} attempts due to an unexpected error. Please try again.")
				raise


def _allowed_levels_for_role(user_role: str) -> list:
	if user_role == "Admin":
		return LEVELS
	start = LEVEL_INDEX.get(user_role, LEVEL_INDEX["Branch"])  # default deepest
	return LEVELS[start:]


def render_survey() -> None:
	st.title("Survey")
	
	user_id = st.session_state.get("user_id")
	user_role = st.session_state.get("user_role", "Branch")
	
	if not user_id:
		st.error("Please log in to fill the survey.")
		return
	
	# Only allow current month
	current_month = date.today().replace(day=1)
	period = current_month.strftime("%Y-%m")
	
	st.info(f"📅 Survey for {period} - Current Month Only")
	
	# Check if user already has a survey for this month with error handling
	existing_score = None
	try:
		with get_session() as db:
			existing_survey = db.query(Survey).filter(
				Survey.user_id == user_id,
				Survey.period == period
			).first()
			if existing_survey:
				existing_score = existing_survey.overall_score
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to check existing surveys: {handle_db_error(e, 'checking existing surveys')}")
		return
	except Exception as e:
		st.error("An unexpected error occurred while checking existing surveys. Please try again.")
		return
	
	if existing_survey:
		st.warning(f"⚠️ You have already filled the survey for {period}. You can edit it below.")
		edit_mode = st.checkbox("Edit existing survey", value=True)
	else:
		edit_mode = False
	
	# Row 1: Assessment level (read-only for current month)
	col_lvl, col_info = st.columns([1,1])
	with col_lvl:
		allowed_levels = _allowed_levels_for_role(user_role)
		role_level = st.selectbox(
			"Assessment Level",
			options=allowed_levels,
			index=0,  # first allowed is user's own level
			help="You can view lower levels. Submission is allowed only for your own level.",
			disabled=edit_mode  # Disable if editing
		)
	with col_info:
		if edit_mode and existing_score is not None:
			st.metric("Existing Score", f"{existing_score:.1f}/100")
		else:
			st.metric("Status", "New Survey")

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
					# Check if this is a binary question (yes/no)
					is_binary = "yes=" in q["text"].lower() and "no=" in q["text"].lower()
					
					if is_binary:
						val = st.selectbox(
							"Select Option", 
							options=[None, "Yes", "No"], 
							index=0,  # Default to None
							key=f"act_{question_index}", 
							label_visibility="collapsed", 
							disabled=view_only
						)
						# Convert to numeric: Yes=100, No=0, None=None
						if val == "Yes":
							val = 100.0
						elif val == "No":
							val = 0.0
						else:
							val = None
					else:
						val_str = st.text_input("Actual Value", key=f"act_{question_index}", label_visibility="collapsed", disabled=view_only)
						val = float(val_str) if val_str.strip() != "" else None
					inputs[question_index] = {"actual": val, "target": q["target"], "formula": q["formula"], "weight": q["weight"], "cat_name": cat["name"]}
		if edit_mode:
			sub = st.form_submit_button("Update Survey", disabled=view_only)
		else:
			sub = st.form_submit_button("Submit Survey", disabled=view_only)

	if not sub:
		return

	# Persist responses and computed scores using retry helper
	survey_id = None
	overall = None
	per_cat = None
	fb_overall = None
	
	def save_survey_operation():
		# First transaction: Save survey, responses, and category scores
		with get_session() as db:
			if edit_mode:
				# Update existing survey
				survey = db.query(Survey).filter(
					Survey.user_id == user_id,
					Survey.period == period
				).first()
				if not survey:
					st.error("Survey not found for editing.")
					return None, None, None, None
				
				# Delete existing responses and category scores with error handling
				try:
					db.query(Response).filter(Response.survey_id == survey.id).delete()
					db.query(CategoryScore).filter(CategoryScore.survey_id == survey.id).delete()
					db.query(AIFeedback).filter(AIFeedback.survey_id == survey.id).delete()
				except Exception as cleanup_error:
					st.warning(f"Warning: Could not clean up existing data: {handle_db_error(cleanup_error, 'cleaning up existing data')}")
			else:
				# Create new survey
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
				# Handle None values - skip questions that weren't answered
				if meta["actual"] is None:
					continue
					
				act = float(meta["actual"])
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
			
			# Store survey ID before session closes
			survey_id = survey.id
		
		# AI feedback generation - called after commit to avoid reading uncommitted data
		try:
			fb_overall, fb_categories, fb_questions = generate_feedback(survey_id)
		except Exception as ai_error:
			# Provide fallback feedback if AI generation fails
			st.warning(f"AI feedback generation failed: {str(ai_error)}")
			fb_overall = "AI feedback is temporarily unavailable. Please check back later for detailed analysis and recommendations."
			fb_categories = {}
			fb_questions = []
		
		# Second transaction: Save AI feedback
		with get_session() as db:
			for text in fb_questions:
				db.add(AIFeedback(survey_id=survey_id, level="question", feedback_text=text))
			for cid, text in fb_categories.items():
				db.add(AIFeedback(survey_id=survey_id, level="category", category_id=cid, feedback_text=text))
			db.add(AIFeedback(survey_id=survey_id, level="overall", feedback_text=fb_overall))
		
		# Return all needed values
		return survey_id, overall, per_cat, fb_overall

	# Use retry helper for the entire save operation
	try:
		result = _retry_db_operation(operation_func=save_survey_operation, max_retries=3, delay=1, operation_name='saving survey')
		if result is None:
			st.error("Failed to save survey: operation returned None")
			return
		survey_id, overall, per_cat, fb_overall = result
	except Exception as e:
		st.error(f"Failed to save survey: {str(e)}")
		return

	# Display detailed results
	if edit_mode:
		st.success("✅ Survey updated successfully!")
	else:
		st.success("✅ Survey submitted successfully!")
	
	# Show detailed scoring breakdown
	st.subheader("📊 Survey Results")
	
	# Overall score
	col1, col2, col3 = st.columns(3)
	with col1:
		st.metric("Overall Health Score", f"{overall:.1f}/100")
	with col2:
		answered_count = sum(1 for v in inputs.values() if v["actual"] is not None)
		st.metric("Questions Answered", f"{answered_count}")
	with col3:
		st.metric("Categories", f"{len(categories)}")
	
	# Category scores
	st.subheader("📈 Category Breakdown")
	for i, cat in enumerate(categories, 1):
		cat_score = per_cat.get(i, 0.0)
		col1, col2 = st.columns([3, 1])
		with col1:
			st.write(f"**{cat['name']}**")
		with col2:
			st.metric("Score", f"{cat_score:.1f}/100")
	
	# Question-level scores
	with st.expander("📋 Detailed Question Scores", expanded=False):
		question_index = 0
		for cat in categories:
			st.write(f"**{cat['name']}**")
			for q in cat["questions"]:
				question_index += 1
				if question_index in inputs and inputs[question_index]["actual"] is not None:
					act = inputs[question_index]["actual"]
					target = inputs[question_index]["target"]
					formula = inputs[question_index]["formula"]
					is_lib = (formula == "LIB")
					score = compute_question_score(act, target, lower_is_better=is_lib) if formula != "RAW_PERCENT" else max(0.0, min(100.0, act))
					
					col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
					with col1:
						st.write(f"Q{question_index}. {q['text']}")
					with col2:
						st.write(f"Actual: {act}")
					with col3:
						st.write(f"Target: {target}")
					with col4:
						st.write(f"Score: {score:.1f}")
	
	# AI Feedback
	st.subheader("🤖 AI Analysis & Recommendations")
	st.markdown(fb_overall)
	
	# Add to saved surveys
	st.session_state["last_survey_id"] = survey_id
	st.session_state["show_saved_surveys"] = True

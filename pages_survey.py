import time
from datetime import date
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

from db import get_session, engine, handle_db_error
from models import Base, Survey, Response, CategoryScore, AIFeedback
from scoring import compute_question_score, compute_survey_scores
from ai import generate_feedback
from survey_definitions import FRAMEWORK
from mappings_loader import load_mappings, get_zones, get_regions, get_cities, get_branches

# Create tables on first run
Base.metadata.create_all(bind=engine)




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


def _load_existing_responses(survey_id: int) -> dict:
	"""Load existing responses for a survey and return as question_id -> raw_value mapping"""
	try:
		with get_session() as db:
			responses = db.query(Response).filter(Response.survey_id == survey_id).all()
			return {response.question_id: response.raw_value for response in responses}
	except Exception as e:
		st.warning(f"Could not load existing responses: {handle_db_error(e, 'loading existing responses')}")
		return {}




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
	existing_survey_id = None
	try:
		with get_session() as db:
			existing_survey = db.query(Survey).filter(
				Survey.user_id == user_id,
				Survey.period == period
			).first()
			if existing_survey:
				existing_score = existing_survey.overall_score
				existing_survey_id = existing_survey.id
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to check existing surveys: {handle_db_error(e, 'checking existing surveys')}")
		return
	except Exception as e:
		st.error("An unexpected error occurred while checking existing surveys. Please try again.")
		return
	
	if existing_survey_id:
		st.warning(f"⚠️ You have already filled the survey for {period}. You can edit it below.")
		edit_mode = st.checkbox("Edit existing survey", value=True)
		
		# Load existing responses when in edit mode
		existing_responses = {}
		if edit_mode:
			existing_responses = _load_existing_responses(existing_survey_id)
	else:
		edit_mode = False
		existing_responses = {}
	
	# Row 1: Status display
	col_info = st.columns([1])[0]
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


	# Row 2: Zone / Region / City / Branch in one row with role-based restriction
	col_zone, col_region, col_city, col_branch = st.columns([1,1,1,1])
	# Zones (restrict by role)
	zones_all = get_zones(m)
	zones = zones_all
	if user_role in ["Zone","Region","City","Branch"] and user_zone:
		zones = [z for z in zones_all if z == user_zone]
	
	# After computing zones
	if not zones:
		st.error("No zones available for your assignment. Please contact the administrator.")
		return
	
	with col_zone:
		zone = st.selectbox("Zone", options=zones, index=0, disabled=(user_role in ["Region","City","Branch"]))

	# Regions (restrict by role)
	regions_all = get_regions(m, zone)
	regions = regions_all
	if user_role in ["Region","City","Branch"] and user_region:
		regions = [r for r in regions_all if r == user_region]
	
	# Repeat for regions based on selected zone
	if not regions:
		st.error("No regions available for the selected zone. Please contact the administrator.")
		return
	
	with col_region:
		region = st.selectbox("Region", options=regions, index=0, disabled=(user_role in ["City","Branch"]))

	# Cities (restrict by role)
	cities_all = get_cities(m, zone, region)
	cities = cities_all
	if user_role in ["City","Branch"] and user_city:
		cities = [c for c in cities_all if c == user_city]
	
	# Repeat for cities based on selected region
	if not cities:
		st.error("No cities available for the selected region. Please contact the administrator.")
		return
	
	with col_city:
		city = st.selectbox("City", options=cities, index=0, disabled=(user_role in ["Branch"]))

	# Branches (restrict by role)
	branches_all = get_branches(m, zone, region, city)
	branches = branches_all
	if user_role in ["Branch"] and user_branch:
		branches = [b for b in branches_all if b == user_branch]
	
	# Repeat for branches based on selected city
	if not branches:
		st.error("No branches available for the selected city. Please contact the administrator.")
		return
	
	with col_branch:
		branch = st.selectbox(
			"Branch (Code)",
			options=branches,
			index=0,
			format_func=lambda b: f"{b} - {m.get(zone, {}).get(region, {}).get(city, {}).get(b, '')}"
		)

	categories = FRAMEWORK.get(user_role, [])
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
						# Check for existing response and convert to selectbox index
						existing_value = existing_responses.get(question_index)
						if existing_value == 100.0:
							default_index = 1  # "Yes"
						elif existing_value == 0.0:
							default_index = 2  # "No"
						else:
							default_index = 0  # None
						
						val = st.selectbox(
							"Select Option", 
							options=[None, "Yes", "No"], 
							index=default_index,  # Pre-fill with existing value
							key=f"act_{question_index}", 
							label_visibility="collapsed"
						)
						# Convert to numeric: Yes=100, No=0, None=None
						if val == "Yes":
							val = 100.0
						elif val == "No":
							val = 0.0
						else:
							val = None
					else:
						# Check for existing response and pre-fill text input
						existing_value = existing_responses.get(question_index)
						default_value = str(existing_value) if existing_value is not None else ""
						
						val_str = st.text_input("Actual Value", value=default_value, key=f"act_{question_index}", label_visibility="collapsed")
						val = float(val_str) if val_str.strip() != "" else None
					inputs[question_index] = {"actual": val, "target": q["target"], "formula": q["formula"], "weight": q["weight"], "cat_name": cat["name"]}
		if edit_mode:
			sub = st.form_submit_button("Update Survey")
		else:
			sub = st.form_submit_button("Submit Survey")

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
				survey = db.query(Survey).filter(Survey.id == existing_survey_id).first()
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
				# derive authoritative locations
				role = st.session_state.get("user_role")
				zone_id = st.session_state.get("user_zone_id") if role in ["Zone","Region","City","Branch"] else zone
				region_id = st.session_state.get("user_region_id") if role in ["Region","City","Branch"] else region
				city_id = st.session_state.get("user_city_id") if role in ["City","Branch"] else city
				branch_id = st.session_state.get("user_branch_id") if role in ["Branch"] else branch
				
				# Optionally assert that any user-level-required ID exists, else st.error(...) and abort
				if role in ["Zone","Region","City","Branch"] and not zone_id:
					st.error("Zone ID is required for your role but not found in session. Please contact the administrator.")
					return None, None, None, None
				if role in ["Region","City","Branch"] and not region_id:
					st.error("Region ID is required for your role but not found in session. Please contact the administrator.")
					return None, None, None, None
				if role in ["City","Branch"] and not city_id:
					st.error("City ID is required for your role but not found in session. Please contact the administrator.")
					return None, None, None, None
				if role in ["Branch"] and not branch_id:
					st.error("Branch ID is required for your role but not found in session. Please contact the administrator.")
					return None, None, None, None
				
				# Create new survey
				survey = Survey(
					user_id=st.session_state["user_id"],
					role_level=role,
					period=period,
					zone_id=zone_id,
					region_id=region_id,
					city_id=city_id,
					branch_id=branch_id,
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

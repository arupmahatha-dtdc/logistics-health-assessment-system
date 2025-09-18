import streamlit as st
import pandas as pd
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
from datetime import datetime

from db import get_session, handle_db_error, get_session_with_retry
from models import Survey, CategoryScore, AIFeedback, Response, SurveyComment, User
from roles_utils import _allowed_child_roles
from survey_definitions import FRAMEWORK
 
from mappings_loader import load_mappings, get_zones, get_regions, get_cities, get_branches


def _scoped_query(db, user_id: int, role: str, z: str, r: str, c: str, b: str, include_subordinates: bool = False):
    q = db.query(Survey)
    # If not showing subordinates, always restrict to own surveys regardless of role
    if not include_subordinates:
        # Admin path is handled by callers with explicit user filter; fall back to own just in case
        return q.filter(Survey.user_id == user_id)

    # Admin viewing team surveys: apply provided geographic scope z/r/c/b if any
    if role in ("Admin", None, ""):
        if b:
            return q.filter((Survey.zone_id == z) & (Survey.region_id == r) & (Survey.city_id == c) & (Survey.branch_id == b))
        if c:
            return q.filter((Survey.zone_id == z) & (Survey.region_id == r) & (Survey.city_id == c))
        if r:
            return q.filter((Survey.zone_id == z) & (Survey.region_id == r))
        if z:
            return q.filter(Survey.zone_id == z)
        return q

    # Zone role: below-zone role levels only, further restricted by deeper selections if provided; include own surveys
    if role == "Zone":
        base = (Survey.zone_id == z) & Survey.role_level.in_(["Region", "City", "Branch"])
        if r:
            base = base & (Survey.region_id == r)
        if c:
            base = base & (Survey.city_id == c)
        if b:
            base = base & (Survey.branch_id == b)
        return q.filter((Survey.user_id == user_id) | base)

    # Region role: below-region levels only, accept deeper filters
    if role == "Region":
        base = (Survey.zone_id == z) & (Survey.region_id == r) & Survey.role_level.in_(["City", "Branch"])
        if c:
            base = base & (Survey.city_id == c)
        if b:
            base = base & (Survey.branch_id == b)
        return q.filter((Survey.user_id == user_id) | base)

    # City role: only branch level under the selected city, accept branch filter
    if role == "City":
        base = (Survey.zone_id == z) & (Survey.region_id == r) & (Survey.city_id == c) & (Survey.role_level == "Branch")
        if b:
            base = base & (Survey.branch_id == b)
        return q.filter((Survey.user_id == user_id) | base)

    # Branch and any other role: own surveys only
    return q.filter(Survey.user_id == user_id)


# _allowed_child_roles moved to roles_utils


def render_dashboard() -> None:
	st.title("📊 Dashboard")
	
	user_id = st.session_state.get("user_id")
	user_role = st.session_state.get("user_role")
	z = st.session_state.get("user_zone_id")
	r = st.session_state.get("user_region_id")
	c = st.session_state.get("user_city_id")
	b = st.session_state.get("user_branch_id")
	
	if not user_id:
		st.error("Please log in to view dashboard.")
		return
	
	# Team survey viewing options
	st.subheader("👥 Survey Viewing Options")
	if user_role != "Branch":
		show_team_surveys = st.checkbox(
			"Show surveys from my team", 
			help="Enable to view surveys from users below your hierarchy level"
		)
	else:
		show_team_surveys = False
		st.info("Branch users can only view their own surveys.")
	
	selected_user_id = None
	# Default selected geography to current user's assigned ids
	selected_zone = z
	selected_region = r
	selected_city = c
	selected_branch = b

	if show_team_surveys and user_role != "Branch":
		# Hierarchical geography filters scoped by current user's jurisdiction
		m = {}
		try:
			m = load_mappings()
		except Exception:
			m = {}
		# Zone selection
		zones_all = get_zones(m) if m else []
		zone_options = zones_all if user_role == "Admin" else ([z] if z else [])
		selected_zone = st.selectbox(
			"Zone",
			options=zone_options if zone_options else ["—"],
			index=((zones_all.index(z) if (user_role == "Admin" and isinstance(z, str) and z in zones_all) else 0) if zone_options else 0),
			disabled=(user_role != "Admin")
		)
		# Region selection
		regions_all = get_regions(m, selected_zone) if (isinstance(selected_zone, str) and selected_zone not in (None, "—")) else []
		if user_role in ["Admin", "Zone"]:
			region_scoped = regions_all
		else:
			region_scoped = [r] if r else []
		selected_region = st.selectbox(
			"Region",
			options=region_scoped if region_scoped else ["—"],
			index=0 if region_scoped else 0,
			disabled=(user_role not in ["Admin", "Zone"]) or (not region_scoped)
		)
		# City selection
		cities_all = get_cities(m, selected_zone, selected_region) if (isinstance(selected_region, str) and selected_region not in (None, "—")) else []
		if user_role in ["Admin", "Zone", "Region"]:
			city_scoped = cities_all
		else:
			city_scoped = [c] if c else []
		selected_city = st.selectbox(
			"City",
			options=city_scoped if city_scoped else ["—"],
			index=0 if city_scoped else 0,
			disabled=(user_role not in ["Admin", "Zone", "Region"]) or (not city_scoped)
		)
		# Branch selection
		branches_all = get_branches(m, selected_zone, selected_region, selected_city) if (isinstance(selected_city, str) and selected_city not in (None, "—")) else []
		branch_scoped = branches_all
		selected_branch = st.selectbox(
			"Branch (Code)",
			options=branch_scoped if branch_scoped else ["—"],
			index=0 if branch_scoped else 0,
			disabled=(user_role not in ["Admin", "Zone", "Region", "City"]) or (not branch_scoped),
			format_func=(lambda bid: (f"{bid} - {m.get(selected_zone, {}).get(selected_region, {}).get(selected_city, {}).get(bid, '')}" if bid not in ("—", "") else bid)),
		)

		# Build user list within selected scope and allowed roles
		available_users = []
		try:
			with get_session() as db:
				allowed_roles = _allowed_child_roles(user_role)
				user_query = db.query(User).filter(User.role.in_(allowed_roles))
				# Exclude self
				user_query = user_query.filter(User.id != user_id)
				# Apply geography depth based on deepest selected level
				if selected_branch and selected_branch not in ("—", None, ""):
					user_query = user_query.filter(
						(User.zone_id == selected_zone) & (User.region_id == selected_region) & (User.city_id == selected_city) & (User.branch_id == selected_branch)
					)
				elif selected_city and selected_city not in ("—", None, ""):
					user_query = user_query.filter(
						(User.zone_id == selected_zone) & (User.region_id == selected_region) & (User.city_id == selected_city)
					)
				elif selected_region and selected_region not in ("—", None, ""):
					user_query = user_query.filter(
						(User.zone_id == selected_zone) & (User.region_id == selected_region)
					)
				elif selected_zone and selected_zone not in ("—", None, ""):
					user_query = user_query.filter(User.zone_id == selected_zone)
				users = user_query.order_by(User.employee_id).all()
				available_users = [(u.id, f"{u.employee_id} - {u.name}") for u in users]
		except (SQLAlchemyError, OperationalError) as e:
			st.warning(f"Could not load team members: {handle_db_error(e, 'loading team members')}")
			available_users = []

		if available_users:
			user_options = [("all", "All users in selected scope")] + available_users
			selected_user_option = st.selectbox(
				"Select specific employee or view all:",
				options=[opt[0] for opt in user_options],
				format_func=lambda x: next(opt[1] for opt in user_options if opt[0] == x),
				help="Choose an employee or view all surveys from your scoped selection"
			)
			if selected_user_option != "all":
				selected_user_id = selected_user_option
		else:
			st.info("No team members found in the selected scope.")
			show_team_surveys = False
	
	# Month-Year Selection
	st.subheader("📅 Select Survey Period")
	
	# Get available periods with error handling
	try:
		with get_session() as db:
			periods_q = _scoped_query(db, user_id, user_role, selected_zone, selected_region, selected_city, selected_branch, include_subordinates=show_team_surveys)
			if selected_user_id:
				periods_q = periods_q.filter(Survey.user_id == selected_user_id)
			elif user_role == "Admin" and not show_team_surveys:
				periods_q = periods_q.filter(Survey.user_id == user_id)
			available_periods = (
				periods_q
				.with_entities(Survey.period)
				.distinct()
				.order_by(Survey.period.desc())
				.all()
			)
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load survey periods: {handle_db_error(e, 'loading survey periods')}")
		return
	except Exception as e:
		st.error(f"An unexpected error occurred while loading survey periods. Please try again.")
		return
	
	if not available_periods:
		st.info("No surveys found. Complete a survey to see your results here.")
		return
	
	# Create period options
	period_options = [p[0] for p in available_periods]
	selected_period = st.selectbox(
		"Choose a period:",
		options=period_options,
		index=0,  # Default to most recent
		help="Select the month-year to view survey results"
	)
	
	# Get the selected survey with comprehensive error handling
	try:
		with get_session() as db:
			query = _scoped_query(db, user_id, user_role, selected_zone, selected_region, selected_city, selected_branch, include_subordinates=show_team_surveys)
			query = query.filter(Survey.period == selected_period)
			
			# Add user filtering if specific user is selected
			if selected_user_id:
				query = query.filter(Survey.user_id == selected_user_id)
			elif user_role == "Admin" and not show_team_surveys:
				query = query.filter(Survey.user_id == user_id)
			
			selected_survey = query.order_by(Survey.created_at.desc()).first()
			
			if not selected_survey:
				st.error("No survey found for the selected period.")
				return
			
			# Extract survey data while session is open
			survey_data = {
				'id': selected_survey.id,
				'period': selected_survey.period,
				'overall_score': selected_survey.overall_score,
				'role_level': selected_survey.role_level,
				'zone_id': selected_survey.zone_id,
				'region_id': selected_survey.region_id,
				'city_id': selected_survey.city_id,
				'branch_id': selected_survey.branch_id,
				'created_at': selected_survey.created_at,
				'user_id': selected_survey.user_id
			}
			
			# Get survey details with fallback values
			try:
				responses = db.query(Response).filter(Response.survey_id == selected_survey.id).all()
			except Exception as e:
				st.warning(f"Could not load survey responses: {handle_db_error(e, 'loading responses')}")
				responses = []
			
			try:
				category_scores = db.query(CategoryScore).filter(CategoryScore.survey_id == selected_survey.id).all()
			except Exception as e:
				st.warning(f"Could not load category scores: {handle_db_error(e, 'loading category scores')}")
				category_scores = []
			
			try:
				ai_feedback = db.query(AIFeedback).filter(AIFeedback.survey_id == selected_survey.id, AIFeedback.level == "overall").first()
			except Exception as e:
				st.warning(f"Could not load AI feedback: {handle_db_error(e, 'loading AI feedback')}")
				ai_feedback = None
			
			# Get survey creator info with fallback
			try:
				survey_creator = db.query(User).filter(User.id == selected_survey.user_id).first()
				if survey_creator:
					creator_name = (survey_creator.name or "").strip() or "Unknown"
					creator_role = survey_creator.role or "Unknown"
					creator_location = f"{survey_creator.zone_id}-{survey_creator.region_id}-{survey_creator.city_id}-{survey_creator.branch_id}"
				else:
					creator_name = "Unknown"
					creator_role = "Unknown"
					creator_location = "Unknown"
			except Exception as e:
				st.warning(f"Could not load survey creator info: {handle_db_error(e, 'loading creator info')}")
				creator_name = "Unknown"
				creator_role = "Unknown"
				creator_location = "Unknown"
			
			# Get comments with user info and error handling
			comments_data = []
			try:
				comments = db.query(SurveyComment).filter(SurveyComment.survey_id == selected_survey.id).order_by(SurveyComment.created_at.desc()).all()
				for comment in comments:
					try:
						comment_author = db.query(User).filter(User.id == comment.user_id).first()
						comments_data.append({
							'id': comment.id,
							'comment': comment.comment,
							'created_at': comment.created_at,
							'author_name': ((comment_author.name or "").strip() if comment_author else "") or "Unknown"
						})
					except Exception as e:
						# Add comment without author info if user lookup fails
						comments_data.append({
							'id': comment.id,
							'comment': comment.comment,
							'created_at': comment.created_at,
							'author_name': "Unknown"
						})
			except Exception as e:
				st.warning(f"Could not load comments: {handle_db_error(e, 'loading comments')}")
				comments_data = []
			
			# Extract all data while session is open
			ai_feedback_text = ai_feedback.feedback_text if ai_feedback else None
			
			# Extract category scores data
			category_data = []
			for cs in category_scores:
				category_data.append({
					"Category": f"Category {cs.category_id}",
					"Score": f"{cs.category_score:.1f}/100"
				})
			
			# Extract responses data
			question_data = []
			for response in responses:
				question_data.append({
					"Question ID": response.question_id,
					"Raw Value": response.raw_value,
					"Score": f"{response.score:.1f}/100"
				})
				
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load survey data: {handle_db_error(e, 'loading survey data')}")
		return
	except Exception as e:
		st.error(f"An unexpected error occurred while loading survey data. Please try again.")
		return
	
	# Display survey results
	st.subheader(f"📋 Survey Results - {survey_data['period']}")
	
	# Survey header with key metrics
	col1, col2, col3, col4 = st.columns(4)
	with col1:
		st.metric("Overall Score", f"{survey_data['overall_score']:.1f}/100")
	with col2:
		st.metric("Level", survey_data['role_level'])
	with col3:
		st.metric("Location", f"{survey_data['zone_id']}-{survey_data['region_id']}-{survey_data['city_id']}-{survey_data['branch_id']}")
	with col4:
		st.metric("Date", survey_data['created_at'].strftime("%Y-%m-%d"))
	
	# Survey creator info
	if show_team_surveys and survey_data['user_id'] != user_id:
		st.info(f"👤 Survey filled by: **{creator_name}** ({creator_role} - {creator_location})")
	else:
		st.info(f"👤 Survey filled by: **{creator_name}**")
	
	# Category scores
	st.subheader("📈 Category Breakdown")
	if category_data:
		df_cats = pd.DataFrame(category_data)
		st.dataframe(df_cats, use_container_width=True)
	
	# Question-level scores (collapsible)
	with st.expander("📋 Detailed Question Scores", expanded=False):
		if question_data:
			df_questions = pd.DataFrame(question_data)
			st.dataframe(df_questions, use_container_width=True)
	
	# AI Feedback
	st.subheader("🤖 AI Analysis & Recommendations")
	if ai_feedback_text:
		st.markdown(ai_feedback_text)
	else:
		st.info("AI feedback will appear after submitting a survey.")
	
	# Comments Section
	st.subheader("💬 Comments & Feedback")
	
	# Check if user can add comments (if they filled this survey or have hierarchy access)
	can_comment = (survey_data['user_id'] == user_id) or (user_role in ["Admin", "Zone", "Region", "City"])
	
	if can_comment:
		with st.form("comment_form"):
			new_comment = st.text_area("Add a comment:", placeholder="Share your thoughts about this survey...")
			submit_comment = st.form_submit_button("Add Comment")
			
			if submit_comment and new_comment.strip():
				try:
					with get_session() as db:
						comment = SurveyComment(
							survey_id=survey_data['id'],
							user_id=user_id,
							comment=new_comment.strip()
						)
						db.add(comment)
					st.success("Comment added successfully!")
					st.rerun()
				except (SQLAlchemyError, OperationalError, IntegrityError) as e:
					st.error(f"Failed to add comment: {handle_db_error(e, 'adding comment')}")
				except Exception as e:
					st.error("An unexpected error occurred while adding the comment. Please try again.")
	
	# Display existing comments
	if comments_data:
		st.write("**Previous Comments:**")
		for comment_data in comments_data:
			with st.container():
				st.markdown(f"**{comment_data['author_name']}** ({comment_data['created_at'].strftime('%Y-%m-%d %H:%M')})")
				st.write(comment_data['comment'])
				st.divider()
	else:
		st.info("No comments yet. Be the first to add one!")
	
	# Trend chart removed as per requirements

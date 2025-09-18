import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
from datetime import datetime

from db import get_session, handle_db_error, get_session_with_retry
from models import Survey, CategoryScore, AIFeedback, Response, SurveyComment, User
from survey_definitions import FRAMEWORK
from scoring import compute_question_score


def _scoped_query(db, user_id: int, role: str, z: str, r: str, c: str, b: str, include_subordinates: bool = False):
	q = db.query(Survey)
	if role in ("Admin", None, ""):
		return q  # Caller applies extra filters
	if not include_subordinates:
		return q.filter(Survey.user_id == user_id)
	if role == "Zone":
		return q.filter((Survey.user_id == user_id) | ((Survey.zone_id == z) & Survey.role_level.in_(["Region","City","Branch"])))
	if role == "Region":
		return q.filter((Survey.user_id == user_id) | ((Survey.zone_id == z) & (Survey.region_id == r) & Survey.role_level.in_(["City","Branch"])))
	if role == "City":
		return q.filter((Survey.user_id == user_id) | ((Survey.zone_id == z) & (Survey.region_id == r) & (Survey.city_id == c) & (Survey.role_level == "Branch")))
	# Branch
	return q.filter(Survey.user_id == user_id)


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
	available_users = []
	
	if show_team_surveys and user_role != "Branch":  # Branch users can only see their own surveys
		try:
			with get_session() as db:
				# Get users from subordinate levels
				user_query = db.query(User)
				if user_role == "Zone":
					user_query = user_query.filter(
						(User.zone_id == z) & 
						(User.role.in_(["Region", "City", "Branch"]))
					)
				elif user_role == "Region":
					user_query = user_query.filter(
						(User.zone_id == z) & 
						(User.region_id == r) & 
						(User.role.in_(["City", "Branch"]))
					)
				elif user_role == "City":
					user_query = user_query.filter(
						(User.zone_id == z) & 
						(User.region_id == r) & 
						(User.city_id == c) & 
						(User.role == "Branch")
					)
				
				# Exclude the current user
				user_query = user_query.filter(User.id != user_id)
				
				users = user_query.order_by(User.name).all()
				available_users = [(u.id, f"{u.name} ({u.role} - {u.zone_id}-{u.region_id}-{u.city_id}-{u.branch_id})") for u in users]
		except (SQLAlchemyError, OperationalError) as e:
			st.warning(f"Could not load team members: {handle_db_error(e, 'loading team members')}")
			available_users = []
		
		if available_users:
			# Add "All users in my hierarchy" option
			user_options = [("all", "All users in my hierarchy")] + available_users
			selected_user_option = st.selectbox(
				"Select specific user or view all:",
				options=[opt[0] for opt in user_options],
				format_func=lambda x: next(opt[1] for opt in user_options if opt[0] == x),
				help="Choose a specific user or view all surveys from your hierarchy"
			)
			if selected_user_option != "all":
				selected_user_id = selected_user_option
		else:
			st.info("No team members found in your hierarchy.")
			show_team_surveys = False
	
	# Month-Year Selection
	st.subheader("📅 Select Survey Period")
	
	# Get available periods with error handling
	try:
		with get_session() as db:
			periods_q = _scoped_query(db, user_id, user_role, z, r, c, b, include_subordinates=show_team_surveys)
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
			query = _scoped_query(db, user_id, user_role, z, r, c, b, include_subordinates=show_team_surveys)
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
	if show_team_surveys and selected_survey.user_id != user_id:
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
	
	# Recent trends (if multiple surveys exist) with error handling
	try:
		with get_session() as db:
			# Use hierarchy-based query for trends
			trends_query = _scoped_query(db, user_id, user_role, z, r, c, b, include_subordinates=show_team_surveys)
			trends_query = trends_query.with_entities(Survey.period, Survey.overall_score, Survey.created_at, Survey.user_id)
			
			# Filter by selected user if a specific user is chosen
			if show_team_surveys and selected_user_id and selected_user_id != "all":
				trends_query = trends_query.filter(Survey.user_id == selected_user_id)
			elif not show_team_surveys:
				# If not showing team surveys, only show user's own surveys
				trends_query = trends_query.filter(Survey.user_id == user_id)
			elif user_role == "Admin" and not show_team_surveys:
				trends_query = trends_query.filter(Survey.user_id == user_id)
			
			recent_surveys = trends_query.order_by(Survey.created_at.desc()).limit(6).all()
			# Convert to dictionaries while session is active
			trend_data = [{"period": s.period, "score": s.overall_score} for s in reversed(recent_surveys)]
	except (SQLAlchemyError, OperationalError) as e:
		st.warning(f"Could not load recent trends: {handle_db_error(e, 'loading recent trends')}")
		trend_data = []
	except Exception as e:
		st.warning("Could not load recent trends. Please try again.")
		trend_data = []
	
	if len(trend_data) > 1:
		# Update chart title based on what's being shown
		if show_team_surveys and selected_user_id and selected_user_id != "all":
			# Find the selected user's name
			try:
				with get_session() as db:
					selected_user = db.query(User).filter(User.id == selected_user_id).first()
					user_display_name = selected_user.name if selected_user else f"User {selected_user_id}"
			except:
				user_display_name = f"User {selected_user_id}"
			chart_title = f"Overall Score Trend - {user_display_name}"
		elif show_team_surveys:
			chart_title = "Overall Score Trend - All Team Members"
		else:
			chart_title = "Overall Score Trend - Your Surveys"
		
		st.subheader("📊 Recent Performance Trends")
		df_trend = pd.DataFrame(trend_data)
		fig = px.line(df_trend, x="period", y="score", markers=True, title=chart_title)
		st.plotly_chart(fig, use_container_width=True)

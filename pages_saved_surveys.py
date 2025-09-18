import streamlit as st
from datetime import datetime
import pandas as pd
import re
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

from db import get_session, handle_db_error
from models import Survey, Response, CategoryScore, AIFeedback, Task
from survey_definitions import FRAMEWORK
from scoring import compute_question_score


def render_saved_surveys() -> None:
	st.title("📚 Saved Surveys")
	
	user_id = st.session_state.get("user_id")
	user_role = st.session_state.get("user_role")
	
	if not user_id:
		st.error("Please log in to view saved surveys.")
		return
	
	# Get surveys with error handling
	try:
		with get_session() as db:
			# Get surveys based on user role and level
			query = db.query(Survey).filter(Survey.user_id == user_id)
			
			# For non-admin users, also show surveys from lower levels in their hierarchy
			if user_role != "Admin":
				user_zone = st.session_state.get("user_zone_id")
				user_region = st.session_state.get("user_region_id")
				user_city = st.session_state.get("user_city_id")
				user_branch = st.session_state.get("user_branch_id")
				
				# Add surveys from lower levels
				if user_role == "Zone":
					query = db.query(Survey).filter(
						(Survey.user_id == user_id) |
						((Survey.zone_id == user_zone) & (Survey.role_level.in_(["Region", "City", "Branch"])))
					)
				elif user_role == "Region":
					query = db.query(Survey).filter(
						(Survey.user_id == user_id) |
						((Survey.zone_id == user_zone) & (Survey.region_id == user_region) & (Survey.role_level.in_(["City", "Branch"])))
					)
				elif user_role == "City":
					query = db.query(Survey).filter(
						(Survey.user_id == user_id) |
						((Survey.zone_id == user_zone) & (Survey.region_id == user_region) & (Survey.city_id == user_city) & (Survey.role_level == "Branch"))
					)
			
			surveys = query.order_by(Survey.created_at.desc()).all()
			
			# Process surveys while session is still open
			if not surveys:
				st.info("No surveys found. Complete a survey to see it here.")
				return
			
			# Survey selection
			st.subheader("Select Survey to View")
			
			# Create survey options with details - extract attributes while session is open
			survey_options = []
			survey_data = {}  # Store survey data for later use
			for survey in surveys:
				# Extract all needed attributes while session is open
				option_text = f"{survey.period} - {survey.role_level} - Score: {survey.overall_score:.1f} - {survey.created_at.strftime('%Y-%m-%d %H:%M')}"
				survey_options.append((survey.id, option_text))
				survey_data[survey.id] = {
					'period': survey.period,
					'role_level': survey.role_level,
					'overall_score': survey.overall_score,
					'created_at': survey.created_at,
					'zone_id': survey.zone_id,
					'region_id': survey.region_id,
					'city_id': survey.city_id,
					'branch_id': survey.branch_id
				}
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load surveys: {handle_db_error(e, 'loading surveys')}")
		return
	except Exception as e:
		st.error("An unexpected error occurred while loading surveys. Please try again.")
		return
	
	# Move the selectbox outside of the database session
	selected_survey_id = st.selectbox(
		"Choose a survey:",
		options=[opt[0] for opt in survey_options],
		format_func=lambda x: next(opt[1] for opt in survey_options if opt[0] == x)
	)
	
	if not selected_survey_id:
		return
	
	# Display selected survey details with error handling
	try:
		with get_session() as db:
			# Get survey data and convert to serializable dictionaries while session is open
			responses_orm = db.query(Response).filter(Response.survey_id == selected_survey_id).all()
			category_scores_orm = db.query(CategoryScore).filter(CategoryScore.survey_id == selected_survey_id).all()
			ai_feedback_orm = db.query(AIFeedback).filter(AIFeedback.survey_id == selected_survey_id).all()
			tasks_orm = db.query(Task).filter(Task.survey_id == selected_survey_id).all()
			
			# Convert ORM objects to serializable dictionaries
			responses_data = [
				{
					"question_id": r.question_id,
					"raw_value": r.raw_value,
					"score": r.score,
					"survey_id": r.survey_id
				}
				for r in responses_orm
			]
			
			category_scores_data = [
				{
					"category_id": cs.category_id,
					"category_score": cs.category_score,
					"survey_id": cs.survey_id
				}
				for cs in category_scores_orm
			]
			
			ai_feedback_data = [
				{
					"level": af.level,
					"feedback_text": af.feedback_text,
					"category_id": af.category_id,
					"survey_id": af.survey_id
				}
				for af in ai_feedback_orm
			]
			
			tasks_data = [
				{
					"id": t.id,
					"description": t.description,
					"status": t.status,
					"created_at": t.created_at,
					"updated_at": t.updated_at,
					"survey_id": t.survey_id
				}
				for t in tasks_orm
			]
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load survey details: {handle_db_error(e, 'loading survey details')}")
		return
	except Exception as e:
		st.error("An unexpected error occurred while loading survey details. Please try again.")
		return
	
	# Get survey data from stored data
	survey_info = survey_data[selected_survey_id]
	
	# Survey header
	st.subheader(f"📊 Survey Details - {survey_info['period']}")
	
	col1, col2, col3, col4 = st.columns(4)
	with col1:
		st.metric("Overall Score", f"{survey_info['overall_score']:.1f}/100")
	with col2:
		st.metric("Level", survey_info['role_level'])
	with col3:
		st.metric("Location", f"{survey_info['zone_id']}-{survey_info['region_id']}-{survey_info['city_id']}-{survey_info['branch_id']}")
	with col4:
		st.metric("Date", survey_info['created_at'].strftime("%Y-%m-%d"))
	
	# Tabs for different views
	tab1, tab2, tab3, tab4 = st.tabs(["📈 Results", "🤖 AI Analysis", "📋 Recommendations", "📊 Data Export"])
	
	with tab1:
		# Category scores
		st.subheader("Category Breakdown")
		cat_data = []
		for cs in category_scores_data:
			cat_data.append({
				"Category": f"Category {cs['category_id']}",
				"Score": f"{cs['category_score']:.1f}/100"
			})
		
		if cat_data:
			df_cats = pd.DataFrame(cat_data)
			st.dataframe(df_cats, use_container_width=True)
		
		# Question-level details
		with st.expander("📋 Question-Level Results", expanded=False):
			question_data = []
			for r in responses_data:
				question_data.append({
					"Question ID": r['question_id'],
					"Raw Value": r['raw_value'],
					"Score": f"{r['score']:.1f}/100"
				})
			
			if question_data:
				df_questions = pd.DataFrame(question_data)
				st.dataframe(df_questions, use_container_width=True)
	
	with tab2:
		# AI Feedback
		st.subheader("AI Analysis & Recommendations")
		overall_feedback = next((fb['feedback_text'] for fb in ai_feedback_data if fb['level'] == "overall"), "No AI feedback available.")
		st.markdown(overall_feedback)
	
	with tab3:
		# Recommendation tracking
		st.subheader("📋 Recommendation Status Tracking")
		
		# Add new recommendation
		with st.expander("➕ Add New Recommendation", expanded=False):
			with st.form("add_recommendation"):
				new_desc = st.text_area("Recommendation Description")
				new_status = st.selectbox("Status", ["Planned", "Executed", "Completed"])
				submit_rec = st.form_submit_button("Add Recommendation")
				
				if submit_rec and new_desc:
					try:
						with get_session() as db:
							new_task = Task(
								survey_id=selected_survey_id,
								description=new_desc,
								status=new_status
							)
							db.add(new_task)
						st.success("Recommendation added!")
						st.rerun()
					except (SQLAlchemyError, OperationalError, IntegrityError) as e:
						st.error(f"Failed to add recommendation: {handle_db_error(e, 'adding recommendation')}")
					except Exception as e:
						st.error("An unexpected error occurred while adding the recommendation. Please try again.")
		
		# Display existing recommendations
		if tasks_data:
			st.write("**Current Recommendations:**")
			for i, task in enumerate(tasks_data):
				with st.container():
					col1, col2, col3 = st.columns([3, 1, 1])
					with col1:
						st.write(f"**{i+1}.** {task['description']}")
					with col2:
						# Status update
						new_status = st.selectbox(
							"Status",
							["Planned", "Executed", "Completed"],
							index=["Planned", "Executed", "Completed"].index(task['status']),
							key=f"status_{task['id']}"
						)
						if new_status != task['status']:
							try:
								with get_session() as db:
									db_task = db.query(Task).filter(Task.id == task['id']).first()
									if db_task:
										db_task.status = new_status
										db_task.updated_at = datetime.utcnow()
								st.rerun()
							except (SQLAlchemyError, OperationalError) as e:
								st.error(f"Failed to update task status: {handle_db_error(e, 'updating task status')}")
							except Exception as e:
								st.error("An unexpected error occurred while updating the task status. Please try again.")
					with col3:
						st.write(f"Updated: {task['updated_at'].strftime('%Y-%m-%d')}")
					st.divider()
		else:
			st.info("No recommendations added yet. Add recommendations from the AI analysis above.")
	
	with tab4:
		# Data export
		st.subheader("📊 Export Survey Data")
		
		# Initialize export_data to avoid NameError
		export_data = []
		
		# Export as CSV
		if st.button("📥 Export as CSV"):
			# Prepare data for export
			export_data = []
			for r in responses_data:
				export_data.append({
					"Question_ID": r['question_id'],
					"Raw_Value": r['raw_value'],
					"Score": r['score'],
					"Survey_ID": r['survey_id'],
					"Period": survey_info['period'],
					"Level": survey_info['role_level']
				})
			
			if export_data:
				df_export = pd.DataFrame(export_data)
				csv = df_export.to_csv(index=False)
				# Sanitize filename to avoid unsafe characters
				safe_period = re.sub(r'[^a-zA-Z0-9]', '_', survey_info['period'])
				safe_role_level = re.sub(r'[^a-zA-Z0-9]', '_', survey_info['role_level'])
				st.download_button(
					label="Download CSV",
					data=csv,
					file_name=f"survey_{safe_period}_{safe_role_level}.csv",
					mime="text/csv"
				)
			else:
				st.warning("No data to export.")
		
		# Show raw data
		with st.expander("🔍 View Raw Data", expanded=False):
			if export_data:
				st.dataframe(pd.DataFrame(export_data), use_container_width=True)
			else:
				st.info("No data available.")

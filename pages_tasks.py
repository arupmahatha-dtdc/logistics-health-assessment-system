import streamlit as st
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
from db import get_session, handle_db_error
from models import Task, Survey


def _scoped_query(db, role: str, z: str, r: str, c: str, b: str):
	q = db.query(Survey)
	if role == "Admin" or role in (None, ""):
		return q
	if role == "Zone":
		return q.filter(Survey.zone_id == z)
	if role == "Region":
		return q.filter(Survey.zone_id == z, Survey.region_id == r)
	if role == "City":
		return q.filter(Survey.zone_id == z, Survey.region_id == r, Survey.city_id == c)
	return q.filter(Survey.zone_id == z, Survey.region_id == r, Survey.city_id == c, Survey.branch_id == b)


def render_tasks() -> None:
	st.title("Action Items")
	role = st.session_state.get("user_role")
	z = st.session_state.get("user_zone_id")
	r = st.session_state.get("user_region_id")
	c = st.session_state.get("user_city_id")
	b = st.session_state.get("user_branch_id")
	
	# Get surveys with error handling
	try:
		with get_session() as db:
			surveys = _scoped_query(db, role, z, r, c, b).order_by(Survey.created_at.desc()).limit(12).all()
			# Extract survey data while session is active to prevent detached instance access
			survey_data = []
			for s in surveys:
				survey_data.append({
					'id': s.id,
					'period': s.period,
					'role_level': s.role_level,
					'overall_score': s.overall_score
				})
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load surveys: {handle_db_error(e, 'loading surveys')}")
		return
	except Exception as e:
		st.error("An unexpected error occurred while loading surveys. Please try again.")
		return
	
	if not survey_data:
		st.info("No surveys yet in your scope. Submit a survey first.")
		return
	
	# Create selectbox options from extracted data
	survey_options = [(s['id'], f"Survey #{s['id']} - {s['period']} - {s['role_level']} - Score: {s['overall_score']:.1f}") for s in survey_data]
	selected_survey = st.selectbox("Select survey", options=[opt[0] for opt in survey_options], format_func=lambda x: next(opt[1] for opt in survey_options if opt[0] == x))
	
	if not selected_survey:
		return
	
	# Get tasks with error handling
	try:
		with get_session() as db:
			tasks = db.query(Task).filter(Task.survey_id == selected_survey).all()
			# Extract task data while session is active
			task_data = []
			for t in tasks:
				task_data.append({
					'id': t.id,
					'description': t.description,
					'status': t.status
				})
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load tasks: {handle_db_error(e, 'loading tasks')}")
		return
	except Exception as e:
		st.error("An unexpected error occurred while loading tasks. Please try again.")
		return
	
	# Add new task
	if st.button("Add task"):
		desc = st.text_input("Task description", key="new_task_desc")
		if desc:
			try:
				with get_session() as db:
					db.add(Task(survey_id=selected_survey, description=desc, status="Planned"))
				st.success("Task added")
				st.rerun()
			except (SQLAlchemyError, OperationalError, IntegrityError) as e:
				st.error(f"Failed to add task: {handle_db_error(e, 'adding task')}")
			except Exception as e:
				st.error("An unexpected error occurred while adding the task. Please try again.")
	
	# Display tasks
	if task_data:
		for task in task_data:
			col1, col2 = st.columns([4,2])
			with col1:
				st.write(task['description'])
			with col2:
				new_status = st.selectbox("Status", options=["Planned","Completed","Pending"], index=["Planned","Completed","Pending"].index(task['status']), key=f"task_{task['id']}")
				if new_status != task['status']:
					try:
						with get_session() as db:
							# Load task fresh in the update session
							obj = db.query(Task).filter(Task.id == task['id']).first()
							if obj:
								obj.status = new_status
						st.success("Updated")
						st.rerun()
					except (SQLAlchemyError, OperationalError) as e:
						st.error(f"Failed to update task: {handle_db_error(e, 'updating task')}")
					except Exception as e:
						st.error("An unexpected error occurred while updating the task. Please try again.")
	else:
		st.info("No tasks for selected survey.")

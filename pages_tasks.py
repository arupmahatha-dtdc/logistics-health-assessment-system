import streamlit as st
from db import get_session
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
	with get_session() as db:
		surveys = _scoped_query(db, role, z, r, c, b).order_by(Survey.created_at.desc()).limit(12).all()
		survey_ids = [s.id for s in surveys]
	if not survey_ids:
		st.info("No surveys yet in your scope. Submit a survey first.")
		return
	sid = st.selectbox("Select survey", options=survey_ids, format_func=lambda i: f"Survey #{i}")
	with get_session() as db:
		tasks = db.query(Task).filter(Task.survey_id == sid).all()
	if st.button("Add task"):
		desc = st.text_input("Task description", key="new_task_desc")
		if desc:
			with get_session() as db:
				db.add(Task(survey_id=sid, description=desc, status="Planned"))
				st.success("Task added")
				st.rerun()
	if tasks:
		for t in tasks:
			col1, col2 = st.columns([4,2])
			with col1:
				st.write(t.description)
			with col2:
				new_status = st.selectbox("Status", options=["Planned","Completed","Pending"], index=["Planned","Completed","Pending"].index(t.status), key=f"task_{t.id}")
				if new_status != t.status:
					with get_session() as db:
						obj = db.query(Task).get(t.id)
						obj.status = new_status
						st.success("Updated")
	else:
		st.info("No tasks for selected survey.")

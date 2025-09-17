import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy.orm import joinedload

from db import get_session
from models import Survey, CategoryScore, AIFeedback


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
	# Branch
	return q.filter(Survey.zone_id == z, Survey.region_id == r, Survey.city_id == c, Survey.branch_id == b)


def render_dashboard() -> None:
	st.title("Dashboard")
	user_role = st.session_state.get("user_role")
	z = st.session_state.get("user_zone_id")
	r = st.session_state.get("user_region_id")
	c = st.session_state.get("user_city_id")
	b = st.session_state.get("user_branch_id")
	# Materialize recent surveys in scope
	with get_session() as db:
		qs = (
			_scoped_query(db, user_role, z, r, c, b)
			.order_by(Survey.created_at.desc())
			.limit(12)
			.all()
		)
		surveys = [{"period": s.period, "overall_score": s.overall_score} for s in qs]
		fb = (
			db.query(AIFeedback)
			.filter(AIFeedback.level == "overall")
			.order_by(AIFeedback.created_at.desc())
			.first()
		)
		latest_fb = fb.feedback_text if fb else None

	st.subheader("Recent Overall Scores")
	if surveys:
		df = pd.DataFrame([{"period": s["period"], "score": s["overall_score"]} for s in reversed(surveys)])
		fig = px.line(df, x="period", y="score", markers=True)
		st.plotly_chart(fig, use_container_width=True)
	else:
		st.info("No survey data yet in your scope. Submit a survey to see trends.")

	st.subheader("Latest AI Overall Feedback")
	if latest_fb:
		st.write(latest_fb)
	else:
		st.info("AI feedback will appear after submitting a survey.")

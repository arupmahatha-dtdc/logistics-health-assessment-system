import streamlit as st

from pages_dashboard import render_dashboard
from pages_survey import render_survey
from pages_tasks import render_tasks
from pages_admin import render_admin


def route_to_page(page: str) -> None:
	if page == "Dashboard":
		render_dashboard()
	elif page == "Survey":
		render_survey()
	elif page == "Tasks":
		render_tasks()
	elif page == "Admin":
		render_admin()
	else:
		st.error("Unknown page")

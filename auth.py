import os
import time
import streamlit as st
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from db import get_session
from models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
	return pwd_context.verify(plain_password, password_hash)


def ensure_session() -> None:
	if "is_authenticated" not in st.session_state:
		st.session_state["is_authenticated"] = False
		st.session_state["user_id"] = None
		st.session_state["user_name"] = None
		st.session_state["user_role"] = None
		st.session_state["user_zone_id"] = None
		st.session_state["user_region_id"] = None
		st.session_state["user_city_id"] = None
		st.session_state["user_branch_id"] = None
		st.session_state["last_activity_ts"] = None


def login_user(user: User) -> None:
	st.session_state["is_authenticated"] = True
	st.session_state["user_id"] = user.id
	st.session_state["user_name"] = user.name
	st.session_state["user_role"] = user.role
	st.session_state["user_zone_id"] = user.zone_id
	st.session_state["user_region_id"] = user.region_id
	st.session_state["user_city_id"] = user.city_id
	st.session_state["user_branch_id"] = user.branch_id
	st.session_state["last_activity_ts"] = time.time()


def logout_user() -> None:
	for key in [
		"is_authenticated","user_id","user_name","user_role",
		"user_zone_id","user_region_id","user_city_id","user_branch_id","last_activity_ts"
	]:
		st.session_state.pop(key, None)
	ensure_session()


def render_login() -> None:
	st.title("Login")
	with st.form("login_form", clear_on_submit=False):
		employee_id = st.text_input("Employee ID")
		password = st.text_input("Password", type="password")
		submitted = st.form_submit_button("Login")
		if submitted:
			with get_session() as db:
				user = db.query(User).filter(User.employee_id == employee_id).first()
				if user and verify_password(password, user.password_hash):
					login_user(user)
					st.rerun()
				else:
					st.error("Invalid credentials")

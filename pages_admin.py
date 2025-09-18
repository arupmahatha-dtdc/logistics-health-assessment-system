import streamlit as st
from passlib.context import CryptContext
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

from db import get_session, handle_db_error, get_session_with_retry
from models import User, AuditLog
from mappings_loader import load_mappings, get_zones, get_regions, get_cities, get_branches

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_ORDER = {"Admin": 0, "Zone": 1, "Region": 2, "City": 3, "Branch": 4}


def _allowed_child_roles(current_role: str) -> list:
	if current_role == "Admin":
		return ["Admin", "Zone", "Region", "City", "Branch"]
	if current_role == "Zone":
		return ["Region", "City", "Branch"]
	if current_role == "Region":
		return ["City", "Branch"]
	if current_role == "City":
		return ["Branch"]
	return []


def _within_jurisdiction(u: User, current_role: str, cz: str, cr: str, cc: str) -> bool:
	# Admin sees all
	if current_role == "Admin":
		return True
	# Zone scope
	if current_role == "Zone":
		return (u.zone_id == cz)
	# Region scope
	if current_role == "Region":
		return (u.zone_id == cz and u.region_id == cr)
	# City scope
	if current_role == "City":
		return (u.zone_id == cz and u.region_id == cr and u.city_id == cc)
	return False


def render_admin() -> None:
	st.title("Admin")
	current_role = st.session_state.get("user_role")
	current_zone = st.session_state.get("user_zone_id")
	current_region = st.session_state.get("user_region_id")
	current_city = st.session_state.get("user_city_id")
	current_user_id = st.session_state.get("user_id")
	# Only Admin / Zone / Region / City can access
	if current_role not in ["Admin", "Zone", "Region", "City"]:
		st.error("Access denied")
		return

	st.subheader("Create / Update User")
	m = load_mappings()
	zones_all = get_zones(m)
	if not zones_all:
		st.error("No zones found in mappings.json")
		return

	# Scope geography options to current user's jurisdiction
	scoped_zones = zones_all if current_role == "Admin" else ([current_zone] if current_zone else [])

	# Row 1: Role + Zone (role options scoped to what current_role can manage)
	allowed_roles = _allowed_child_roles(current_role)
	# If Admin, allow picking Admin too; else exclude Admin/peers/above
	col_role, col_zone = st.columns([1,1])
	with col_role:
		role = st.selectbox("Role", options=allowed_roles, index=0 if allowed_roles else 0, help="Choose role for the user")
	with col_zone:
		if role == "Admin":
			zone = st.selectbox("Zone", options=["—"], index=0, disabled=True)
		else:
			zone = st.selectbox("Zone", options=scoped_zones, index=0 if scoped_zones else 0, disabled=(current_role != "Admin"))

	# Compute disabled flags from selected role
	disable_region = (role in ["Admin","Zone"])  # Region disabled for Admin/Zone
	disable_city = (role in ["Admin","Zone","Region"])  # City disabled for Admin/Zone/Region
	disable_branch = (role in ["Admin","Zone","Region","City"])  # Branch disabled except for Branch

	# Row 2: Region + City + Branch (scoped to jurisdiction)
	col_r, col_c, col_b = st.columns([1,1,1])
	regions_all = get_regions(m, zone) if (isinstance(zone, str) and zone not in (None, "—")) else []
	regions_scoped = regions_all if current_role in ["Admin", "Zone"] else ([current_region] if current_region else [])
	with col_r:
		if role in ["Admin", "Zone"]:
			region = st.selectbox("Region", options=["—"], index=0, disabled=True)
		else:
			region = st.selectbox("Region", options=(regions_scoped if regions_scoped else ["—"]), index=0, disabled=False if regions_scoped else True)
	cities_all = get_cities(m, zone, region) if (isinstance(region, str) and region not in (None, "—")) else []
	cities_scoped = cities_all if current_role in ["Admin", "Zone", "Region"] else ([current_city] if current_city else [])
	with col_c:
		if role in ["Admin", "Zone", "Region"]:
			city = st.selectbox("City", options=["—"], index=0, disabled=True)
		else:
			city = st.selectbox("City", options=(cities_scoped if cities_scoped else ["—"]), index=0, disabled=False if cities_scoped else True)
	branches = get_branches(m, zone, region, city) if (isinstance(city, str) and city not in (None, "—")) else []
	with col_b:
		if role in ["Admin", "Zone", "Region", "City"]:
			branch = st.selectbox("Branch (Code)", options=["—"], index=0, disabled=True)
		else:
			branch = st.selectbox(
				"Branch (Code)",
				options=branches if branches else ["—"],
				index=0,
				disabled=False if branches else True,
				format_func=(lambda b: (f"{b} - {m.get(zone, {}).get(region, {}).get(city, {}).get(b, '')}" if b not in ("—", "") else b)),
			)

	# Row 3: Name + Employee ID + Password inside the form
	with st.form("admin_user_form"):
		col_n, col_e, col_p = st.columns([1,1,1])
		with col_n:
			name = st.text_input("Name")
		with col_e:
			emp_id = st.text_input("Employee ID")
		with col_p:
			password = st.text_input("Password", type="password")
		sub = st.form_submit_button("Create/Update User")
		if sub:
			if not emp_id or not name or not role:
				st.error("Employee ID, Name and Role are required")
				st.stop()
			# Validate depth based on chosen role and selectors
			if role in ["Zone","Region","City","Branch"] and not zone:
				st.error("Please select a Zone")
				st.stop()
			if role in ["Region","City","Branch"] and (disable_region or region in (None, "—")):
				st.error("Please select a Region")
				st.stop()
			if role in ["City","Branch"] and (disable_city or city in (None, "—")):
				st.error("Please select a City")
				st.stop()
			if role == "Branch" and (disable_branch or branch in (None, "—")):
				st.error("Please select a Branch")
				st.stop()
			try:
				with get_session() as db:
					existing = db.query(User).filter(User.employee_id == emp_id).first()
					if not existing:
						user = User(employee_id=emp_id, name=name, role=role, password_hash=pwd.hash(password) if password else pwd.hash("ChangeMe@123"))
						db.add(user)
						action = "create_user"
					else:
						# Prevent elevating beyond current admin scope (except true Admin)
						if ROLE_ORDER[role] < ROLE_ORDER[current_role] and current_role != "Admin":
							st.error("Cannot assign a higher or equal role than your own")
							st.stop()
						existing.name = name
						existing.role = role
						if password:
							existing.password_hash = pwd.hash(password)
						user = existing
						action = "update_user"
					user.zone_id = None if role == "Admin" else zone
					user.region_id = None if role in ["Admin","Zone"] else region
					user.city_id = None if role in ["Admin","Zone","Region"] else city
					user.branch_id = None if role in ["Admin","Zone","Region","City"] else branch
					
					st.success("User created/updated")
			except (SQLAlchemyError, OperationalError, IntegrityError) as e:
				st.error(f"Failed to create/update user: {handle_db_error(e, 'creating/updating user')}")
			except Exception as e:
				st.error("An unexpected error occurred while creating/updating the user. Please try again.")
			
			# Audit log in separate transaction
			try:
				with get_session() as audit_sess:
					audit_sess.add(AuditLog(user_id=current_user_id, action=action, details=f"{emp_id}:{name}:{role}:{user.zone_id}/{user.region_id}/{user.city_id}/{user.branch_id}"))
			except Exception as e:
				st.warning(f"Audit log not recorded: {str(e)}")

	st.divider()
	st.subheader("User Management")
	role_display = {
		"Admin": "Admin",
		"Zone": "Zone Supervisor",
		"Region": "Region Supervisor",
		"City": "City Supervisor",
		"Branch": "Branch Supervisor",
	}
	role_order = ["Admin","Zone","Region","City","Branch"]
	try:
		with get_session() as db:
			# Fetch and filter users within jurisdiction 
			all_users = db.query(User).all()
			if st.session_state.get("user_id") and any(u.id == st.session_state["user_id"] and u.employee_id == "C32722" for u in all_users):
				# SuperAdmin can see everyone (including Admins and peers)
				users = all_users
			else:
				# Only users strictly below current role and within jurisdiction
				users = [
					u for u in all_users
					if (ROLE_ORDER.get(u.role, 99) > ROLE_ORDER.get(current_role, 0))
					and _within_jurisdiction(u, current_role, current_zone, current_region, current_city)
				]
	except (SQLAlchemyError, OperationalError) as e:
		st.error(f"Unable to load users: {handle_db_error(e, 'loading users')}")
		users = []
	except Exception as e:
		st.error("An unexpected error occurred while loading users. Please try again.")
		users = []
	
	if not users:
		st.info("No users in your scope.")
	else:
		# Group users by role (only roles you can see/manage)
		users_by_role = {r: [] for r in role_order}
		for u in users:
			users_by_role.setdefault(u.role, []).append(u)
		for r in role_order:
			group = users_by_role.get(r, [])
			if not group:
				continue
			st.markdown(f"### {role_display.get(r, r)} ({len(group)})")
			for u in group:
				friendly_role = role_display.get(u.role, u.role)
				with st.expander(f"{u.employee_id} — {u.name} ({friendly_role})", expanded=False):
					# Row A: Name + Employee ID (readonly) + New Password
					col_a1, col_a2, col_a3 = st.columns([1,1,1])
					with col_a1:
						new_name = st.text_input(f"Name — {u.employee_id}", value=u.name, key=f"name_{u.id}")
					with col_a2:
						emp_disp = st.text_input(f"Employee ID — {u.employee_id}", value=u.employee_id, key=f"emp_{u.id}", disabled=True)
					with col_a3:
						new_password = st.text_input(f"Password — {u.employee_id}", type="password", key=f"pwd_{u.id}")

					# Row B: Role + Zone (restrict role changes to allowed child roles)
					col_b1, col_b2 = st.columns([1,1])
					child_roles = _allowed_child_roles(current_role)
					with col_b1:
						new_role = st.selectbox(
							f"Role — {u.employee_id}",
							options=child_roles if current_role != "Admin" else role_order,
							index=(child_roles.index(u.role) if current_role != "Admin" and u.role in child_roles else role_order.index(u.role)),
							key=f"role_{u.id}"
						)
					zones_opts = get_zones(m) if current_role == "Admin" else [current_zone]
					cur_zone = u.zone_id if (u.zone_id in zones_opts) else (zones_opts[0] if zones_opts else "")
					with col_b2:
						if new_role == "Admin":
							z_sel = st.selectbox(f"Zone — {u.employee_id}", options=["—"], index=0, disabled=True)
						else:
							z_sel = st.selectbox(f"Zone — {u.employee_id}", options=zones_opts, index=(zones_opts.index(cur_zone) if cur_zone in zones_opts else 0), key=f"zone_{u.id}", disabled=(current_role != "Admin"))

					# Row C: Region + City + Branch (scoped)
					col_c1, col_c2, col_c3 = st.columns([1,1,1])
					regions_opts = get_regions(m, z_sel) if (isinstance(z_sel, str) and z_sel not in (None, "—")) else []
					if current_role == "Region":
						regions_opts = [current_region]
					with col_c1:
						if new_role in ["Admin", "Zone"]:
							r_sel = st.selectbox(f"Region — {u.employee_id}", options=["—"], index=0, disabled=True)
						else:
							r_sel = st.selectbox(f"Region — {u.employee_id}", options=regions_opts if regions_opts else ["—"], index=(0 if regions_opts else 0), key=f"region_{u.id}", disabled=(current_role in ["Region"]) or (not regions_opts))
					cities_opts = get_cities(m, z_sel, r_sel) if (isinstance(r_sel, str) and r_sel not in (None, "—")) else []
					if current_role == "City":
						cities_opts = [current_city]
					with col_c2:
						if new_role in ["Admin", "Zone", "Region"]:
							c_sel = st.selectbox(f"City — {u.employee_id}", options=["—"], index=0, disabled=True)
						else:
							c_sel = st.selectbox(f"City — {u.employee_id}", options=cities_opts if cities_opts else ["—"], index=(0 if cities_opts else 0), key=f"city_{u.id}", disabled=(current_role in ["City"]) or (not cities_opts))
					branches_opts = get_branches(m, z_sel, r_sel, c_sel) if (isinstance(c_sel, str) and c_sel not in (None, "—")) else []
					with col_c3:
						if new_role in ["Admin", "Zone", "Region", "City"]:
							b_sel = st.selectbox(f"Branch — {u.employee_id}", options=["—"], index=0, disabled=True)
						else:
							b_sel = st.selectbox(
								f"Branch — {u.employee_id}",
								options=branches_opts if branches_opts else ["—"],
								index=(0 if branches_opts else 0),
								key=f"branch_{u.id}",
								format_func=(lambda b: (f"{b} - {m.get(z_sel, {}).get(r_sel, {}).get(c_sel, {}).get(b, '')}" if b not in ("—", "") else b)),
							)

					# Actions (disallow changing to higher/equal role)
					col_d1, col_d2 = st.columns([1,1])
					with col_d1:
						if st.button("Save", key=f"save_{u.id}"):
							# SuperAdmin immutable
							if u.employee_id == "C32722":
								st.error("SuperAdmin cannot be modified")
							else:
								# Prevent assigning higher/equal role by non-admins
								if ROLE_ORDER[new_role] < ROLE_ORDER[current_role] and current_role != "Admin":
									st.error("Cannot assign a higher or equal role than your own")
								else:
									# If demoting an Admin, ensure at least one Admin remains
									try:
										with get_session() as tx:
											if u.role == "Admin" and new_role != "Admin":
												admins_count = tx.query(User).filter(User.role == "Admin").count()
												if admins_count <= 1:
													st.error("Cannot demote the last Admin")
													st.stop()
											u.name = new_name
											u.role = new_role
											if new_password:
												u.password_hash = pwd.hash(new_password)
											u.zone_id = None if new_role == "Admin" else z_sel
											u.region_id = None if new_role in ["Admin","Zone"] else r_sel
											u.city_id = None if new_role in ["Admin","Zone","Region"] else c_sel
											u.branch_id = None if new_role in ["Admin","Zone","Region","City"] else b_sel
											tx.merge(u)
										
										st.success("User updated")
										st.rerun()
									except (SQLAlchemyError, OperationalError, IntegrityError) as e:
										st.error(f"Failed to update user: {handle_db_error(e, 'updating user')}")
									except Exception as e:
										st.error("An unexpected error occurred while updating the user. Please try again.")
									
									# Audit log in separate transaction
									try:
										with get_session() as audit_sess:
											audit_sess.add(AuditLog(user_id=current_user_id, action="update_user", details=f"{u.employee_id}:{u.name}:{u.role}:{u.zone_id}/{u.region_id}/{u.city_id}/{u.branch_id}"))
									except Exception as e:
										st.warning(f"Audit log not recorded: {str(e)}")
					with col_d2:
						if st.button("Delete", type="secondary", key=f"del_{u.id}"):
							# SuperAdmin cannot be deleted; users cannot delete themselves
							if u.employee_id == "C32722":
								st.error("SuperAdmin cannot be deleted")
							elif u.id == current_user_id:
								st.error("You cannot delete yourself")
							else:
								try:
									with get_session() as tx:
										# Do not delete the last Admin
										if u.role == "Admin":
											admins_count = tx.query(User).filter(User.role == "Admin").count()
											if admins_count <= 1:
												st.error("Cannot delete the last Admin")
												st.stop()
										# Jurisdiction/role checks already applied by filtering; proceed
										tu_del = tx.query(User).get(u.id)
										tx.delete(tu_del)
									
									st.warning("User deleted")
									st.rerun()
								except (SQLAlchemyError, OperationalError, IntegrityError) as e:
									st.error(f"Failed to delete user: {handle_db_error(e, 'deleting user')}")
								except Exception as e:
									st.error("An unexpected error occurred while deleting the user. Please try again.")
								
								# Audit log in separate transaction
								try:
									with get_session() as audit_sess:
										audit_sess.add(AuditLog(user_id=current_user_id, action="delete_user", details=f"{u.employee_id}:{u.name}:{u.role}:{u.zone_id}/{u.region_id}/{u.city_id}/{u.branch_id}"))
								except Exception as e:
									st.warning(f"Audit log not recorded: {str(e)}")

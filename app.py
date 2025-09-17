import os
import time
import streamlit as st

from auth import ensure_session, render_login, logout_user
from pages_router import route_to_page
from mappings_loader import load_mappings

st.set_page_config(page_title="Logistics Health Assessment", layout="wide")

# Initialize session
ensure_session()

SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))

# Custom CSS for better navigation styling
st.markdown("""
<style>
.sidebar .stRadio > div {
    background-color: #f0f2f6;
    padding: 0.5rem;
    border-radius: 0.5rem;
    margin: 0.25rem 0;
}

.sidebar .stRadio > div > label {
    font-weight: 500;
    color: #1f2937;
}

.sidebar .stRadio > div > label:hover {
    background-color: #e5e7eb;
    border-radius: 0.25rem;
}

.user-info {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 1rem;
    border-radius: 0.5rem;
    margin: 0.5rem 0;
}

.session-timer {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    color: white;
    padding: 0.75rem;
    border-radius: 0.5rem;
    margin: 0.5rem 0;
    text-align: center;
    font-weight: bold;
    font-size: 1.1rem;
}

.hierarchy-info {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    padding: 0.75rem;
    border-radius: 0.5rem;
    margin: 0.5rem 0;
    font-size: 0.9rem;
}

.nav-button {
    width: 100%;
    margin: 0.25rem 0;
    padding: 0.75rem;
    border-radius: 0.5rem;
    border: none;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s ease;
}

.nav-button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
}
</style>
""", unsafe_allow_html=True)

# Sidebar navigation with timer
with st.sidebar:
	st.markdown("## 🏥 LogiHealth")
	st.markdown(":blue[Performance Assessment System]")
	
	if st.session_state.get("is_authenticated"):
		# User info with hierarchy
		user_name = st.session_state.get('user_name', '')
		user_role = st.session_state.get('user_role', '')
		zone_id = st.session_state.get('user_zone_id')
		region_id = st.session_state.get('user_region_id')
		city_id = st.session_state.get('user_city_id')
		branch_id = st.session_state.get('user_branch_id')
		
		# Load mappings to get names
		try:
			mappings = load_mappings()
			hierarchy_parts = []
			
			if user_role == "Admin":
				hierarchy_text = "Admin - Full Access"
			else:
				# For non-admin users, show their specific hierarchy
				if zone_id and zone_id in mappings:
					zone_name = zone_id  # You can add zone names to mappings if needed
					hierarchy_parts.append(f"Zone: {zone_name}")
					
					if region_id and region_id in mappings.get(zone_id, {}):
						region_name = region_id  # You can add region names to mappings if needed
						hierarchy_parts.append(f"Region: {region_name}")
						
						if city_id and city_id in mappings.get(zone_id, {}).get(region_id, {}):
							city_name = city_id  # You can add city names to mappings if needed
							hierarchy_parts.append(f"City: {city_name}")
							
							if branch_id and branch_id in mappings.get(zone_id, {}).get(region_id, {}).get(city_id, {}):
								branch_name = mappings.get(zone_id, {}).get(region_id, {}).get(city_id, {}).get(branch_id, branch_id)
								hierarchy_parts.append(f"Branch: {branch_name}")
				
				hierarchy_text = " -> ".join(hierarchy_parts) if hierarchy_parts else "No jurisdiction assigned"
		except:
			hierarchy_text = "Admin - Full Access" if user_role == "Admin" else "No jurisdiction assigned"
		
		st.markdown(f"""
		<div class="user-info">
			<strong>👤 {user_name}</strong><br>
			<small>Role: {user_role}</small><br>
			<small>{hierarchy_text}</small>
		</div>
		""", unsafe_allow_html=True)
		
		# Real-time session timer
		if st.session_state.get("last_activity_ts"):
			elapsed = int(time.time() - st.session_state["last_activity_ts"])
			remaining = max(0, SESSION_TIMEOUT_MINUTES*60 - elapsed)
			mins = remaining // 60
			secs = remaining % 60
			
			# Color coding based on remaining time
			if remaining < 300:  # Less than 5 minutes
				icon = "🔴"
				bg_color = "linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%)"
			elif remaining < 900:  # Less than 15 minutes
				icon = "🟡"
				bg_color = "linear-gradient(135deg, #feca57 0%, #ff9ff3 100%)"
			else:
				icon = "🟢"
				bg_color = "linear-gradient(135deg, #48dbfb 0%, #0abde3 100%)"
			
			# Create a container for the timer
			timer_container = st.container()
			with timer_container:
				st.markdown(f"""
				<div id="session-timer" style="
					background: {bg_color};
					color: white;
					padding: 0.75rem;
					border-radius: 0.5rem;
					margin: 0.5rem 0;
					text-align: center;
					font-weight: bold;
					font-size: 1.1rem;
				">
					{icon} Session: <span id="timer-display">{mins:02d}:{secs:02d}</span> remaining
				</div>
				""", unsafe_allow_html=True)
			
			# JavaScript for real-time countdown
			st.markdown(f"""
			<script>
			let remainingSeconds = {remaining};
			const timerElement = document.getElementById('timer-display');
			
			function updateTimer() {{
				if (remainingSeconds <= 0) {{
					timerElement.textContent = '00:00';
					return;
				}}
				
				const minutes = Math.floor(remainingSeconds / 60);
				const seconds = remainingSeconds % 60;
				timerElement.textContent = minutes.toString().padStart(2, '0') + ':' + seconds.toString().padStart(2, '0');
				remainingSeconds--;
			}}
			
			// Update immediately and then every second
			updateTimer();
			setInterval(updateTimer, 1000);
			</script>
			""", unsafe_allow_html=True)
		
		st.button("🚪 Logout", on_click=logout_user, type="secondary")
		st.divider()
		
		# Enhanced navigation
		st.markdown("### 🧭 Navigation")
		
		# Navigation options based on user role
		if user_role in ["Admin", "Zone", "Region", "City"]:
			nav_options = ["Dashboard","Survey","Tasks","Admin"]
			nav_format = {
				"Dashboard": "📊 Dashboard", 
				"Survey": "📝 Survey", 
				"Tasks": "✅ Tasks", 
				"Admin": "⚙️ Admin"
			}
		else:
			nav_options = ["Dashboard","Survey","Tasks"]
			nav_format = {
				"Dashboard": "📊 Dashboard", 
				"Survey": "📝 Survey", 
				"Tasks": "✅ Tasks"
			}
		
		page = st.radio("Select Page", 
			options=nav_options, 
			index=0,
			format_func=lambda x: nav_format[x],
			label_visibility="collapsed"
		)
	else:
		page = "Login"

# Route to pages
if page == "Login":
	render_login()
else:
	if not st.session_state.get("is_authenticated"):
		st.warning("Please login to continue.")
		render_login()
		st.stop()
	# session timeout check
	if st.session_state.get("last_activity_ts") and (time.time() - st.session_state["last_activity_ts"]) > (SESSION_TIMEOUT_MINUTES*60):
		st.info("Session expired due to inactivity. Please log in again.")
		logout_user()
		render_login()
		st.stop()
	st.session_state["last_activity_ts"] = time.time()
	
	route_to_page(page)

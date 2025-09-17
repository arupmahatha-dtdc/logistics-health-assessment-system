import os
from passlib.context import CryptContext

from db import engine, get_session
from models import Base, User

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def ensure_tables():
	Base.metadata.create_all(bind=engine)


def ensure_user(employee_id: str, name: str, role: str, password: str,
				zone_id: str = None, region_id: str = None, city_id: str = None, branch_id: str = None):
	with get_session() as db:
		user = db.query(User).filter(User.employee_id == employee_id).first()
		if user:
			user.name = name
			user.role = role
			if password:
				user.password_hash = pwd.hash(password)
			user.zone_id = zone_id
			user.region_id = region_id
			user.city_id = city_id
			user.branch_id = branch_id
		else:
			user = User(
				employee_id=employee_id,
				name=name,
				role=role,
				password_hash=pwd.hash(password),
				zone_id=zone_id,
				region_id=region_id,
				city_id=city_id,
				branch_id=branch_id,
			)
			db.add(user)


def main():
	ensure_tables()
	# Admin
	ensure_user(employee_id="admin", name="Administrator", role="Admin", password="Admin@123")
	# Zone supervisor
	ensure_user(employee_id="zone1", name="Zone Supervisor East", role="Zone", password="Zone@123", zone_id="East")
	# Region supervisor
	ensure_user(employee_id="region1", name="Region Supervisor CCU", role="Region", password="Region@123", zone_id="East", region_id="CCU")
	# City supervisor
	ensure_user(employee_id="city1", name="City Supervisor Kolkata", role="City", password="City@123", zone_id="East", region_id="CCU", city_id="KOLKATA")
	# Branch supervisor
	ensure_user(employee_id="branch1", name="Branch Supervisor MOULALI", role="Branch", password="Branch@123", zone_id="East", region_id="CCU", city_id="KOLKATA", branch_id="K01")
	# SuperAdmin
	ensure_user(employee_id="C32722", name="Arup Mahatha", role="Admin", password="#C32722@dtdc")
	print("Bootstrap completed. Users created: admin / zone1 / region1 / city1 / branch1")


if __name__ == "__main__":
	main()

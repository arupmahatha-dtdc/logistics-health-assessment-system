from datetime import datetime
from sqlalchemy import (
	Column, Integer, String, DateTime, ForeignKey, Float, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
	__tablename__ = "users"
	id = Column(Integer, primary_key=True)
	employee_id = Column(String(64), unique=True, nullable=False)
	name = Column(String(128), nullable=False)
	role = Column(String(32), nullable=False)  # Admin, Zone, Region, City, Branch
	zone_id = Column(String(64))
	region_id = Column(String(64))
	city_id = Column(String(64))
	branch_id = Column(String(64))
	password_hash = Column(String(255), nullable=False)
	created_at = Column(DateTime, default=datetime.utcnow)


default_level_weights = {
	"Zone": 1,
	"Region": 2,
	"City": 3,
	"Branch": 4,
}


class Category(Base):
	__tablename__ = "categories"
	id = Column(Integer, primary_key=True)
	name = Column(String(128), nullable=False)
	weight = Column(Float, nullable=False)  # percentage of total 0..100
	level = Column(String(32), nullable=False)  # Zone/Region/City/Branch
	__table_args__ = (UniqueConstraint("name", "level", name="uq_category_level"),)


class Question(Base):
	__tablename__ = "questions"
	id = Column(Integer, primary_key=True)
	category_id = Column(Integer)
	text = Column(Text, nullable=False)
	weight = Column(Float, nullable=False)  # percentage of total 0..100
	formula = Column(String(64), nullable=False)  # HIB/LIB/RAW_PERCENT
	is_lower_better = Column(Integer, default=0)


class Survey(Base):
	__tablename__ = "surveys"
	id = Column(Integer, primary_key=True)
	user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
	role_level = Column(String(32), nullable=False)  # Zone/Region/City/Branch
	period = Column(String(16), nullable=False)  # e.g., 2025-09
	overall_score = Column(Float)
	zone_id = Column(String(64))
	region_id = Column(String(64))
	city_id = Column(String(64))
	branch_id = Column(String(64))
	created_at = Column(DateTime, default=datetime.utcnow)


class Response(Base):
	__tablename__ = "responses"
	id = Column(Integer, primary_key=True)
	survey_id = Column(Integer, ForeignKey("surveys.id"), nullable=False)
	question_id = Column(Integer, nullable=False)  # index within framework
	raw_value = Column(Float)
	score = Column(Float)
	__table_args__ = (UniqueConstraint("survey_id", "question_id", name="uq_survey_question"),)


class CategoryScore(Base):
	__tablename__ = "category_scores"
	survey_id = Column(Integer, ForeignKey("surveys.id"), primary_key=True)
	category_id = Column(Integer, primary_key=True)  # index within framework for the level
	category_score = Column(Float)


class AIFeedback(Base):
	__tablename__ = "ai_feedback"
	id = Column(Integer, primary_key=True)
	survey_id = Column(Integer, ForeignKey("surveys.id"), nullable=False)
	level = Column(String(16), nullable=False)  # question/category/overall
	category_id = Column(Integer)
	question_id = Column(Integer)
	feedback_text = Column(Text, nullable=False)
	model = Column(String(64))
	prompt_hash = Column(String(64))
	created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
	__tablename__ = "tasks"
	id = Column(Integer, primary_key=True)
	survey_id = Column(Integer, ForeignKey("surveys.id"), nullable=False)
	description = Column(Text, nullable=False)
	status = Column(String(16), default="Planned")  # Planned, Completed, Pending
	updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
	__tablename__ = "audit_log"
	id = Column(Integer, primary_key=True)
	user_id = Column(Integer, ForeignKey("users.id"))
	action = Column(String(64), nullable=False)
	details = Column(Text)
	created_at = Column(DateTime, default=datetime.utcnow)

import os
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from openai import OpenAI

from db import get_session
from models import Survey, Response, CategoryScore, Question


client = None
model_name = None
if os.getenv("DEEPSEEK_API_KEY"):
	client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
	model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
elif os.getenv("OPENAI_API_KEY"):
	client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
	model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


SYSTEM_PROMPT = (
	"You are a logistics operations expert. Analyze KPI survey responses and provide actionable feedback."
)


def _format_prompt(db: Session, survey_id: int) -> str:
	s = db.query(Survey).filter(Survey.id == survey_id).first()
	responses = db.query(Response, Question).join(Question, Response.question_id == Question.id).filter(Response.survey_id == survey_id).all()
	lines = [f"Level: {s.role_level}", f"Period: {s.period}", f"Overall: {s.overall_score:.1f}"]
	for r, q in responses:
		lines.append(f"Q{q.id}: {q.text} -> score={r.score:.1f}")
	return "\n".join(lines)


def generate_feedback(db: Session, survey_id: int) -> Tuple[str, Dict[int, str], List[str]]:
	prompt = _format_prompt(db, survey_id)
	if client and model_name:
		msg = client.chat.completions.create(
			model=model_name,
			messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":prompt}],
			temperature=0.2,
		)
		text = msg.choices[0].message.content
		overall = text or "Overall feedback not available."
	else:
		overall = "Based on scores, prioritize low-scoring categories and maintain strengths."
	# Simple placeholders for category/question level
	cat_fb: Dict[int, str] = {}
	q_fb: List[str] = []
	return overall, cat_fb, q_fb

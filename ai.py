import os
import time
import logging
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from openai import OpenAI
from dotenv import load_dotenv
import requests
import json

from db import get_session, handle_db_error
from models import Survey, Response, CategoryScore, Question

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Client initialization moved to generate_feedback function to avoid module-level errors


SYSTEM_PROMPT = (
	"You are a logistics operations expert. Provide brief, technical analysis.\n\n"
	"Requirements:\n"
	"- Maximum 300 words\n"
	"- Plain text only (no code blocks, no boxes)\n"
	"- Focus on critical issues only\n"
	"- Be specific with metrics\n"
	"- Top 3 priorities maximum\n"
	"- Use simple bullet points\n\n"
	"Format: Use ## for headers and - for bullets only. No code formatting or special characters."
)


def _format_prompt(survey_id: int) -> str:
	"""Format prompt for AI analysis using its own database session"""
	try:
		with get_session() as db:
			s = db.query(Survey).filter(Survey.id == survey_id).first()
			if not s:
				logger.error(f"Survey {survey_id} not found")
				raise ValueError(f"Survey {survey_id} not found")
			
			responses = db.query(Response).filter(Response.survey_id == survey_id).all()
			category_scores = db.query(CategoryScore).filter(CategoryScore.survey_id == survey_id).all()
			
			# Build comprehensive prompt with all survey data
			lines = [
				f"# Logistics Health Assessment Analysis",
				f"**Assessment Level:** {s.role_level}",
				f"**Period:** {s.period}",
				f"**Location:** Zone={s.zone_id}, Region={s.region_id}, City={s.city_id}, Branch={s.branch_id}",
				f"**Overall Health Score:** {s.overall_score:.1f}/100",
				"",
				"## Category Scores:"
			]
			
			# Add category scores
			for cs in category_scores:
				lines.append(f"- Category {cs.category_id}: {cs.category_score:.1f}/100")
			
			lines.extend([
				"",
				"## Question-Level Results:"
			])
			
			# Add detailed question results
			for r in responses:
				lines.append(f"- Question {r.question_id}: Score={r.score:.1f}/100, Raw Value={r.raw_value}")
			
			lines.extend([
				"",
				"## Analysis Request:",
				"Provide a concise technical analysis focusing on:",
				"1. Critical performance gaps (scores < 70)",
				"2. Top 3 immediate action items with specific metrics",
				"3. Root cause analysis for low-performing areas",
				"4. Concrete improvement targets and timelines",
				"",
				"Keep response under 500 words. Use plain text format only."
			])
			
			return "\n".join(lines)
	except Exception as e:
		logger.error(f"Error formatting prompt for survey {survey_id}: {str(e)}")
		raise


def call_deepseek(prompt: str) -> str:
	"""
	Makes an API call to DeepSeek with robust error handling and retry logic.
	"""
	DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
	if not DEEPSEEK_API_KEY:
		logger.warning("DEEPSEEK_API_KEY not found in environment variables")
		raise ValueError("DEEPSEEK_API_KEY not found in environment variables")

	url = "https://api.deepseek.com/v1/chat/completions"
	headers = {
		"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
		"Content-Type": "application/json"
	}
	
	data = {
		"model": "deepseek-chat",
		"messages": [
			{"role": "system", "content": SYSTEM_PROMPT},
			{"role": "user", "content": prompt}
		],
		"temperature": 0.1,
		"max_tokens": 400
	}

	# Retry logic with exponential backoff
	max_retries = 3
	base_delay = 1
	
	for attempt in range(max_retries):
		try:
			logger.info(f"Making API call to DeepSeek (attempt {attempt + 1}/{max_retries})")
			
			# Add connection timeout and read timeout
			response = requests.post(
				url, 
				headers=headers, 
				json=data,
				timeout=(30, 60)  # (connection_timeout, read_timeout)
			)
			
			# Handle different HTTP status codes
			if response.status_code == 429:
				# Rate limiting
				retry_after = int(response.headers.get('Retry-After', 60))
				if attempt < max_retries - 1:
					logger.warning(f"Rate limited. Waiting {retry_after} seconds before retry...")
					time.sleep(retry_after)
					continue
				else:
					raise requests.exceptions.HTTPError(f"Rate limited after {max_retries} attempts")
			
			elif response.status_code >= 500:
				# Server errors
				if attempt < max_retries - 1:
					delay = base_delay * (2 ** attempt)
					logger.warning(f"Server error {response.status_code}. Retrying in {delay} seconds...")
					time.sleep(delay)
					continue
				else:
					raise requests.exceptions.HTTPError(f"Server error {response.status_code} after {max_retries} attempts")
			
			elif response.status_code == 401:
				# Authentication error - don't retry
				raise requests.exceptions.HTTPError("Authentication failed. Please check your API key.")
			
			response.raise_for_status()
			
			result = response.json()
			
			# Validate response structure
			if "choices" not in result or not result["choices"]:
				raise ValueError("Invalid response structure from API")
			
			content = result["choices"][0]["message"]["content"]
			logger.info("API call successful")
			return content
			
		except requests.exceptions.Timeout as e:
			if attempt < max_retries - 1:
				delay = base_delay * (2 ** attempt)
				logger.warning(f"Request timeout. Retrying in {delay} seconds...")
				time.sleep(delay)
				continue
			else:
				logger.error(f"Request timeout after {max_retries} attempts: {str(e)}")
				raise
		
		except requests.exceptions.ConnectionError as e:
			if attempt < max_retries - 1:
				delay = base_delay * (2 ** attempt)
				logger.warning(f"Connection error. Retrying in {delay} seconds...")
				time.sleep(delay)
				continue
			else:
				logger.error(f"Connection error after {max_retries} attempts: {str(e)}")
				raise
		
		except requests.exceptions.HTTPError as e:
			status = getattr(e, 'response', None).status_code if getattr(e, 'response', None) else None
			if status and 400 <= status < 500 and status != 429:
				logger.error(f"Client error {status}: {e}")
				raise
			# For other HTTP errors, retry
			if attempt < max_retries - 1:
				delay = base_delay * (2 ** attempt)
				logger.warning(f"HTTP error {status}. Retrying in {delay} seconds...")
				time.sleep(delay)
				continue
			else:
				logger.error(f"HTTP error after {max_retries} attempts: {str(e)}")
				raise
		
		except Exception as e:
			if attempt < max_retries - 1:
				delay = base_delay * (2 ** attempt)
				logger.warning(f"Unexpected error. Retrying in {delay} seconds: {str(e)}")
				time.sleep(delay)
				continue
			else:
				logger.error(f"Unexpected error after {max_retries} attempts: {str(e)}")
				raise
	
	# This should never be reached, but just in case
	raise Exception("Maximum retry attempts exceeded")


def generate_feedback(survey_id: int) -> Tuple[str, Dict[int, str], List[str]]:
	"""
	Generate AI feedback with graceful degradation when API is unavailable.
	Decoupled from caller's database session for better transaction isolation.
	"""
	try:
		prompt = _format_prompt(survey_id)
	except Exception as e:
		logger.error(f"Error formatting prompt for survey {survey_id}: {str(e)}")
		# Return fallback feedback if prompt generation fails
		return _get_fallback_feedback(), {}, []
	
	# Check for DeepSeek API key with graceful handling
	DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
	
	if not DEEPSEEK_API_KEY:
		logger.info("DEEPSEEK_API_KEY not found, using fallback feedback")
		return _get_fallback_feedback(), {}, []
	
	try:
		logger.info(f"Generating AI feedback for survey {survey_id}")
		overall = call_deepseek(prompt)
		logger.info("AI feedback generated successfully")
	except requests.exceptions.HTTPError as e:
		if "401" in str(e) or "Authentication" in str(e):
			logger.error("API authentication failed - check API key")
			overall = _get_fallback_feedback() + "\n\n*Note: API authentication failed. Please check your API key configuration.*"
		elif "429" in str(e) or "Rate limited" in str(e):
			logger.warning("API rate limited")
			overall = _get_fallback_feedback() + "\n\n*Note: API rate limit exceeded. Please try again later.*"
		else:
			logger.error(f"API HTTP error: {str(e)}")
			overall = _get_fallback_feedback() + f"\n\n*Note: API error occurred: {str(e)}*"
	except requests.exceptions.Timeout:
		logger.error("API request timeout")
		overall = _get_fallback_feedback() + "\n\n*Note: API request timed out. Please try again later.*"
	except requests.exceptions.ConnectionError:
		logger.error("API connection error")
		overall = _get_fallback_feedback() + "\n\n*Note: Unable to connect to AI service. Please check your internet connection.*"
	except Exception as e:
		logger.error(f"Unexpected error during AI feedback generation: {str(e)}")
		overall = _get_fallback_feedback() + f"\n\n*Note: Unexpected error occurred: {str(e)}*"
	
	# For now, return the comprehensive feedback as overall
	cat_fb: Dict[int, str] = {}
	q_fb: List[str] = []
	return overall, cat_fb, q_fb


def _get_fallback_feedback() -> str:
	"""
	Provides fallback feedback when AI service is unavailable.
	"""
	return """## Performance Analysis

**Critical Issues:**
- Review categories scoring below 70
- Implement daily performance tracking
- Address process inefficiencies immediately

**Top 3 Actions:**
1. Focus on lowest-scoring operational areas
2. Establish daily KPI monitoring
3. Implement corrective action plans

**Targets:**
- Achieve minimum 80% score across all categories
- Reduce process cycle times by 20%
- Improve accuracy metrics to 95%+

*Note: AI analysis temporarily unavailable. Configure API keys for detailed insights.*"""

import os
import logging
import time
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Build absolute path for SQLite DB to avoid cwd-related I/O errors
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Connection metrics
connection_metrics = {
    "successful_connections": 0,
    "failed_connections": 0,
    "last_connection_test": None,
    "session_durations": [],
    "query_counts": 0,
    "transaction_success_rate": 0.0,
    "pool_utilization": 0.0
}

engine = create_engine(
	DATABASE_URL,
	connect_args={
		"check_same_thread": False,
		"timeout": 30
	} if DATABASE_URL.startswith("sqlite") else {},
	pool_pre_ping=True,
	pool_recycle=3600,
	pool_timeout=30,
	pool_size=5,  # Optimized for Streamlit usage patterns
	max_overflow=10,  # Reduced for typical Streamlit concurrency
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_session():
	"""Enhanced session context manager with better error handling and logging"""
	session_start_time = time.time()
	session = SessionLocal()
	try:
		logger.debug("Database session created successfully")
		yield session
		session.commit()
		logger.debug("Database session committed successfully")
		connection_metrics["successful_connections"] += 1
		# Track session duration
		session_duration = time.time() - session_start_time
		connection_metrics["session_durations"].append(session_duration)
		# Keep only last 100 session durations for memory efficiency
		if len(connection_metrics["session_durations"]) > 100:
			connection_metrics["session_durations"] = connection_metrics["session_durations"][-100:]
	except SQLAlchemyError as e:
		session.rollback()
		logger.error(f"Database error occurred: {str(e)}")
		connection_metrics["failed_connections"] += 1
		raise
	except Exception as e:
		session.rollback()
		logger.error(f"Unexpected error in database session: {str(e)}")
		connection_metrics["failed_connections"] += 1
		raise
	finally:
		try:
			session.close()
			logger.debug("Database session closed successfully")
		except Exception as e:
			logger.error(f"Error closing database session: {str(e)}")


def cleanup_connections():
	"""Enhanced cleanup with more robust error handling and connection state checking"""
	try:
		logger.info("Starting database connection cleanup")
		
		# Log final metrics before cleanup
		total_connections = connection_metrics["successful_connections"] + connection_metrics["failed_connections"]
		if total_connections > 0:
			success_rate = connection_metrics["successful_connections"] / total_connections
			logger.info(f"Final connection metrics - Success rate: {success_rate:.2%}, Total sessions: {total_connections}")
		
		engine.dispose()
		logger.info("Database connections disposed successfully")
	except Exception as e:
		logger.error(f"Error during connection cleanup: {str(e)}")
		# Force cleanup even if there are errors
		try:
			engine.pool.dispose()
		except Exception as cleanup_error:
			logger.error(f"Error during forced cleanup: {str(cleanup_error)}")


def test_connection():
	"""Test database connectivity and return connection status"""
	try:
		with get_session() as session:
			# Simple query to test connection
			session.execute(text("SELECT 1"))
			connection_metrics["last_connection_test"] = time.time()
			logger.info("Database connection test successful")
			return True
	except Exception as e:
		logger.error(f"Database connection test failed: {str(e)}")
		connection_metrics["last_connection_test"] = time.time()
		return False


@contextmanager
def get_session_with_retry(max_retries=3, delay=1):
	"""Get database session with retry logic for transient failures.
	
	This context manager attempts to open a session with retries and yields it.
	Intended scope: acquire-only - provides a session that can be used within the context.
	"""
	for attempt in range(max_retries):
		try:
			with get_session() as session:
				yield session
			return  # Success, exit the retry loop
		except (OperationalError, SQLAlchemyError) as e:
			if attempt == max_retries - 1:
				logger.error(f"Failed to get database session after {max_retries} attempts: {str(e)}")
				raise
			logger.warning(f"Database session attempt {attempt + 1} failed, retrying in {delay} seconds: {str(e)}")
			time.sleep(delay)
			delay *= 2  # Exponential backoff
		except Exception as e:
			logger.error(f"Unexpected error getting database session: {str(e)}")
			raise


def handle_db_error(error, operation="database operation"):
	"""Centralized database error handling with user-friendly messages"""
	if isinstance(error, OperationalError):
		if "database is locked" in str(error).lower():
			return f"Database is temporarily busy. Please try again in a moment."
		elif "connection" in str(error).lower():
			return f"Database connection issue. Please refresh the page and try again."
		else:
			return f"Database operation failed. Please try again."
	elif isinstance(error, IntegrityError):
		return f"Data validation error. Please check your input and try again."
	elif isinstance(error, SQLAlchemyError):
		return f"Database error occurred during {operation}. Please try again."
	else:
		logger.error(f"Unexpected database error during {operation}: {str(error)}")
		return f"An unexpected error occurred during {operation}. Please try again."


def warm_connection_pool():
	"""Pre-warm the connection pool on application startup"""
	try:
		logger.info("Warming up database connection pool")
		with get_session() as session:
			session.execute(text("SELECT 1"))
		logger.info("Connection pool warmed up successfully")
		return True
	except Exception as e:
		logger.error(f"Failed to warm up connection pool: {str(e)}")
		return False


def monitor_pool_status():
	"""Monitor pool status and log warnings when utilization is high"""
	try:
		pool = engine.pool
		pool_size = pool.size()
		checked_in = pool.checkedin()
		checked_out = pool.checkedout()
		overflow = pool.overflow()
		
		utilization = (checked_out / (pool_size + overflow)) if (pool_size + overflow) > 0 else 0
		connection_metrics["pool_utilization"] = utilization
		
		if utilization > 0.8:  # 80% utilization threshold
			logger.warning(f"High pool utilization: {utilization:.1%} ({checked_out}/{pool_size + overflow})")
		
		return {
			"pool_size": pool_size,
			"checked_in": checked_in,
			"checked_out": checked_out,
			"overflow": overflow,
			"utilization": utilization
		}
	except Exception as e:
		logger.error(f"Error monitoring pool status: {str(e)}")
		return None



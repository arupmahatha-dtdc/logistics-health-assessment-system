import streamlit as st
import pandas as pd
import sqlite3
import json
import os
from datetime import datetime
import traceback
import ast
import math
import plotly.express as px

st.set_page_config(page_title="Facility Scoring Tool", layout="wide")

# --- Database helpers ---
DB_PATH = "submissions.db"

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def parse_float(text):
    try:
        return float(text) if isinstance(text, str) and text.strip() != "" else None
    except Exception:
        return None

def parse_int(text):
    try:
        return int(text) if isinstance(text, str) and text.strip() != "" else None
    except Exception:
        return None

def float_input(label: str, placeholder: str = "", key: str | None = None):
    # Provide an optional Streamlit key to avoid duplicate widget IDs when rendering
    # multiple inputs with identical labels in loops.
    raw = st.text_input(label, value="", placeholder=placeholder, key=key)
    return parse_float(raw)

def int_input(label: str, placeholder: str = "", key: str | None = None):
    raw = st.text_input(label, value="", placeholder=placeholder, key=key)
    return parse_int(raw)


def get_table_info(conn, table_name="submissions"):
    """
                        val = st.text_input(f" - {label}", value=(str(prefill_val) if prefill_val is not None else ""), key=key)
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info('{table_name}')")
    cols = {}
    for row in cur.fetchall():
        # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
        cid, name, typ, notnull, dflt_value, pk = row
        cols[name] = {"cid": cid, "type": typ, "notnull": notnull, "dflt_value": dflt_value, "pk": pk}
    return cols

def init_db():
    """
    Initialize the submissions DB.

    Behavior summary:
    - For fresh installs (no 'submissions' table): create a minimal current schema (no latitude/longitude).
      This prevents introducing unused columns for new deployments.
    - For existing DBs: perform best-effort ALTER TABLE additions for payload, facility_code, submission_month/year.
    - Additionally: detect legacy schemas where latitude and/or longitude exist with NOT NULL constraints.
      In that case, perform a one-time migration that relaxes the NOT NULL requirement while keeping the
      columns present for backward compatibility. Migration steps:
        1) BEGIN IMMEDIATE;
        2) CREATE a new table `submissions_new` with the desired (compatible) columns where latitude/longitude
           are nullable (REAL) and not declared NOT NULL.
        3) COPY data across including latitude/longitude.
        4) DROP old table and rename new to submissions.
        5) COMMIT.
      The migration is wrapped in try/except. On failure, it rolls back and surfaces the error.
    """

    conn = get_connection()
    cur = conn.cursor()

    # Check if submissions table exists already
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='submissions'")
    exists = cur.fetchone() is not None

    if exists:
        # Introspect columns
        cols = get_table_info(conn, "submissions")
        lat_notnull = cols.get("latitude", {}).get("notnull") == 1
        lon_notnull = cols.get("longitude", {}).get("notnull") == 1

        # If legacy NOT NULL detected on either column, attempt a one-time migration to relax the constraint.
        # We keep latitude/longitude columns in the migrated schema (as nullable REAL) to preserve compatibility,
        # but remove NOT NULL requirement so new inserts/updates that don't include lat/lon succeed.
        if lat_notnull or lon_notnull:
            try:
                # Start an immediate transaction to avoid concurrent writes during migration
                cur.execute("BEGIN IMMEDIATE;")
                # Create new table with latitude/longitude present but nullable.
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS submissions_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        facility_code TEXT,
                        employee_id TEXT NOT NULL,
                        drive_link TEXT,
                        total_score REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        payload TEXT,
                        submission_month INTEGER,
                        submission_year INTEGER,
                        latitude REAL,
                        longitude REAL
                    );
                    """
                )
                # Copy columns over. If old table lacks some columns, this SELECT will fail; guard with COALESCE where needed.
                # We'll use a SELECT that tries to pull the columns if they exist; otherwise NULLs.
                # Build SELECT column list dynamically from existing columns for safety.
                existing_cols = set(cols.keys())

                select_cols = [
                    "id",
                    "facility_code" if "facility_code" in existing_cols else "NULL AS facility_code",
                    "employee_id",
                    "drive_link" if "drive_link" in existing_cols else "NULL AS drive_link",
                    "total_score" if "total_score" in existing_cols else "0.0 AS total_score",
                    "created_at" if "created_at" in existing_cols else "CURRENT_TIMESTAMP AS created_at",
                    "payload" if "payload" in existing_cols else "NULL AS payload",
                    "submission_month" if "submission_month" in existing_cols else "NULL AS submission_month",
                    "submission_year" if "submission_year" in existing_cols else "NULL AS submission_year",
                    "latitude" if "latitude" in existing_cols else "NULL AS latitude",
                    "longitude" if "longitude" in existing_cols else "NULL AS longitude",
                ]

                select_sql = "SELECT " + ", ".join(select_cols) + " FROM submissions;"
                insert_sql = "INSERT INTO submissions_new (id, facility_code, employee_id, drive_link, total_score, created_at, payload, submission_month, submission_year, latitude, longitude) " + select_sql

                cur.execute(insert_sql)

                # Drop old table and rename
                cur.execute("DROP TABLE submissions;")
                cur.execute("ALTER TABLE submissions_new RENAME TO submissions;")
                conn.commit()
                # Refresh cursor/conn after commit
                cur = conn.cursor()
            except Exception as e:
                # Rollback and surface a clear error
                try:
                    conn.rollback()
                except Exception:
                    pass
                # Re-raise as a clear exception so init_db caller (app) can surface an informative message.
                # But don't crash the entire app silently; print traceback and raise
                tb = traceback.format_exc()
                raise RuntimeError(f"Migration to relax NOT NULL on latitude/longitude failed: {e}\n{tb}")
    else:
        # Table does not exist — create minimal current schema (no latitude/longitude)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                facility_code TEXT,
                employee_id TEXT NOT NULL,
                drive_link TEXT,
                total_score REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                payload TEXT,
                submission_month INTEGER,
                submission_year INTEGER
            );
            """
        )
        conn.commit()

    # Best-effort add of payload and facility_code columns if table exists without them
    # (useful for older deployments where these columns were added later)
    try:
        cur.execute("ALTER TABLE submissions ADD COLUMN payload TEXT")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE submissions ADD COLUMN facility_code TEXT")
        conn.commit()
    except Exception:
        pass
    # Add new month/year columns if they don't exist (best-effort)
    try:
        cur.execute("ALTER TABLE submissions ADD COLUMN submission_month INTEGER")
        conn.commit()
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE submissions ADD COLUMN submission_year INTEGER")
        conn.commit()
    except Exception:
        pass

    conn.close()

# Initialize database
try:
    init_db()
except Exception as e:
    # If migration failed, expose a clear message in Streamlit
    st.error(f"Database initialization error: {e}")
    st.stop()


# --- Navigation ---
page = st.sidebar.selectbox("Select Page", ["Submit Proposal", "View Dashboard"])


# --- Questions loading ---
QUESTIONS_CSV = "questions.csv"

def load_questions(csv_path: str = QUESTIONS_CSV):
    """Load and normalize questions CSV.

    CSV format (expected): Category, Category Weight (%), Question, Expected Input, Scoring Formula (0–1)
    Rows may omit Category/Category Weight for subsequent questions in the same category; we'll forward-fill.
    Returns list of categories, where each category is dict with name, weight and list of questions.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return []

    # Forward-fill category and weight
    df["Category"] = df["Category"].ffill()
    if "Category Weight (%)" in df.columns:
        df["Category Weight (%)"] = df["Category Weight (%)"].ffill()

    categories = []
    for cat, group in df.groupby("Category", sort=False):
        weight = float(group.iloc[0].get("Category Weight (%)", 0) or 0)
        questions = []
        for _, row in group.iterrows():
            q_text = str(row.get("Question") or "").strip()
            expected = str(row.get("Expected Input") or "").strip()
            formula = str(row.get("Scoring Formula (01)") or row.get("Scoring Formula (0–1)") or row.get("Scoring Formula (0-1)") or row.get("Scoring Formula (0–1)") or row.get("Scoring Formula (0-1)") or "").strip()
            # Normalize expected inputs to list by splitting on ';'
            expected_inputs = [e.strip() for e in expected.split(";") if e.strip()]
            questions.append({
                "text": q_text,
                "expected_inputs": expected_inputs,
                "formula": formula,
            })
        categories.append({"name": cat, "weight": weight, "questions": questions})

    return categories


def _safe_eval_formula(expr: str, variables: dict):
    """Safely evaluate a scoring formula expression using provided variables.

    Allowed nodes: Expression, BinOp, UnaryOp, Call (only min/max), Num/Constant, Name, Load, Compare,
    BoolOp, IfExp. Operators limited to arithmetic and comparisons.
    """
    if not expr or not expr.strip():
        return None

    # Map callable names to actual functions
    allowed_funcs = {"min": min, "max": max, "abs": abs, "pow": pow}

    class SafeEvaluator(ast.NodeVisitor):
        def visit(self, node):
            if isinstance(node, ast.Expression):
                return self.visit(node.body)
            elif isinstance(node, ast.BinOp):
                left = self.visit(node.left)
                right = self.visit(node.right)
                op = node.op
                if isinstance(op, ast.Add):
                    return left + right
                if isinstance(op, ast.Sub):
                    return left - right
                if isinstance(op, ast.Mult):
                    return left * right
                if isinstance(op, ast.Div):
                    try:
                        return left / right
                    except Exception:
                        return 0.0
                if isinstance(op, ast.Pow):
                    return left ** right
                if isinstance(op, ast.Mod):
                    return left % right
                raise ValueError(f"Operator {op} not allowed")
            elif isinstance(node, ast.UnaryOp):
                operand = self.visit(node.operand)
                if isinstance(node.op, ast.UAdd):
                    return +operand
                if isinstance(node.op, ast.USub):
                    return -operand
                raise ValueError("Unary operator not allowed")
            elif isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.Name):
                if node.id in variables:
                    val = variables[node.id]
                    try:
                        return float(val)
                    except Exception:
                        return 0.0
                # allow math constants
                if node.id in vars(math):
                    return getattr(math, node.id)
                raise ValueError(f"Unknown variable '{node.id}'")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in allowed_funcs:
                    func = allowed_funcs[node.func.id]
                    args = [self.visit(a) for a in node.args]
                    return func(*args)
                raise ValueError("Only min/max/abs/pow calls are allowed in formulas")
            elif isinstance(node, ast.Compare):
                left = self.visit(node.left)
                results = []
                for op, comparator in zip(node.ops, node.comparators):
                    right = self.visit(comparator)
                    if isinstance(op, ast.Lt):
                        results.append(left < right)
                    elif isinstance(op, ast.LtE):
                        results.append(left <= right)
                    elif isinstance(op, ast.Gt):
                        results.append(left > right)
                    elif isinstance(op, ast.GtE):
                        results.append(left >= right)
                    elif isinstance(op, ast.Eq):
                        results.append(left == right)
                    elif isinstance(op, ast.NotEq):
                        results.append(left != right)
                    else:
                        raise ValueError("Comparison operator not allowed")
                    left = right
                return all(results)
            elif isinstance(node, ast.IfExp):
                cond = self.visit(node.test)
                if cond:
                    return self.visit(node.body)
                else:
                    return self.visit(node.orelse)
            else:
                raise ValueError(f"Unsupported expression: {type(node).__name__}")

    try:
        tree = ast.parse(expr, mode="eval")
        evaluator = SafeEvaluator()
        return evaluator.visit(tree)
    except Exception as e:
        # If evaluation fails, return None so UI can indicate an error
        return None

# Helper to detect whether existing DB still enforces NOT NULL on lat/lon (used as fallback only)
def db_requires_latlon_placeholders():
    """
    Inspect the current submissions table info and return True if either latitude or longitude
    columns exist and are marked NOT NULL. This is used as a fallback during INSERT/UPDATE to
    include placeholder 0.0 values when migrating is not possible.
    """
    try:
        conn = get_connection()
        cols = get_table_info(conn, "submissions")
        conn.close()
        lat_notnull = cols.get("latitude", {}).get("notnull") == 1
        lon_notnull = cols.get("longitude", {}).get("notnull") == 1
        return lat_notnull or lon_notnull
    except Exception:
        return False


if page == "Submit Proposal":
    # --- Submission Inputs ---
    st.title("Facility Selection Scoring Tool")
    st.header("Submit Facility Proposal")

    facility_code = st.text_input("Facility Code", max_chars=64)
    now_dt = datetime.now()
    col1, col2 = st.columns(2)
    with col1:
        submission_month = st.selectbox("Submission Month", options=list(range(1, 13)), index=now_dt.month - 1)
    with col2:
        year_options = list(range(now_dt.year - 1, now_dt.year + 2))
        submission_year = st.selectbox("Submission Year", options=year_options, index=year_options.index(now_dt.year))

    # Prefill logic: check for existing submission for facility_code, month, year
    prefill_data = None
    if facility_code.strip():
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT employee_id, drive_link, payload FROM submissions WHERE facility_code = ? AND submission_month = ? AND submission_year = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
                (facility_code.strip(), int(submission_month), int(submission_year))
            )
            row = cur.fetchone()
            if row:
                prefill_data = {
                    "employee_id": row[0],
                    "drive_link": row[1],
                    "payload": row[2]
                }
            conn.close()
        except Exception:
            pass

    # Use prefill if available
    employee_id = st.text_input("Submitter ID or Name", max_chars=64, value=(prefill_data["employee_id"] if prefill_data else ""))
    drive_link = st.text_input("Google Drive link (documents/videos)", value=(prefill_data["drive_link"] if prefill_data else ""))

    if 'last_submission' not in st.session_state:
        st.session_state['last_submission'] = None

    # Load questions from CSV
    categories = load_questions(QUESTIONS_CSV)

    # helper to extract variable names from formula
    def extract_varnames(expr: str):
        try:
            tree = ast.parse(expr or "", mode="eval")
        except Exception:
            return []
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
        return list(names)

    def map_vars_to_inputs(varnames, expected_inputs):
        # expected_inputs: list of strings
        mapping = {}
        lowered = [e.lower() for e in expected_inputs]
        for v in varnames:
            v_low = v.lower()
            found = False
            for idx, text in enumerate(lowered):
                if v_low in text or v_low.rstrip('d') in text or v_low.rstrip('s') in text:
                    mapping[v] = idx
                    found = True
                    break
            if not found:
                # fallback: if counts match, map by position
                if len(varnames) == len(expected_inputs):
                    # positionally map
                    pos = varnames.index(v)
                    mapping[v] = pos
                else:
                    # else leave unmapped
                    mapping[v] = None
        return mapping

    # If no categories found, fall back to a simple sample question to keep behaviour
    if not categories:
        st.header("Sample Question")
        if prefill_data and prefill_data.get("payload"):
            try:
                payload_prefill = json.loads(prefill_data["payload"])
                sample_answer = payload_prefill.get("sample", {}).get("answer", "")
            except Exception:
                sample_answer = ""
        else:
            sample_answer = ""
        sample_answer = st.selectbox("Is this location suitable?", ("", "Yes", "No"), index=(["", "Yes", "No"].index(sample_answer) if sample_answer in ["", "Yes", "No"] else 0))
        sample_score = 100.0 if sample_answer == "Yes" else (0.0 if sample_answer == "No" else 0.0)
        st.write(f"Sample Score: {sample_score:.1f} / 100")
        total_score = sample_score
    else:
        st.header("Facility Assessment Questions")
        all_results = []
        total_weighted = 0.0
        total_weight_sum = 0.0

        # Prefill answers if available
        prefill_answers = {}
        if prefill_data and prefill_data.get("payload"):
            try:
                payload_prefill = json.loads(prefill_data["payload"])
                for r in payload_prefill.get("questions", []):
                    cat = r.get("category")
                    qtext = r.get("question")
                    answers = r.get("answers", [])
                    prefill_answers[(cat, qtext)] = answers
            except Exception:
                pass

        user_answers = {}
        for ci, cat in enumerate(categories):
            cat_name = cat.get("name")
            cat_weight = float(cat.get("weight", 0) or 0)

            left_col, right_col = st.columns([8, 2])
            left_col.markdown(f"### {cat_name}")
            score_placeholder = right_col.empty()

            with st.expander("View questions", expanded=False):
                q_scores = []
                for qi, q in enumerate(cat.get("questions", [])):
                    q_text = q.get("text")
                    expected_inputs = q.get("expected_inputs", [])
                    formula = q.get("formula", "")
                    st.markdown(f"**Q{ci+1}.{qi+1}**: {q_text}")
                    answers = []
                    prefill = prefill_answers.get((cat_name, q_text), [])
                    for ei, label in enumerate(expected_inputs):
                        key = f"q_{ci}_{qi}_{ei}"
                        prefill_val = prefill[ei] if ei < len(prefill) else None
                        val = float_input(f" - {label}", placeholder="Enter numeric value", key=key) if prefill_val is None else float_input(f" - {label}", placeholder="Enter numeric value", key=key) or prefill_val
                        if val is None and prefill_val is not None:
                            val = prefill_val
                        answers.append(val)
                    user_answers[(cat_name, q_text)] = answers

                    varnames = extract_varnames(formula)
                    mapping = map_vars_to_inputs(varnames, expected_inputs)

                    missing_input = False
                    vars_for_eval = {}
                    for v in varnames:
                        idx = mapping.get(v)
                        if idx is None:
                            missing_input = True
                            break
                        aval = answers[idx]
                        if aval is None:
                            missing_input = True
                            break
                        try:
                            vars_for_eval[v] = float(aval)
                        except Exception:
                            missing_input = True
                            break

                    if missing_input or not formula:
                        q_score = None
                    else:
                        raw_score = _safe_eval_formula(formula, vars_for_eval)
                        try:
                            q_score = float(raw_score) if raw_score is not None else None
                        except Exception:
                            q_score = None

                        if isinstance(q_score, bool):
                            q_score = 1.0 if q_score else 0.0

                        try:
                            if q_score is None or math.isnan(q_score):
                                q_score = None
                        except Exception:
                            q_score = None
                        if q_score is not None:
                            q_score = max(0.0, min(1.0, float(q_score)))

                    q_scores.append(q_score)
                    all_results.append({
                        "category": cat_name,
                        "category_weight": cat_weight,
                        "question": q_text,
                        "expected_inputs": expected_inputs,
                        "answers": answers,
                        "formula": formula,
                        "score": q_score,
                    })

                answered_scores = [s for s in q_scores if s is not None]
                if answered_scores:
                    cat_score = (sum(answered_scores) / len(answered_scores))
                    weighted = (cat_score * 100.0) * (cat_weight / 100.0)
                    try:
                        score_placeholder.metric("Score", f"{cat_score*100:.1f} / 100")
                    except Exception:
                        score_placeholder.write(f"{cat_score*100:.1f} / 100")
                    st.write(f"Weighted contribution: {weighted:.2f}")
                    st.progress(int(cat_score * 100))
                    total_weighted += weighted
                    total_weight_sum += cat_weight
                else:
                    cat_score = 0.0
                    try:
                        score_placeholder.write("No answered questions")
                    except Exception:
                        pass

        if total_weight_sum > 0:
            if abs(total_weight_sum - 100.0) > 1e-6:
                scale = 100.0 / total_weight_sum
                total_score = max(0.0, min(100.0, total_weighted * scale))
            else:
                total_score = max(0.0, min(100.0, total_weighted))
        else:
            total_score = 0.0

        st.header(f"Total Facility Score: {total_score:.1f} / 100")

        if st.checkbox("Show scoring breakdown and diagnostics"):
            try:
                import pandas as _pd
                rows = []
                for r in all_results:
                    rows.append({
                        "category": r.get("category"),
                        "question": r.get("question"),
                        "answers": r.get("answers"),
                        "formula": r.get("formula"),
                        "score": r.get("score"),
                        "counted": (r.get("score") is not None),
                    })
                dbg = _pd.DataFrame(rows)
                st.dataframe(dbg, use_container_width=True)
                st.write(f"Total weighted: {total_weighted:.4f}; total weight considered: {total_weight_sum:.2f}")
            except Exception as _:
                st.write("Unable to build debug table.")

    # Bottom submission button
    st.write("")
    button_label = "Update" if prefill_data else "Submit Proposal"
    submit_clicked = st.button(button_label)

    if submit_clicked:
        # Build payload depending on whether we had categories
        if categories:
            # Use user_answers to save what user entered
            for r in all_results:
                cat = r["category"]
                qtext = r["question"]
                r["answers"] = user_answers.get((cat, qtext), r["answers"])
            payload = {
                "submitter": {
                    "facility_code": facility_code.strip(),
                    "employee_id": employee_id.strip(),
                    "submission_month": submission_month,
                    "submission_year": submission_year,
                    "drive_link": drive_link.strip(),
                },
                "questions": all_results,
                "totals": {"total_score": total_score},
            }
        else:
            payload = {
                "submitter": {
                    "facility_code": facility_code.strip(),
                    "employee_id": employee_id.strip(),
                    "submission_month": submission_month,
                    "submission_year": submission_year,
                    "drive_link": drive_link.strip(),
                },
                "sample": {
                    "answer": (sample_answer if 'sample_answer' in locals() else ""),
                    "sample_score": (sample_score if 'sample_score' in locals() else 0.0),
                },
                "totals": {"total_score": (total_score if 'total_score' in locals() else 0.0)},
            }

        errors = []
        if not facility_code.strip():
            errors.append("Facility Code is required.")
        if not employee_id.strip():
            errors.append("Employee ID is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            try:
                conn = get_connection()
                cur = conn.cursor()

                cols = get_table_info(conn, "submissions")
                lat_notnull = cols.get("latitude", {}).get("notnull") == 1
                lon_notnull = cols.get("longitude", {}).get("notnull") == 1
                require_latlon_placeholders = lat_notnull or lon_notnull

                # Check for existing submission for same facility, month, year
                cur.execute(
                    "SELECT id FROM submissions WHERE facility_code = ? AND submission_month = ? AND submission_year = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
                    (facility_code.strip(), int(submission_month), int(submission_year))
                )
                row = cur.fetchone()
                if row:
                    # Update only if same facility, month, year
                    if require_latlon_placeholders:
                        cur.execute(
                            """
                            UPDATE submissions
                            SET employee_id = ?, drive_link = ?, total_score = ?, payload = ?, submission_month = ?, submission_year = ?, latitude = ?, longitude = ?, created_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                employee_id.strip(),
                                drive_link.strip(),
                                float(total_score),
                                json.dumps(payload),
                                int(submission_month),
                                int(submission_year),
                                0.0,
                                0.0,
                                int(row[0])
                            )
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE submissions
                            SET employee_id = ?, drive_link = ?, total_score = ?, payload = ?, submission_month = ?, submission_year = ?, created_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                employee_id.strip(),
                                drive_link.strip(),
                                float(total_score),
                                json.dumps(payload),
                                int(submission_month),
                                int(submission_year),
                                int(row[0])
                            )
                        )
                else:
                    # Insert new record
                    if require_latlon_placeholders:
                        cur.execute(
                            "INSERT INTO submissions (facility_code, employee_id, drive_link, total_score, payload, submission_month, submission_year, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                facility_code.strip(),
                                employee_id.strip(),
                                drive_link.strip(),
                                float(total_score),
                                json.dumps(payload),
                                int(submission_month),
                                int(submission_year),
                                0.0,
                                0.0
                            )
                        )
                    else:
                        cur.execute(
                            "INSERT INTO submissions (facility_code, employee_id, drive_link, total_score, payload, submission_month, submission_year) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                facility_code.strip(),
                                employee_id.strip(),
                                drive_link.strip(),
                                float(total_score),
                                json.dumps(payload),
                                int(submission_month),
                                int(submission_year)
                            )
                        )
                conn.commit()
                conn.close()
                st.session_state['last_submission'] = employee_id.strip()
                st.success("Submission saved successfully.")
            except Exception as e:
                tb = traceback.format_exc()
                st.error(f"Failed to save submission: {e}\n{tb}")

elif page == "View Dashboard":
    # --- Dashboard Code ---
    st.title("Facility Scoring Dashboard")

    # Passcode protection
    st.subheader("Access Dashboard")
    entered_passcode = st.text_input("Enter passcode to view dashboard:", type="password", placeholder="Enter passcode")

    if entered_passcode != "PnE":
        st.warning("Please enter the correct passcode to access the dashboard.")
        st.stop()

    st.success("Access granted! Loading dashboard...")

    # Load distinct facility codes for filter options
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT COALESCE(facility_code, '') AS facility_code FROM submissions ORDER BY facility_code")
    facility_options = [r[0] for r in cur.fetchall() if r[0] is not None and r[0] != ""]

    # Multi-select filter (empty -> show all)
    selected_facilities = st.multiselect("Filter by Facility Code(s)", options=facility_options)

    # Fetch submissions
    cur.execute(
        """
        WITH ranked AS (
            SELECT
                id, facility_code, employee_id, drive_link,
                submission_month, submission_year,
                total_score, created_at, payload,
                ROW_NUMBER() OVER (PARTITION BY facility_code ORDER BY datetime(created_at) DESC, id DESC) AS rn
            FROM submissions
        )
        SELECT id, facility_code, employee_id, drive_link,
               submission_month, submission_year,
               total_score, created_at, payload
        FROM ranked
        WHERE rn = 1
        ORDER BY datetime(created_at) DESC, id DESC
        """
    )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()

    df = pd.DataFrame(rows, columns=cols)
    if selected_facilities:
        df = df[df["facility_code"].isin(selected_facilities)]

        # Helper: extract category-wise scores from payload.questions
        def extract_category_scores(payload_json):
            # ...existing code...
            try:
                p = json.loads(payload_json) if isinstance(payload_json, str) and payload_json else {}
            except Exception:
                p = {}
            questions = p.get("questions") or []
            totals = p.get("totals") or {}
            total = totals.get("total_score")
            cats = {}
            for q in questions:
                cat = q.get("category") or ""
                score = q.get("score")
                if score is None:
                    continue
                try:
                    val = float(score) * 100.0
                except Exception:
                    continue
                if cat not in cats:
                    cats[cat] = {"sum": 0.0, "count": 0}
                cats[cat]["sum"] += val
                cats[cat]["count"] += 1
            cat_scores = {}
            for k, v in cats.items():
                if v["count"]:
                    cat_scores[k] = v["sum"] / v["count"]
                else:
                    cat_scores[k] = None
            return cat_scores, (float(total) if total is not None else None)

    conn.close()

    df = pd.DataFrame(rows, columns=cols)
    if selected_facilities:
        df = df[df["facility_code"].isin(selected_facilities)]

    # Helper: extract category-wise scores from payload.questions
    def extract_category_scores(payload_json):
        """Return (category_scores_dict, total_score)

        category_scores_dict: mapping category_name -> category_percent (0-100) or None
        total_score: payload totals.total_score if present else None
        """
        try:
            p = json.loads(payload_json) if isinstance(payload_json, str) and payload_json else {}
        except Exception:
            p = {}
        questions = p.get("questions") or []
        totals = p.get("totals") or {}
        total = totals.get("total_score")

        # Aggregate per category: compute average of answered question scores
        cats = {}
        for q in questions:
            cat = q.get("category") or ""
            score = q.get("score")
            # score expected in 0-1 range; convert to percent
            if score is None:
                continue
            try:
                val = float(score) * 100.0
            except Exception:
                continue
            if cat not in cats:
                cats[cat] = {"sum": 0.0, "count": 0}
            cats[cat]["sum"] += val
            cats[cat]["count"] += 1

        cat_scores = {}
        for k, v in cats.items():
            if v["count"]:
                cat_scores[k] = v["sum"] / v["count"]
            else:
                cat_scores[k] = None

        return cat_scores, (float(total) if total is not None else None)

    # Build summary table: basic details + sample score + total
    def extract_scores(payload_json):
        try:
            p = json.loads(payload_json) if isinstance(payload_json, str) and payload_json else {}
        except Exception:
            p = {}
        sample = (p.get("sample") or {}).get("sample_score")
        total = (p.get("totals") or {}).get("total_score")
        return sample, total

    if not df.empty:
        scores = df["payload"].apply(extract_scores)
        df[["sample_score", "total_score_payload"]] = pd.DataFrame(scores.tolist(), index=df.index)

    # Build a wide table of category scores for each submission
    if not df.empty:
        cat_dicts = df["payload"].apply(lambda p: extract_category_scores(p)[0])
        # union all categories
        all_cats = set()
        for d in cat_dicts.tolist():
            if isinstance(d, dict):
                all_cats.update([k for k in d.keys() if k])
        all_cats = sorted(list(all_cats))

        # Create columns for each category (percent) and a payload_total column
        for c in all_cats:
            df[f"cat::{c}"] = cat_dicts.apply(lambda d: (d.get(c) if isinstance(d, dict) else None))
        # Use payload total score if present, else stored total_score
        df["total_score_effective"] = df.apply(lambda r: (json.loads(r["payload"]).get("totals", {}).get("total_score") if isinstance(r.get("payload"), str) and r.get("payload") else (r.get("total_score") if r.get("total_score") is not None else None)), axis=1)

    summary_df = (
        df[[
            "id", "facility_code", "employee_id", "submission_month", "submission_year", "created_at",
            "sample_score"
        ]].copy() if not df.empty else pd.DataFrame(columns=[
            "id", "facility_code", "employee_id", "submission_month", "submission_year", "created_at",
            "sample_score"
        ])
    )

    # Prefer total_score from payload if present; fallback to stored total_score
    if not df.empty:
        summary_df["total_score"] = df["total_score_payload"].where(df["total_score_payload"].notna(), df["total_score"])  # type: ignore
    else:
        summary_df["total_score"] = []

    # Only show the summary table for category scores & totals
    if df.empty:
        st.info("No submissions available.")
    else:
        # Show all submissions in the summary table
        cat_cols = [c for c in df.columns if c.startswith("cat::")]
        display_cols = ["id", "facility_code", "employee_id", "submission_month", "submission_year", "created_at"] + cat_cols + ["total_score_effective"]
        summary_for_selected = df[display_cols].copy()
        rename_map = {c: c.replace("cat::", "") for c in cat_cols}
        summary_for_selected = summary_for_selected.rename(columns=rename_map)
        st.subheader("Submissions - Category Scores & Totals")
        st.dataframe(summary_for_selected.fillna("N/A"), use_container_width=True)
        for idx, row in summary_for_selected.iterrows():
            st.write(row.to_dict())
            # Download button for each row
            # Build payload dict from original df
            orig_row = df[df["id"] == row["id"]].iloc[0]
            try:
                p = json.loads(orig_row["payload"]) if isinstance(orig_row["payload"], str) and orig_row["payload"] else {}
            except Exception:
                p = {}
            submitter = p.get("submitter") or {}
            submitter.setdefault("facility_code", orig_row.get("facility_code"))
            submitter.setdefault("employee_id", orig_row.get("employee_id"))
            submitter.setdefault("submission_month", orig_row.get("submission_month"))
            submitter.setdefault("submission_year", orig_row.get("submission_year"))
            submitter.setdefault("drive_link", orig_row.get("drive_link"))
            p["submitter"] = submitter
            flat = pd.json_normalize(p, sep=".")
            csv_bytes = flat.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"Download Submission {row['id']} as CSV",
                data=csv_bytes,
                file_name=f"submission_{row['id']}.csv",
                mime="text/csv",
            )
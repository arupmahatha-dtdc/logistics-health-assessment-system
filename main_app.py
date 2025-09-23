import streamlit as st
import pandas as pd
import sqlite3
import json
import os
from datetime import datetime
import traceback

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

def float_input(label: str, placeholder: str = ""):
    raw = st.text_input(label, value="", placeholder=placeholder)
    return parse_float(raw)

def int_input(label: str, placeholder: str = ""):
    raw = st.text_input(label, value="", placeholder=placeholder)
    return parse_int(raw)


def get_table_info(conn, table_name="submissions"):
    """
    Return a dict mapping column name -> {notnull: int, type: str, cid: int, dflt_value, pk}
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
    employee_id = st.text_input("Submitter ID or Name", max_chars=64)
    # Submission period
    now_dt = datetime.now()
    col1, col2 = st.columns(2)
    with col1:
        submission_month = st.selectbox("Submission Month", options=list(range(1, 13)), index=now_dt.month - 1)
    with col2:
        year_options = list(range(now_dt.year - 1, now_dt.year + 2))
        submission_year = st.selectbox("Submission Year", options=year_options, index=year_options.index(now_dt.year))
    drive_link = st.text_input("Google Drive link (documents/videos)")

    if 'last_submission' not in st.session_state:
        st.session_state['last_submission'] = None

    # Sample single question
    st.header("Sample Question")
    sample_answer = st.selectbox("Is this location suitable?", ("", "Yes", "No"))
    sample_score = 100.0 if sample_answer == "Yes" else (0.0 if sample_answer == "No" else 0.0)
    st.write(f"Sample Score: {sample_score:.1f} / 100")

    # Final Score (same as sample for now)
    total_score = sample_score
    st.header(f"Total Facility Score: {total_score:.1f} / 100")

    # Save submission after score is computed
    # Bottom submission button
    st.write("")
    submit_clicked = st.button("Submit Proposal")

    if submit_clicked:
        # Build full payload
        payload = {
            "submitter": {
                "facility_code": facility_code.strip(),
                "employee_id": employee_id.strip(),
                "submission_month": submission_month,
                "submission_year": submission_year,
                "drive_link": drive_link.strip(),
            },
            "sample": {
                "answer": sample_answer,
                "sample_score": sample_score,
            },
            "totals": {"total_score": total_score},
        }
        # Validation for compulsory fields
        errors = []
        if not facility_code.strip():
            errors.append("Facility Code is required.")
        if not employee_id.strip():
            errors.append("Employee ID is required.")
        if sample_answer == "":
            errors.append("Please select an answer for the sample question.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            try:
                conn = get_connection()
                cur = conn.cursor()

                # Inspect table info for fallback placeholders
                cols = get_table_info(conn, "submissions")
                lat_notnull = cols.get("latitude", {}).get("notnull") == 1
                lon_notnull = cols.get("longitude", {}).get("notnull") == 1
                require_latlon_placeholders = lat_notnull or lon_notnull

                # Check if a submission already exists for this facility_code (latest by created_at/id)
                cur.execute(
                    "SELECT id FROM submissions WHERE facility_code = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT 1",
                    (facility_code.strip(),)
                )
                row = cur.fetchone()
                if row:
                    # Update existing record
                    if require_latlon_placeholders:
                        # include latitude and longitude placeholders in the update
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
                # Provide detailed error message for debugging (but keep it readable)
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

    st.subheader("Submissions")
    # Add in-table checkbox for selection
    selected_ids = []
    if not summary_df.empty:
        table_df = summary_df.copy()
        table_df.insert(0, "select", False)
        edited_df = st.data_editor(
            table_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "select": st.column_config.CheckboxColumn("Select", default=False),
            },
            key="submissions_table_editor",
        )
        try:
            selected_ids = [int(x) for x in edited_df[edited_df["select"] == True]["id"].tolist()]
        except Exception:
            selected_ids = []
    else:
        st.info("No submissions found.")

    # Selection for download
    st.markdown("")
    st.subheader("Download Selected Submissions' Inputs as CSV")
    if not summary_df.empty:
        # If no rows selected, default to all filtered
        if not selected_ids:
            selected_ids = summary_df["id"].tolist()

        # Build CSV of inputs (flattened payload)
        def row_to_payload_dict(row):
            try:
                p = json.loads(row["payload"]) if isinstance(row["payload"], str) and row["payload"] else {}
            except Exception:
                p = {}
            # Ensure some top-level basics exist even if payload missing
            submitter = p.get("submitter") or {}
            submitter.setdefault("facility_code", row.get("facility_code"))
            submitter.setdefault("employee_id", row.get("employee_id"))
            submitter.setdefault("submission_month", row.get("submission_month"))
            submitter.setdefault("submission_year", row.get("submission_year"))
            submitter.setdefault("drive_link", row.get("drive_link"))
            p["submitter"] = submitter
            return p

        filtered_df = df[df["id"].isin(selected_ids)] if selected_ids else df
        payload_dicts = [row_to_payload_dict(r) for _, r in filtered_df.iterrows()]
        if payload_dicts:
            flat = pd.json_normalize(payload_dicts, sep=".")
            # Keep a stable column order: basics first if present
            preferred_order = [
                "submitter.facility_code", "submitter.employee_id", "submitter.submission_month",
                "submitter.submission_year", "submitter.drive_link",
                "sample.sample_score",
                "totals.total_score",
            ]
            cols_in_flat = list(flat.columns)
            ordered = [c for c in preferred_order if c in cols_in_flat] + [c for c in cols_in_flat if c not in preferred_order]
            flat = flat[ordered]
            csv_bytes = flat.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download CSV",
                data=csv_bytes,
                file_name="facility_submissions_inputs.csv",
                mime="text/csv",
            )
        else:
            st.info("No data to download.")
    else:
        st.info("No submissions found.")
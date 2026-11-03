import os
import re
import uuid
from datetime import date, datetime, time
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from backend.db import db_cursor
from backend.reviewer import make_reviewer_content, read_module_text
from backend.schema import ensure_schema

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOTS = {
    "profile_photos": BASE_DIR / "profile_photos",
    "uploaded_modules": BASE_DIR / "uploaded_modules",
    "uploaded_activities": BASE_DIR / "uploaded_activities",
    "uploaded_announcements": BASE_DIR / "uploaded_announcements",
    "uploaded_submissions": BASE_DIR / "uploaded_submissions",
}

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "classroom-portal-local-secret")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

SECTIONS = ("Section A", "Section B", "Section C", "All Sections")
PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@phinmaed\.com", re.IGNORECASE)
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]+")
PASSWORD_RE = re.compile(r"[A-Za-z0-9_-]+")


def setup_app():
    for folder in UPLOAD_ROOTS.values():
        folder.mkdir(parents=True, exist_ok=True)
    try:
        ensure_schema()
    except Exception as error:
        print(f"Database setup warning: {error}")


def current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "username": session.get("username"),
        "role": session.get("role"),
        "section": session.get("section") or "Not assigned",
        "fullname": session.get("fullname") or session.get("username"),
    }


def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("login"))
            if role and user["role"] != role:
                flash("You do not have access to that page.", "error")
                return redirect(url_for("home"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def verify_password(stored, provided):
    if not stored:
        return False
    if stored.startswith(("pbkdf2:", "scrypt:", "argon2:")):
        return check_password_hash(stored, provided)
    return stored == provided


def save_upload(file_storage, folder_key):
    if not file_storage or not file_storage.filename:
        return None, None, None
    original = secure_filename(file_storage.filename)
    if not original:
        return None, None
    ext = Path(original).suffix.lower()
    unique = f"{uuid.uuid4().hex}_{original}"
    destination = UPLOAD_ROOTS[folder_key] / unique
    file_storage.save(destination)
    return str(destination), original, ext


def parse_deadline(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.max)
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                parsed = datetime.combine(parsed.date(), time.max)
            return parsed
        except ValueError:
            continue
    return None


def get_assigned_subjects(teacher_id, section=None):
    with db_cursor() as (_conn, cursor):
        if section and section != "All Sections":
            cursor.execute(
                """
                SELECT DISTINCT subject_name FROM subjects
                WHERE teacher_id = %s AND (section = %s OR section = 'All Sections')
                ORDER BY subject_name
                """,
                (teacher_id, section),
            )
        else:
            cursor.execute(
                """
                SELECT DISTINCT subject_name FROM subjects
                WHERE teacher_id = %s ORDER BY subject_name
                """,
                (teacher_id,),
            )
        return [row[0] for row in cursor.fetchall() if row[0]]


def get_student_subjects(user_id, section):
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            "SELECT enrollment_type FROM student_enrollment_types WHERE student_id=%s",
            (user_id,),
        )
        type_row = cursor.fetchone()
        if type_row and type_row[0] == "Irregular":
            cursor.execute(
                """
                SELECT DISTINCT s.subject_name
                FROM subjects s
                JOIN student_subject_assignments a ON a.subject_id = s.id
                WHERE a.student_id = %s
                ORDER BY s.subject_name
                """,
                (user_id,),
            )
        else:
            cursor.execute(
                """
                SELECT DISTINCT subject_name FROM subjects
                WHERE section = %s OR section = 'All Sections'
                ORDER BY subject_name
                """,
                (section,),
            )
        return [row[0] for row in cursor.fetchall() if row[0]]


def subject_filter(items, subject_index):
    chosen = session.get("current_subject") or "All Subjects"
    if chosen == "All Subjects":
        return items, chosen
    filtered = [item for item in items if (item[subject_index] or "") == chosen]
    return filtered, chosen


def load_profile(username):
    with db_cursor(dictionary=True) as (_conn, cursor):
        cursor.execute(
            """
            SELECT id, username, role, section, fullname, email, contact, photo_path
            FROM users WHERE username = %s
            """,
            (username,),
        )
        return cursor.fetchone()


def serve_stored_file(path):
    if not path:
        abort(404)
    file_path = Path(path)
    if not file_path.is_file():
        abort(404)
    allowed = False
    resolved = file_path.resolve()
    for folder in UPLOAD_ROOTS.values():
        try:
            resolved.relative_to(folder.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        abort(403)
    return send_file(resolved)


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "current_subject": session.get("current_subject", "All Subjects"),
        "now": datetime.now(),
    }


@app.route("/")
def home():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] == "Administrator":
        return redirect(url_for("admin_dashboard"))
    if user["role"] == "Teacher":
        return redirect(url_for("teacher_dashboard"))
    return redirect(url_for("student_dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username and not (
            re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", username)
            or USERNAME_RE.fullmatch(username)
        ):
            flash("Please enter a valid email address or existing username.", "error")
            return render_template("auth.html", mode="login")
        with db_cursor(dictionary=True) as (_conn, cursor):
            cursor.execute(
                """
                SELECT id, username, password, role, section, fullname
                FROM users WHERE username = %s
                """,
                (username,),
            )
            user = cursor.fetchone()
        if not user or not verify_password(user["password"], password):
            flash("Incorrect username or password.", "error")
            return render_template("auth.html", mode="login")
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["section"] = user["section"] or "Not assigned"
        session["fullname"] = user["fullname"] or user["username"]
        session["current_subject"] = "All Subjects"
        flash(f"Welcome back, {session['fullname']}.", "success")
        return redirect(url_for("home"))
    return render_template("auth.html", mode="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("home"))
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        role = request.form.get("role", "Student")
        section = request.form.get("section") if role == "Student" else None
        if not fullname:
            flash("Please enter your full name.", "error")
        elif not EMAIL_RE.fullmatch(email):
            flash(
                "Please use your PHINMA Education email, for example juandelacruz@phinmaed.com.",
                "error",
            )
        elif role == "Student" and not section:
            flash("Please select your section.", "error")
        elif not password or not PASSWORD_RE.fullmatch(password):
            flash("Password may contain only letters, numbers, underscores and dashes.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            try:
                with db_cursor() as (_conn, cursor):
                    cursor.execute(
                        """
                        SELECT id FROM users
                        WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)
                        LIMIT 1
                        """,
                        (email, email),
                    )
                    if cursor.fetchone():
                        flash("This email is already registered. Please sign in.", "error")
                        return render_template("auth.html", mode="register")
                    cursor.execute(
                        """
                        INSERT INTO users (username, password, role, section, fullname, email)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            email,
                            generate_password_hash(password),
                            role,
                            section,
                            fullname,
                            email,
                        ),
                    )
                flash("Account created successfully. Sign in to enter the portal.", "success")
                return redirect(url_for("login"))
            except Exception as error:
                flash(f"Could not create account: {error}", "error")
        return render_template("auth.html", mode="register")
    return render_template("auth.html", mode="register")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/set-subject", methods=["POST"])
@login_required()
def set_subject():
    session["current_subject"] = request.form.get("subject") or "All Subjects"
    next_url = request.form.get("next") or url_for("home")
    return redirect(next_url)


@app.route("/admin")
@login_required("Administrator")
def admin_dashboard():
    with db_cursor(dictionary=True) as (_conn, cursor):
        cursor.execute(
            "SELECT id, COALESCE(NULLIF(fullname, ''), username) AS name FROM users WHERE role = 'Teacher' ORDER BY username"
        )
        teachers = cursor.fetchall()
        cursor.execute(
            """
            SELECT s.id, s.subject_name, s.section, s.teacher_id,
                   COALESCE(NULLIF(u.fullname, ''), u.username, 'Not assigned') AS teacher
            FROM subjects s
            LEFT JOIN users u ON u.id = s.teacher_id
            ORDER BY s.section, s.subject_name
            """
        )
        subjects = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, COALESCE(NULLIF(fullname, ''), username) AS name, username,
                   COALESCE(section, 'Not assigned') AS section
            FROM users WHERE role = 'Student' ORDER BY fullname, username
            """
        )
        students = cursor.fetchall()
        cursor.execute(
            """
            SELECT id, COALESCE(fullname, '') AS fullname, username, role,
                   COALESCE(section, 'Not assigned') AS section
            FROM users ORDER BY role, username
            """
        )
        accounts = cursor.fetchall()
        cursor.execute("SELECT id, subject_name, section FROM subjects ORDER BY subject_name")
        all_subjects = cursor.fetchall()
        cursor.execute("SELECT student_id, enrollment_type FROM student_enrollment_types")
        enrollment_types = {row["student_id"]: row["enrollment_type"] for row in cursor.fetchall()}
        cursor.execute("SELECT student_id, subject_id FROM student_subject_assignments")
        assignments = {}
        for row in cursor.fetchall():
            assignments.setdefault(row["student_id"], []).append(row["subject_id"])
    return render_template(
        "admin.html",
        teachers=teachers,
        subjects=subjects,
        students=students,
        accounts=accounts,
        all_subjects=all_subjects,
        enrollment_types=enrollment_types,
        assignments=assignments,
        sections=SECTIONS,
    )


@app.route("/admin/subjects", methods=["POST"])
@login_required("Administrator")
def admin_save_subject():
    name = request.form.get("subject_name", "").strip()
    section = request.form.get("section", "Section A")
    teacher_id = request.form.get("teacher_id")
    if not name or not teacher_id:
        flash("Enter a subject name and choose a teacher.", "warning")
        return redirect(url_for("admin_dashboard"))
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            "SELECT id FROM subjects WHERE LOWER(subject_name)=LOWER(%s) AND section=%s",
            (name, section),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE subjects SET subject_name=%s, teacher_id=%s WHERE id=%s",
                (name, int(teacher_id), existing[0]),
            )
            flash("Subject assignment updated.", "success")
        else:
            cursor.execute(
                "INSERT INTO subjects (subject_name, section, teacher_id) VALUES (%s, %s, %s)",
                (name, section, int(teacher_id)),
            )
            flash("Subject created and assigned.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/subjects/<int:subject_id>/delete", methods=["POST"])
@login_required("Administrator")
def admin_delete_subject(subject_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
    flash("Subject deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/enrollment", methods=["POST"])
@login_required("Administrator")
def admin_save_enrollment():
    student_id = request.form.get("student_id")
    enrollment_type = request.form.get("enrollment_type", "Regular")
    checked = request.form.getlist("subject_ids")
    if not student_id:
        flash("Choose a student first.", "warning")
        return redirect(url_for("admin_dashboard"))
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            INSERT INTO student_enrollment_types (student_id, enrollment_type)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE enrollment_type=VALUES(enrollment_type)
            """,
            (student_id, enrollment_type),
        )
        cursor.execute(
            "DELETE FROM student_subject_assignments WHERE student_id=%s",
            (student_id,),
        )
        if enrollment_type == "Irregular":
            for subject_id in checked:
                cursor.execute(
                    "INSERT INTO student_subject_assignments (student_id, subject_id) VALUES (%s, %s)",
                    (student_id, int(subject_id)),
                )
    flash("Enrollment saved.", "success")
    return redirect(url_for("admin_dashboard"))


def teacher_nav():
    user = current_user()
    return {
        "subjects": ["All Subjects"] + get_assigned_subjects(user["id"]),
        "assigned": get_assigned_subjects(user["id"]),
    }


@app.route("/teacher")
@login_required("Teacher")
def teacher_dashboard():
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT COUNT(*) FROM modules")
        module_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM activities")
        activity_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM attendance_sessions WHERE created_by=%s",
            (user["id"],),
        )
        attendance_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM announcements")
        announcement_count = cursor.fetchone()[0]
    return render_template(
        "teacher.html",
        page="dashboard",
        **teacher_nav(),
        stats={
            "modules": module_count,
            "activities": activity_count,
            "attendance": attendance_count,
            "announcements": announcement_count,
        },
        sections=SECTIONS,
    )


@app.route("/teacher/announcements", methods=["GET", "POST"])
@login_required("Teacher")
def teacher_announcement():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        section = request.form.get("section", "All Sections")
        subject = request.form.get("subject") or None
        if not title or not description:
            flash("Please enter an announcement title and description.", "warning")
            return redirect(url_for("teacher_announcement"))
        path, _name, _ext = save_upload(request.files.get("attachment"), "uploaded_announcements")
        with db_cursor() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO announcements (title, description, attachment_path, section, subject)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (title, description, path, section, subject),
            )
        flash("Announcement posted.", "success")
        return redirect(url_for("teacher_dashboard"))
    return render_template(
        "teacher.html",
        page="announcement",
        **teacher_nav(),
        sections=SECTIONS,
        subject_options=get_assigned_subjects(user["id"]),
    )


@app.route("/teacher/attendance", methods=["GET", "POST"])
@login_required("Teacher")
def teacher_attendance():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        section = request.form.get("section", "All Sections")
        deadline_text = request.form.get("deadline", "23:59").strip()
        try:
            deadline_time = datetime.strptime(deadline_text, "%H:%M").time()
        except ValueError:
            flash("Enter the deadline as HH:MM, for example 14:30.", "warning")
            return redirect(url_for("teacher_attendance"))
        now = datetime.now()
        deadline = datetime.combine(now.date(), deadline_time)
        if not title:
            flash("Please enter an attendance title.", "warning")
            return redirect(url_for("teacher_attendance"))
        if deadline <= now:
            flash("The deadline must be a future time today.", "warning")
            return redirect(url_for("teacher_attendance"))
        with db_cursor() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO attendance_sessions
                (title, section, attendance_date, deadline, created_by)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (title, section, now.date(), deadline, user["id"]),
            )
        flash("Attendance created and is now visible to students.", "success")
        return redirect(url_for("teacher_attendance_records"))
    return render_template(
        "teacher.html",
        page="create_attendance",
        **teacher_nav(),
        sections=SECTIONS,
    )


@app.route("/teacher/attendance-records")
@login_required("Teacher")
def teacher_attendance_records():
    user = current_user()
    with db_cursor(dictionary=True) as (_conn, cursor):
        cursor.execute(
            """
            SELECT a.id AS attendance_id, a.title, a.section, a.attendance_date, a.deadline,
                   u.username AS student_name, u.fullname, r.status, r.marked_at
            FROM attendance_sessions a
            LEFT JOIN attendance_records r ON r.attendance_id = a.id
            LEFT JOIN users u ON u.id = r.student_id AND u.role = 'Student'
            WHERE a.created_by = %s
            ORDER BY a.attendance_date DESC, a.created_at DESC, u.username
            """,
            (user["id"],),
        )
        rows = cursor.fetchall()
    grouped = {}
    for row in rows:
        aid = row["attendance_id"]
        grouped.setdefault(
            aid,
            {
                "title": row["title"],
                "section": row["section"] or "All Sections",
                "attendance_date": row["attendance_date"],
                "deadline": row["deadline"],
                "students": [],
            },
        )
        if row["student_name"]:
            grouped[aid]["students"].append(row)
    return render_template(
        "teacher.html",
        page="attendance_records",
        **teacher_nav(),
        records=list(grouped.values()),
    )


@app.route("/teacher/modules", methods=["GET", "POST"])
@login_required("Teacher")
def teacher_modules():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        url = request.form.get("url", "").strip()
        section = request.form.get("section", "Section A")
        subject = request.form.get("subject")
        uploaded = request.files.get("file")
        path, filename, _ext = save_upload(uploaded, "uploaded_modules")
        if not title or not description:
            flash("Please enter the module title and description.", "warning")
            return redirect(url_for("teacher_modules"))
        if not path and not url:
            flash("Attach a module file or enter a module link.", "warning")
            return redirect(url_for("teacher_modules"))
        if url and not url.lower().startswith(("https://", "http://")):
            flash("The module link must start with https:// or http://.", "warning")
            return redirect(url_for("teacher_modules"))
        module_type = "both" if path and url else ("file" if path else "link")
        if subject == "No assigned subjects":
            subject = None
        with db_cursor() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO modules
                (title, description, filename, filepath, module_type, url, section, subject)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (title, description, filename, path, module_type, url or None, section, subject),
            )
        flash("Module posted.", "success")
        return redirect(url_for("teacher_modules"))

    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT id, title, description, filename, filepath, url, uploaded_at, section, subject
            FROM modules ORDER BY uploaded_at DESC
            """
        )
        modules = cursor.fetchall()
    modules, chosen = subject_filter(modules, 8)
    return render_template(
        "teacher.html",
        page="modules",
        **teacher_nav(),
        modules=modules,
        sections=SECTIONS,
        subject_options=get_assigned_subjects(user["id"]),
        chosen_subject=chosen,
    )


@app.route("/teacher/modules/<int:module_id>/delete", methods=["POST"])
@login_required("Teacher")
def teacher_delete_module(module_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("DELETE FROM modules WHERE id=%s", (module_id,))
    flash("Module deleted.", "success")
    return redirect(url_for("teacher_modules"))


@app.route("/teacher/activities", methods=["GET", "POST"])
@login_required("Teacher")
def teacher_activities():
    user = current_user()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()
        due_date = request.form.get("due_date", "").strip()
        due_time = request.form.get("due_time", "").strip()
        resource_url = request.form.get("resource_url", "").strip()
        section = request.form.get("section", "Section A")
        subject = request.form.get("subject")
        path, _name, _ext = save_upload(request.files.get("attachment"), "uploaded_activities")
        if not title or not instructions or not due_date or not due_time:
            flash("Please enter the title, instructions, due date, and due time.", "warning")
            return redirect(url_for("teacher_activities"))
        try:
            datetime.strptime(due_time, "%H:%M")
        except ValueError:
            flash("Enter the due time in 24-hour HH:MM format.", "warning")
            return redirect(url_for("teacher_activities"))
        if resource_url and not resource_url.startswith(("https://", "http://")):
            flash("The resource link must start with https:// or http://.", "warning")
            return redirect(url_for("teacher_activities"))
        if subject == "No assigned subjects":
            subject = None
        deadline = f"{due_date} {due_time}:00"
        with db_cursor() as (_conn, cursor):
            cursor.execute(
                """
                INSERT INTO activities
                (title, description, due_date, attachment_path, resource_url, section, subject)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (title, instructions, deadline, path, resource_url or None, section, subject),
            )
        flash("Activity assigned.", "success")
        return redirect(url_for("teacher_activities"))

    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT id, title, description, due_date, attachment_path, resource_url, section, subject
            FROM activities ORDER BY due_date
            """
        )
        activities = cursor.fetchall()
    activities, chosen = subject_filter(activities, 7)
    upcoming, overdue = [], []
    now = datetime.now()
    for activity in activities:
        deadline = parse_deadline(activity[3])
        if deadline and now > deadline:
            overdue.append(activity)
        else:
            upcoming.append(activity)
    return render_template(
        "teacher.html",
        page="activities",
        **teacher_nav(),
        upcoming=upcoming,
        overdue=overdue,
        sections=SECTIONS,
        subject_options=get_assigned_subjects(user["id"]),
        chosen_subject=chosen,
    )


@app.route("/teacher/activities/<int:activity_id>/delete", methods=["POST"])
@login_required("Teacher")
def teacher_delete_activity(activity_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("DELETE FROM activities WHERE id=%s", (activity_id,))
    flash("Activity deleted.", "success")
    return redirect(url_for("teacher_activities"))


@app.route("/teacher/students-work")
@login_required("Teacher")
def teacher_students_work():
    with db_cursor(dictionary=True) as (_conn, cursor):
        cursor.execute(
            """
            SELECT a.id AS activity_id, a.title AS activity_title, a.due_date,
                   u.id AS student_id, u.username AS student_name, u.fullname, u.section,
                   s.id AS submission_id, s.answer_text, s.file_path, s.submitted_at
            FROM activities a
            JOIN users u ON (
                a.section = u.section OR a.section = 'All Sections'
                OR a.section IS NULL OR a.section = ''
            ) AND u.role = 'Student'
            LEFT JOIN submissions s ON s.activity_id = a.id AND s.student_id = u.id
            ORDER BY a.due_date, a.title, u.username
            """
        )
        records = cursor.fetchall()
    submitted = sum(1 for record in records if record["submission_id"])
    missing = len(records) - submitted
    return render_template(
        "teacher.html",
        page="students_work",
        **teacher_nav(),
        records=records,
        submitted=submitted,
        missing=missing,
    )


@app.route("/teacher/history/<int:activity_id>/<int:student_id>")
@login_required("Teacher")
def teacher_submission_history(activity_id, student_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT title FROM activities WHERE id=%s", (activity_id,))
        row = cursor.fetchone()
        title = row[0] if row else "Activity"
        cursor.execute(
            """
            SELECT id, answer_text, file_path FROM submission_history
            WHERE activity_id=%s AND student_id=%s ORDER BY id DESC
            """,
            (activity_id, student_id),
        )
        history = cursor.fetchall()
    return render_template(
        "teacher.html",
        page="history",
        **teacher_nav(),
        history=history,
        activity_title=title,
    )


@app.route("/teacher/profile", methods=["GET", "POST"])
@login_required("Teacher")
def teacher_profile():
    return handle_profile("teacher.html")


def handle_profile(template):
    user = current_user()
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip()
        contact = request.form.get("contact", "").strip()
        if not fullname:
            flash("Please enter your full name.", "warning")
            return redirect(request.path)
        profile = load_profile(user["username"])
        photo_path = profile["photo_path"] if profile else None
        uploaded = request.files.get("photo")
        if uploaded and uploaded.filename:
            ext = Path(uploaded.filename).suffix.lower()
            if ext not in PHOTO_EXTS:
                flash("Please select a PNG, JPG, JPEG, GIF, or WEBP image.", "warning")
                return redirect(request.path)
            path, _name, _ext = save_upload(uploaded, "profile_photos")
            photo_path = path
        with db_cursor() as (_conn, cursor):
            cursor.execute(
                """
                UPDATE users SET fullname=%s, email=%s, contact=%s, photo_path=%s
                WHERE username=%s
                """,
                (fullname, email, contact, photo_path, user["username"]),
            )
        session["fullname"] = fullname
        flash("Profile updated.", "success")
        return redirect(request.path)
    profile = load_profile(user["username"]) or {}
    extra = teacher_nav() if user["role"] == "Teacher" else {
        "subjects": ["All Subjects"] + get_student_subjects(user["id"], user["section"])
    }
    return render_template(template, page="profile", profile=profile, **extra)


def student_nav():
    user = current_user()
    return {
        "subjects": ["All Subjects"] + get_student_subjects(user["id"], user["section"])
    }


@app.route("/student")
@login_required("Student")
def student_dashboard():
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT a.title, a.due_date
            FROM activities a
            LEFT JOIN submissions s ON s.activity_id = a.id AND s.student_id = %s
            WHERE (a.section = %s OR a.section = 'All Sections' OR a.section IS NULL)
              AND s.id IS NULL AND a.due_date > NOW()
            ORDER BY a.due_date ASC
            """,
            (user["id"], user["section"]),
        )
        pending = cursor.fetchall()
        cursor.execute(
            """
            SELECT COUNT(*) FROM modules
            WHERE section = %s OR section = 'All Sections' OR section IS NULL
            """,
            (user["section"],),
        )
        module_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*) FROM announcements
            WHERE section = %s OR section = 'All Sections' OR section IS NULL
            """,
            (user["section"],),
        )
        announcement_count = cursor.fetchone()[0]
    return render_template(
        "student.html",
        page="dashboard",
        **student_nav(),
        pending=pending,
        pending_count=len(pending),
        module_count=module_count,
        announcement_count=announcement_count,
    )


@app.route("/student/modules")
@login_required("Student")
def student_modules():
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT id, title, description, filename, filepath, url, uploaded_at, subject
            FROM modules
            WHERE section = %s OR section = 'All Sections' OR section IS NULL
            ORDER BY uploaded_at DESC
            """,
            (user["section"],),
        )
        modules = cursor.fetchall()
    modules, chosen = subject_filter(modules, 7)
    assigned = get_student_subjects(user["id"], user["section"])
    if session.get("current_subject") == "All Subjects":
        enrollment = None
        with db_cursor() as (_conn, cursor):
            cursor.execute(
                "SELECT enrollment_type FROM student_enrollment_types WHERE student_id=%s",
                (user["id"],),
            )
            row = cursor.fetchone()
            enrollment = row[0] if row else "Regular"
        if enrollment == "Irregular":
            modules = [item for item in modules if not item[7] or item[7] in assigned]
    return render_template(
        "student.html",
        page="modules",
        **student_nav(),
        modules=modules,
        chosen_subject=chosen,
    )


@app.route("/student/activities")
@login_required("Student")
def student_activities():
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT a.id, a.title, a.description, a.due_date, a.attachment_path,
                   a.resource_url, a.subject
            FROM activities a
            LEFT JOIN submissions s ON s.activity_id = a.id AND s.student_id = %s
            WHERE (a.section = %s OR a.section = 'All Sections' OR a.section IS NULL)
              AND s.id IS NULL
            ORDER BY a.due_date ASC
            """,
            (user["id"], user["section"]),
        )
        activities = cursor.fetchall()
    activities, chosen = subject_filter(activities, 6)
    now = datetime.now()
    due_soon, missing = [], []
    for activity in activities:
        deadline = parse_deadline(activity[3])
        if deadline is not None and now > deadline:
            missing.append(activity)
        else:
            due_soon.append(activity)
    return render_template(
        "student.html",
        page="activities",
        **student_nav(),
        due_soon=due_soon,
        missing=missing,
        chosen_subject=chosen,
    )


@app.route("/student/submit/<int:activity_id>", methods=["GET", "POST"])
@login_required("Student")
def student_submit(activity_id):
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            "SELECT id, title, due_date FROM activities WHERE id=%s",
            (activity_id,),
        )
        activity = cursor.fetchone()
    if not activity:
        flash("This activity no longer exists.", "error")
        return redirect(url_for("student_activities"))
    if request.method == "POST":
        answer = request.form.get("answer", "").strip()
        uploaded = request.files.get("file")
        path, _name, _ext = save_upload(uploaded, "uploaded_submissions")
        if not answer and not path:
            flash("Please enter an answer or attach a file.", "warning")
            return redirect(url_for("student_submit", activity_id=activity_id))
        try:
            with db_cursor() as (_conn, cursor):
                cursor.execute(
                    """
                    SELECT id, answer_text, file_path FROM submissions
                    WHERE activity_id=%s AND student_id=%s
                    """,
                    (activity_id, user["id"]),
                )
                existing = cursor.fetchone()
                if existing:
                    cursor.execute(
                        """
                        INSERT INTO submission_history
                        (submission_id, activity_id, student_id, answer_text, file_path)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (existing[0], activity_id, user["id"], existing[1], existing[2]),
                    )
                    cursor.execute(
                        """
                        UPDATE submissions
                        SET answer_text=%s, file_path=%s, submitted_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                        """,
                        (answer or None, path, existing[0]),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO submissions (activity_id, student_id, answer_text, file_path)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (activity_id, user["id"], answer or None, path),
                    )
            flash("Your submission has been saved.", "success")
            return redirect(url_for("student_activities"))
        except Exception as error:
            flash(f"Could not save your submission: {error}", "error")
    return render_template(
        "student.html",
        page="submit",
        **student_nav(),
        activity=activity,
    )


@app.route("/student/history")
@login_required("Student")
def student_history():
    user = current_user()
    with db_cursor(dictionary=True) as (_conn, cursor):
        cursor.execute(
            """
            SELECT s.id AS submission_id, s.activity_id, s.answer_text, s.file_path,
                   s.submitted_at, a.title AS activity_title
            FROM submissions s
            JOIN activities a ON a.id = s.activity_id
            WHERE s.student_id=%s
            ORDER BY s.submitted_at DESC
            """,
            (user["id"],),
        )
        records = cursor.fetchall()
    return render_template(
        "student.html",
        page="history",
        **student_nav(),
        records=records,
    )


@app.route("/student/history/<int:activity_id>")
@login_required("Student")
def student_previous_versions(activity_id):
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT title FROM activities WHERE id=%s", (activity_id,))
        row = cursor.fetchone()
        title = row[0] if row else "Activity"
        cursor.execute(
            """
            SELECT id, answer_text, file_path FROM submission_history
            WHERE activity_id=%s AND student_id=%s ORDER BY id DESC
            """,
            (activity_id, user["id"]),
        )
        versions = cursor.fetchall()
    return render_template(
        "student.html",
        page="versions",
        **student_nav(),
        versions=versions,
        activity_title=title,
    )


@app.route("/student/announcements")
@login_required("Student")
def student_announcements():
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT id, title, description, attachment_path, section, created_at, subject
            FROM announcements
            WHERE section = %s OR section = 'All Sections' OR section IS NULL
            ORDER BY created_at DESC
            """,
            (user["section"],),
        )
        announcements = cursor.fetchall()
    with db_cursor(dictionary=True) as (_conn, cursor):
        cursor.execute(
            """
            SELECT a.id, a.title, a.section, a.deadline, r.status, r.marked_at
            FROM attendance_sessions a
            LEFT JOIN attendance_records r
              ON r.attendance_id = a.id AND r.student_id = %s
            WHERE a.attendance_date = CURDATE()
              AND (a.section = %s OR a.section = 'All Sections' OR a.section IS NULL OR a.section = '')
            ORDER BY a.created_at DESC
            """,
            (user["id"], user["section"]),
        )
        attendance_items = cursor.fetchall()
    now = datetime.now()
    for item in attendance_items:
        deadline = item["deadline"]
        if isinstance(deadline, str):
            deadline = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
        item["deadline_dt"] = deadline
        item["open"] = now < deadline and not item["marked_at"]
    return render_template(
        "student.html",
        page="announcements",
        **student_nav(),
        announcements=announcements,
        attendance_items=attendance_items,
    )


@app.route("/student/attendance/<int:attendance_id>", methods=["POST"])
@login_required("Student")
def student_mark_attendance(attendance_id):
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            "SELECT deadline FROM attendance_sessions WHERE id=%s",
            (attendance_id,),
        )
        row = cursor.fetchone()
        if not row:
            flash("This attendance session no longer exists.", "error")
            return redirect(url_for("student_announcements"))
        deadline = row[0]
        if isinstance(deadline, str):
            deadline = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
        if datetime.now() >= deadline:
            flash("The deadline has passed. You can no longer mark attendance.", "warning")
            return redirect(url_for("student_announcements"))
        cursor.execute(
            """
            INSERT IGNORE INTO attendance_records (attendance_id, student_id, status, marked_at)
            VALUES (%s, %s, 'Present', NOW())
            """,
            (attendance_id, user["id"]),
        )
    flash("Your Present status has been saved.", "success")
    return redirect(url_for("student_announcements"))


@app.route("/student/reviewer", methods=["GET", "POST"])
@login_required("Student")
def student_reviewer():
    user = current_user()
    with db_cursor() as (_conn, cursor):
        cursor.execute(
            """
            SELECT id, title, filename, filepath FROM modules
            WHERE filepath IS NOT NULL AND filepath <> ''
            ORDER BY uploaded_at DESC
            """
        )
        modules = cursor.fetchall()
    summary = key_points = None
    questions = []
    selected_id = None
    if request.method == "POST":
        selected_id = int(request.form.get("module_id"))
        selected = next((module for module in modules if module[0] == selected_id), None)
        if not selected:
            flash("Please choose a module.", "warning")
        else:
            try:
                source_text = read_module_text(selected[3])
                summary, key_points, questions = make_reviewer_content(source_text)
            except Exception as error:
                flash(str(error), "error")
    return render_template(
        "student.html",
        page="reviewer",
        **student_nav(),
        modules=modules,
        summary=summary,
        key_points=key_points,
        questions=questions,
        selected_id=selected_id,
    )


@app.route("/student/profile", methods=["GET", "POST"])
@login_required("Student")
def student_profile():
    return handle_profile("student.html")


@app.route("/file/module/<int:module_id>")
@login_required()
def file_module(module_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT filepath FROM modules WHERE id=%s", (module_id,))
        row = cursor.fetchone()
    return serve_stored_file(row[0] if row else None)


@app.route("/file/activity/<int:activity_id>")
@login_required()
def file_activity(activity_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT attachment_path FROM activities WHERE id=%s", (activity_id,))
        row = cursor.fetchone()
    return serve_stored_file(row[0] if row else None)


@app.route("/file/announcement/<int:item_id>")
@login_required()
def file_announcement(item_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT attachment_path FROM announcements WHERE id=%s", (item_id,))
        row = cursor.fetchone()
    return serve_stored_file(row[0] if row else None)


@app.route("/file/submission/<int:submission_id>")
@login_required()
def file_submission(submission_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT file_path FROM submissions WHERE id=%s", (submission_id,))
        row = cursor.fetchone()
    return serve_stored_file(row[0] if row else None)


@app.route("/file/history/<int:history_id>")
@login_required()
def file_history(history_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT file_path FROM submission_history WHERE id=%s", (history_id,))
        row = cursor.fetchone()
    return serve_stored_file(row[0] if row else None)


@app.route("/file/photo/<int:user_id>")
@login_required()
def file_photo(user_id):
    with db_cursor() as (_conn, cursor):
        cursor.execute("SELECT photo_path FROM users WHERE id=%s", (user_id,))
        row = cursor.fetchone()
    return serve_stored_file(row[0] if row else None)


setup_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

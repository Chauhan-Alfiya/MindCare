from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
UPLOAD_FOLDER = "static/resources"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.secret_key = "mindcare123"


# ===========================
# DATABASE CONNECTION
# ===========================

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="mindcare"
    )

# ===========================
# HOME PAGE
# ===========================

@app.route("/")
def home():
    return render_template("home.html")


# ===========================
# ABOUT PAGE
# ===========================

@app.route("/about")
def about():
    return render_template("about.html")





# ===========================
# AI CHAT PAGE
# ===========================

@app.route("/chatbot")
def chatbot():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "STUDENT":
        return redirect(url_for("login"))

    return render_template("chatbot.html")




# ===========================
# COMMON DASHBOARD REDIRECT
# ===========================

@app.route("/dashboard")
def dashboard_redirect():

    if "user_id" not in session:
        return redirect(url_for("login"))


    role = session.get("role")


    if role == "ADMIN":
        return redirect(url_for("admin_dashboard"))


    elif role == "COUNSELLOR":
        return redirect(url_for("counsellor_dashboard"))


    elif role == "STUDENT":
        return redirect(url_for("student_dashboard"))


    return redirect(url_for("login"))
# ===========================
# APPOINTMENT
# ===========================

@app.route("/appointment", methods=["GET", "POST"])
def appointment():

    # ===========================
    # LOGIN CHECK
    # ===========================

    if "user_id" not in session:
        return redirect(url_for("login"))

    # ===========================
    # STUDENT ONLY
    # ===========================

    if session.get("role") != "STUDENT":
        return redirect(url_for("login"))

    student_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        # =================================================
        # POST - BOOK APPOINTMENT
        # =================================================

        if request.method == "POST":

            counsellor_id = request.form.get(
                "counsellor_id",
                ""
            ).strip()

            appointment_date = request.form.get(
                "appointment_date",
                ""
            ).strip()

            appointment_time = request.form.get(
                "appointment_time",
                ""
            ).strip()

            reason = request.form.get(
                "reason",
                ""
            ).strip()

            # ===========================
            # REQUIRED FIELDS
            # ===========================

            if (
                not counsellor_id
                or not appointment_date
                or not appointment_time
            ):

                flash(
                    "Please select counsellor, date and time."
                )

                return redirect(
                    url_for("appointment")
                )

            # ===========================
            # CHECK COUNSELLOR
            # ===========================

            cursor.execute("""
                SELECT
                    u.user_id,
                    u.username

                FROM users u

                INNER JOIN roles r
                    ON u.role_id = r.role_id

                INNER JOIN counsellor_details c
                    ON u.user_id = c.user_id

                WHERE u.user_id = %s

                  AND r.role = 'COUNSELLOR'

                  AND u.is_active = TRUE

                  AND u.is_deleted = FALSE
            """, (counsellor_id,))

            counsellor = cursor.fetchone()

            if not counsellor:

                flash(
                    "Selected counsellor is not available."
                )

                return redirect(
                    url_for("appointment")
                )

            # ===========================
            # CHECK DATE
            # ===========================

            cursor.execute("""
                SELECT CURDATE() AS today
            """)

            today = cursor.fetchone()["today"]

            from datetime import datetime

            try:

                selected_date = datetime.strptime(
                    appointment_date,
                    "%Y-%m-%d"
                ).date()

            except ValueError:

                flash(
                    "Invalid appointment date."
                )

                return redirect(
                    url_for("appointment")
                )

            if selected_date < today:

                flash(
                    "Please select today or a future date."
                )

                return redirect(
                    url_for("appointment")
                )

            # ===========================
            # CHECK COUNSELLOR SLOT
            # ===========================

            cursor.execute("""
                SELECT appointment_id

                FROM appointments

                WHERE counsellor_id = %s

                  AND appointment_date = %s

                  AND appointment_time = %s

                  AND status IN (
                      'Pending',
                      'Approved'
                  )
            """, (
                counsellor_id,
                appointment_date,
                appointment_time
            ))

            existing_slot = cursor.fetchone()

            if existing_slot:

                flash(
                    "This time slot is already booked. Please select another time."
                )

                return redirect(
                    url_for("appointment")
                )

            # ===========================
            # CHECK STUDENT SLOT
            # ===========================

            cursor.execute("""
                SELECT appointment_id

                FROM appointments

                WHERE user_id = %s

                  AND appointment_date = %s

                  AND appointment_time = %s

                  AND status IN (
                      'Pending',
                      'Approved'
                  )
            """, (
                student_id,
                appointment_date,
                appointment_time
            ))

            student_existing = cursor.fetchone()

            if student_existing:

                flash(
                    "You already have an appointment at this date and time."
                )

                return redirect(
                    url_for("appointment")
                )

            # ===========================
            # INSERT APPOINTMENT
            # ===========================

            cursor.execute("""
                INSERT INTO appointments
                (
                    user_id,
                    counsellor_id,
                    appointment_date,
                    appointment_time,
                    reason,
                    status
                )

                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'Pending'
                )
            """, (
                student_id,
                counsellor_id,
                appointment_date,
                appointment_time,
                reason if reason else None
            ))

            db.commit()

            flash(
                "Counselling appointment request submitted successfully."
            )

            return redirect(
                url_for("student_dashboard")
            )

        # =================================================
        # GET - LOAD COUNSELLORS
        # =================================================

        cursor.execute("""
            SELECT

                u.user_id,
                u.username,
                u.email,

                c.qualification,
                c.specialization,
                c.experience

            FROM users u

            INNER JOIN roles r
                ON u.role_id = r.role_id

            INNER JOIN counsellor_details c
                ON u.user_id = c.user_id

            WHERE r.role = 'COUNSELLOR'

              AND u.is_active = TRUE

              AND u.is_deleted = FALSE

            ORDER BY u.username ASC
        """)

        counsellors = cursor.fetchall()

        # ===========================
        # TODAY'S DATE
        # ===========================

        cursor.execute("""
            SELECT CURDATE() AS today
        """)

        today_value = cursor.fetchone()["today"]

        today = today_value.strftime("%Y-%m-%d")

    except mysql.connector.Error as err:

        db.rollback()

        print(
            "Appointment Database Error:",
            err
        )

        flash(
            "Unable to process appointment. Please try again."
        )

        return redirect(
            url_for("student_dashboard")
        )

    finally:

        cursor.close()
        db.close()

    # ===========================
    # RENDER PAGE
    # ===========================

    return render_template(
        "appointment.html",
        counsellors=counsellors,
        today=today
    )
# ===========================
# REGISTER
# ===========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        # FORM DATA
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        selected_role = request.form.get("role", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )
        # REQUIRED FIELDS

        if not username or not email or not selected_role:

            flash("Please fill all required fields.")

            return redirect(
                url_for("register")
            )

        # PASSWORD MATCH

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(
                url_for("register")
            )

        # VALID ROLE

        if selected_role not in [
            "STUDENT",
            "COUNSELLOR"
        ]:
            flash("Please select a valid role.")
            return redirect(
                url_for("register")
            )

        db = get_db_connection()
        cursor = db.cursor()

        try:
            # CHECK EMAIL

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE email = %s
                """,
                (email,)
            )
            if cursor.fetchone():
                flash("Email already exists.")
                return redirect(
                    url_for("register")
                )
            # CHECK USERNAME

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE username = %s
                """,
                (username,)
            )
            if cursor.fetchone():
                flash("Username already exists.")
                return redirect(
                    url_for("register")
                )

            # GET ROLE ID

            cursor.execute(
                """
                SELECT role_id
                FROM roles
                WHERE role = %s
                """,
                (selected_role,)
            )
            role_data = cursor.fetchone()

            if not role_data:
                flash(
                    "Selected role does not exist."
                )
                return redirect(
                    url_for("register")
                )

            role_id = role_data[0]

            # HASH PASSWORD

            password_hash = generate_password_hash(
                password
            )

            # INSERT INTO USERS

            cursor.execute(
                """
                INSERT INTO users
                (
                    username,
                    email,
                    password,
                    role_id
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    username,
                    email,
                    password_hash,
                    role_id
                )
            )

            user_id = cursor.lastrowid

            # STUDENT DETAILS

            if selected_role == "STUDENT":
                student_class = request.form.get(
                    "class",
                    ""
                ).strip()
                stream = request.form.get(
                    "stream",
                    ""
                ).strip()
                if not student_class or not stream:
                    db.rollback()
                    flash(
                        "Please select class and stream."
                    )
                    return redirect(
                        url_for("register")
                    )
                cursor.execute(
                    """
                    INSERT INTO student_details
                    (
                        user_id,
                        class,
                        stream
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        user_id,
                        student_class,
                        stream
                    )
                )

            # COUNSELLOR DETAILS

            elif selected_role == "COUNSELLOR":
                qualification = request.form.get(
                    "qualification",
                    ""
                ).strip()
                specialization = request.form.get(
                    "specialization",
                    ""
                ).strip()
                experience = request.form.get(
                    "experience",
                    "0"
                ).strip()
                if not qualification or not specialization:
                    db.rollback()
                    flash(
                        "Please enter qualification and specialization."
                    )
                    return redirect(
                        url_for("register")
                    )
                if not experience:
                    experience = 0
                cursor.execute(
                    """
                    INSERT INTO counsellor_details
                    (
                        user_id,
                        qualification,
                        specialization,
                        experience
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        user_id,
                        qualification,
                        specialization,
                        experience
                    )
                )

            # SAVE

            db.commit()
            flash(
                "Registration Successful."
            )
            return redirect(
                url_for("login")
            )
        except mysql.connector.Error as err:
            db.rollback()
            print(
                "Registration Error:",
                err
            )
            flash(
                "Registration failed."
            )
            return redirect(
                url_for("register")
            )
        finally:
            cursor.close()
            db.close()
    return render_template(
        "register.html"
    )

# ===========================
# LOGIN
# ===========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        try:
            # ===========================
            # GET USER + ROLE
            # ===========================
            cursor.execute(
                """
                SELECT
                    users.user_id,
                    users.username,
                    users.email,
                    users.password,
                    users.role_id,
                    users.is_active,
                    users.is_deleted,
                    roles.role
                FROM users
                INNER JOIN roles
                    ON users.role_id =
                       roles.role_id
                WHERE users.username = %s
                """,
                (username,)
            )
            user = cursor.fetchone()
        except mysql.connector.Error as err:
            print(
                "Login Database Error:",
                err
            )
            flash(
                "Login failed. Please try again."
            )
            cursor.close()
            db.close()
            return render_template(
                "login.html"
            )
        
        finally:
            try:
                cursor.close()
                db.close()
            except:
                pass

        # ===========================
        # USER NOT FOUND
        # ===========================
        if not user:
            flash(
                "Invalid Username or Password."
            )
            return render_template(
                "login.html"
            )

        # ===========================
        # ACCOUNT STATUS
        # ===========================
        if not user["is_active"]:
            flash(
                "Your account is inactive."
            )
            return render_template(
                "login.html"
            )
        if user["is_deleted"]:

            flash(
                "Your account has been deleted."
            )

            return render_template(
                "login.html"
            )
        # ===========================
        # PASSWORD CHECK
        # ===========================
        try:
            password_valid = check_password_hash(user["password"],password)
        except (ValueError, TypeError):
            password_valid = False
        if not password_valid:
            flash(
                "Invalid Username or Password."
            )
            return render_template(
                "login.html"
            )
        # ===========================
        # SESSION
        # ===========================
        session.clear()
        session["user_id"] = user["user_id"]
        session["username"] = user["username"]
        session["email"] = user["email"]
        session["role"] = user["role"]
        # ===========================
        # ROLE REDIRECTION
        # ===========================
        if user["role"] == "ADMIN":
            return redirect(
                url_for("admin_dashboard")
            )
        elif user["role"] == "COUNSELLOR":
            return redirect(
                url_for("counsellor_dashboard")
            )
        elif user["role"] == "STUDENT":
            return redirect(
                url_for("student_dashboard")
            )
        else:
            session.clear()
            flash(
                "Invalid user role."
            )
            return redirect(
                url_for("login")
            )
    return render_template(
        "login.html"
    )

# ===========================
# STUDENT DASHBOARD
# ===========================
@app.route("/student_dashboard")
def student_dashboard():

    # =========================== LOGIN CHECK ===========================
    if "user_id" not in session:
        return redirect(url_for("login"))
    #=========================== ROLE CHECK # ===========================
    if session.get("role") != "STUDENT":
        return redirect(url_for("login"))
    user_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # =========================== STUDENT PROFILE  ===========================
        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                s.class,
                s.stream
            FROM users u
            INNER JOIN student_details s
                ON u.user_id = s.user_id
            WHERE u.user_id = %s
        """, (user_id,))
        student = cursor.fetchone()

        # ===========================
        # TOTAL ASSESSMENTS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM assessments
            WHERE user_id = %s
        """, (user_id,))
        total_assessments = cursor.fetchone()["total"]

        # ===========================
        # PENDING APPOINTMENTS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
            WHERE user_id = %s
            AND status = 'Pending'
        """, (user_id,))
        pending_appointments = cursor.fetchone()["total"]

        # ===========================
        # WELLNESS CHECK-INS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM wellness_tracker
            WHERE user_id = %s
        """, (user_id,))
        wellness_checkins = cursor.fetchone()["total"]

    except mysql.connector.Error as err:

        print("Student Dashboard Database Error:", err)
        flash("Unable to load student dashboard.")
        return redirect(url_for("logout"))

    finally:
        cursor.close()
        db.close()
    # ===========================
    # STUDENT PROFILE NOT FOUND
    # ===========================
    if not student:
        flash("Student profile not found.")
        return redirect(url_for("logout"))
    # ===========================
    # RENDER DASHBOARD
    # ===========================
    return render_template(
        "student_dashboard.html",
        student=student,
        total_assessments=total_assessments,
        pending_appointments=pending_appointments,
        wellness_checkins=wellness_checkins
    )
# ===========================
# ADMIN DASHBOARD
# ===========================

@app.route("/admin_dashboard")
def admin_dashboard():

    # ===========================
    # LOGIN CHECK
    # ===========================
    if "user_id" not in session:
        return redirect(url_for("login"))

    # ===========================
    # ADMIN ONLY
    # ===========================
    if session.get("role") != "ADMIN":
        return redirect(url_for("dashboard_redirect"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        # ===========================
        # TOTAL STUDENTS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM users u
            INNER JOIN roles r
            ON u.role_id = r.role_id
            WHERE r.role = 'STUDENT'
            AND u.is_deleted = FALSE
        """)
        total_students = cursor.fetchone()["total"]

        # ===========================
        # TOTAL COUNSELLORS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM users u
            INNER JOIN roles r
            ON u.role_id = r.role_id
            WHERE r.role = 'COUNSELLOR'
            AND u.is_deleted = FALSE
        """)
        total_counsellors = cursor.fetchone()["total"]

        # ===========================
        # TOTAL ASSESSMENTS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM assessments
        """)
        total_assessments = cursor.fetchone()["total"]

        # ===========================
        # TOTAL APPOINTMENTS
        # ===========================
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM appointments
        """)
        total_appointments = cursor.fetchone()["total"]

        # ===========================
        # RECENT STUDENTS
        # ===========================
        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                u.is_active,
                u.created_at
            FROM users u
            INNER JOIN roles r
            ON u.role_id = r.role_id
            WHERE r.role = 'STUDENT'
            AND u.is_deleted = FALSE
            ORDER BY u.created_at DESC
            LIMIT 5
        """)
        students = cursor.fetchall()

        # ===========================
        # RECENT COUNSELLORS
        # ===========================
        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                u.is_active,
                u.created_at
            FROM users u
            INNER JOIN roles r
            ON u.role_id = r.role_id
            WHERE r.role = 'COUNSELLOR'
            AND u.is_deleted = FALSE
            ORDER BY u.created_at DESC
            LIMIT 5
        """)
        counsellors = cursor.fetchall()

        # ===========================
        # RECENT APPOINTMENTS
        # ===========================
        cursor.execute("""
            SELECT
                a.appointment_id,
                s.username AS student_name,
                c.username AS counsellor_name,
                a.appointment_date,
                a.appointment_time,
                a.status
            FROM appointments a
            INNER JOIN users s
            ON a.user_id = s.user_id
            INNER JOIN users c
            ON a.counsellor_id = c.user_id
            ORDER BY a.created_at DESC
            LIMIT 5
        """)
        appointments = cursor.fetchall()

        # ===========================
        # RECENT ASSESSMENTS
        # ===========================
        cursor.execute("""
            SELECT
                a.assessment_id,
                u.username,
                a.assessment_type,
                a.score,
                a.risk_level,
                a.created_at
            FROM assessments a
            INNER JOIN users u
            ON a.user_id = u.user_id
            ORDER BY a.created_at DESC
            LIMIT 5
        """)
        assessments = cursor.fetchall()

    except mysql.connector.Error as err:

        print("Admin Dashboard Error:",err)
        flash("Unable to load admin dashboard.")
        return redirect(
            url_for("logout")
        )

    finally:

        cursor.close()
        db.close()

    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        total_counsellors=total_counsellors,
        total_assessments=total_assessments,
        total_appointments=total_appointments,
        students=students,
        counsellors=counsellors,
        appointments=appointments,
        assessments=assessments
    )
# ===========================
# COUNSELLOR DASHBOARD
# ===========================

@app.route("/counsellor_dashboard")
def counsellor_dashboard():

    # ===========================
    # LOGIN CHECK
    # ===========================

    if "user_id" not in session:
        return redirect(url_for("login"))

    # ===========================
    # ROLE CHECK
    # ===========================

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("login"))

    counsellor_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        # ===========================
        # COUNSELLOR PROFILE
        # ===========================

        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                u.created_at,

                c.qualification,
                c.specialization,
                c.experience

            FROM users u

            LEFT JOIN counsellor_details c
                ON u.user_id = c.user_id

            WHERE u.user_id = %s
        """, (counsellor_id,))

        counsellor = cursor.fetchone()

        # ===========================
        # PENDING APPOINTMENTS
        # ===========================

        cursor.execute("""
            SELECT COUNT(*) AS total

            FROM appointments

            WHERE counsellor_id = %s
            AND status = 'Pending'
        """, (counsellor_id,))

        pending = cursor.fetchone()["total"]

        # ===========================
        # TODAY'S SESSIONS
        # ===========================

        cursor.execute("""
            SELECT COUNT(*) AS total

            FROM appointments

            WHERE counsellor_id = %s
            AND appointment_date = CURDATE()
            AND status != 'Cancelled'
        """, (counsellor_id,))

        today_sessions = cursor.fetchone()["total"]

        # ===========================
        # COMPLETED SESSIONS
        # ===========================

        cursor.execute("""
            SELECT COUNT(*) AS total

            FROM appointments

            WHERE counsellor_id = %s
            AND status = 'Completed'
        """, (counsellor_id,))

        completed = cursor.fetchone()["total"]

        # ===========================
        # STUDENTS UNDER MONITORING
        # ===========================

        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) AS total

            FROM appointments

            WHERE counsellor_id = %s
        """, (counsellor_id,))

        students = cursor.fetchone()["total"]

        # ===========================
        # COUNSELLOR STATS
        # ===========================

        stats = {
            "pending": pending,
            "today_sessions": today_sessions,
            "completed": completed,
            "students": students
        }

        # ===========================
        # COUNSELLING SCHEDULE
        # ===========================

        cursor.execute("""
            SELECT

                a.appointment_id,
                a.appointment_date,
                a.appointment_time,
                a.reason,
                a.status,

                u.username,
                u.email,

                s.class,
                s.stream

            FROM appointments a

            INNER JOIN users u
                ON a.user_id = u.user_id

            INNER JOIN student_details s
                ON u.user_id = s.user_id

            WHERE a.counsellor_id = %s

            ORDER BY
                a.appointment_date ASC,
                a.appointment_time ASC
        """, (counsellor_id,))

        appointments = cursor.fetchall()
         # ===========================
                # STUDENTS WITH CHAT
                # ===========================
        
        cursor.execute("""
                    SELECT DISTINCT
                        u.user_id,
                        u.username,
                        u.email,
                        s.class,
                        s.stream
                    FROM counsellor_chat cc
        
                    INNER JOIN users u
                        ON cc.student_id = u.user_id
        
                    LEFT JOIN student_details s
                        ON u.user_id = s.user_id
        
                    WHERE cc.counsellor_id = %s
        
                    ORDER BY cc.created_at DESC
                """, (counsellor_id,))
        
        chat_students = cursor.fetchall()

    except mysql.connector.Error as err:

        print(
            "Counsellor Dashboard Database Error:",
            err
        )

        flash(
            "Unable to load counsellor dashboard."
        )

        return redirect(
            url_for("logout")
        )

    finally:

        cursor.close()
        db.close()
                

    # ===========================
    # COUNSELLOR PROFILE CHECK
    # ===========================

    if not counsellor:

        flash(
            "Counsellor profile not found."
        )

        return redirect(
            url_for("logout")
        )

    # ===========================
    # RENDER DASHBOARD
    # ===========================

    return render_template(
    "counsellor_dashboard.html",
    counsellor=counsellor,
    stats=stats,
    appointments=appointments,
    chat_students=chat_students
    )
    # ===========================
# APPROVE APPOINTMENT
# ===========================

@app.route("/approve_appointment/<int:id>")
def approve_appointment(id):

    # ===========================
    # LOGIN CHECK
    # ===========================

    if "user_id" not in session:
        return redirect(url_for("login"))

    # ===========================
    # COUNSELLOR CHECK
    # ===========================

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("login"))

    counsellor_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor()

    try:

        # ===========================
        # CHECK APPOINTMENT
        # ===========================

        cursor.execute("""
            SELECT appointment_id
            FROM appointments
            WHERE appointment_id = %s
              AND counsellor_id = %s
              AND status = 'Pending'
        """, (
            id,
            counsellor_id
        ))

        appointment = cursor.fetchone()

        if not appointment:

            flash(
                "Appointment not found or already processed."
            )

            return redirect(
                url_for("counsellor_dashboard")
            )

        # ===========================
        # APPROVE
        # ===========================

        cursor.execute("""
            UPDATE appointments
            SET status = 'Approved'
            WHERE appointment_id = %s
              AND counsellor_id = %s
              AND status = 'Pending'
        """, (
            id,
            counsellor_id
        ))

        db.commit()

        flash(
            "Appointment approved successfully."
        )

    except mysql.connector.Error as err:

        db.rollback()

        print(
            "Approve Appointment Error:",
            err
        )

        flash(
            "Unable to approve appointment."
        )

    finally:

        cursor.close()
        db.close()

    return redirect(
        url_for("counsellor_dashboard")
    )


# ===========================
# CANCEL APPOINTMENT
# ===========================

@app.route("/cancel_appointment/<int:id>")
def cancel_appointment(id):

    # ===========================
    # LOGIN CHECK
    # ===========================

    if "user_id" not in session:
        return redirect(url_for("login"))

    # ===========================
    # COUNSELLOR CHECK
    # ===========================

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("login"))

    counsellor_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor()

    try:

        # ===========================
        # CHECK APPOINTMENT
        # ===========================

        cursor.execute("""
            SELECT appointment_id
            FROM appointments
            WHERE appointment_id = %s
              AND counsellor_id = %s
              AND status = 'Pending'
        """, (
            id,
            counsellor_id
        ))

        appointment = cursor.fetchone()

        if not appointment:

            flash(
                "Appointment not found or already processed."
            )

            return redirect(
                url_for("counsellor_dashboard")
            )

        # ===========================
        # CANCEL
        # ===========================

        cursor.execute("""
            UPDATE appointments
            SET status = 'Cancelled'
            WHERE appointment_id = %s
              AND counsellor_id = %s
              AND status = 'Pending'
        """, (
            id,
            counsellor_id
        ))

        db.commit()

        flash(
            "Appointment cancelled successfully."
        )

    except mysql.connector.Error as err:

        db.rollback()

        print(
            "Cancel Appointment Error:",
            err
        )

        flash(
            "Unable to cancel appointment."
        )

    finally:

        cursor.close()
        db.close()

    return redirect(
        url_for("counsellor_dashboard")
    )
    
    # ===========================
# MY APPOINTMENTS
# STUDENT + COUNSELLOR
# ===========================

@app.route("/my_appointments")
def my_appointments():

    # ===========================
    # LOGIN CHECK
    # ===========================

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    role = session.get("role")

    # ===========================
    # ROLE CHECK
    # ===========================

    if role not in ["STUDENT", "COUNSELLOR"]:
        return redirect(url_for("login"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        # =================================================
        # STUDENT
        # =================================================

        if role == "STUDENT":

            cursor.execute("""
                SELECT

                    a.appointment_id,
                    a.appointment_date,
                    a.appointment_time,
                    a.reason,
                    a.status,

                    cuser.username AS counsellor_name,

                    cd.qualification,
                    cd.specialization

                FROM appointments a

                INNER JOIN users cuser
                    ON a.counsellor_id = cuser.user_id

                LEFT JOIN counsellor_details cd
                    ON a.counsellor_id = cd.user_id

                WHERE a.user_id = %s

                ORDER BY
                    a.appointment_date DESC,
                    a.appointment_time DESC,
                    a.appointment_id DESC

            """, (user_id,))

            appointments = cursor.fetchall()


        # =================================================
        # COUNSELLOR
        # =================================================

        else:

            cursor.execute("""
                SELECT

                    a.appointment_id,
                    a.appointment_date,
                    a.appointment_time,
                    a.reason,
                    a.status,

                    suser.username AS student_name,
                    suser.email AS student_email,

                    sd.class AS student_class,
                    sd.stream AS student_stream

                FROM appointments a

                INNER JOIN users suser
                    ON a.user_id = suser.user_id

                LEFT JOIN student_details sd
                    ON a.user_id = sd.user_id

                WHERE a.counsellor_id = %s

                ORDER BY
                    a.appointment_date DESC,
                    a.appointment_time DESC,
                    a.appointment_id DESC

            """, (user_id,))

            appointments = cursor.fetchall()


    except mysql.connector.Error as err:

        print(
            "My Appointments Database Error:",
            err
        )

        flash(
            "Unable to load appointments."
        )

        if role == "STUDENT":

            return redirect(
                url_for("student_dashboard")
            )

        return redirect(
            url_for("counsellor_dashboard")
        )

    finally:

        cursor.close()
        db.close()


    # =================================================
    # SAME PAGE
    # =================================================

    return render_template(
        "my_appointments.html",
        appointments=appointments,
        role=role
    )# ===========================
# APPOINTMENT DETAIL
# STUDENT + COUNSELLOR
# ===========================

@app.route("/appointment_detail/<int:id>", methods=["GET", "POST"])
def appointment_detail(id):

    # ===========================
    # LOGIN CHECK
    # ===========================

    if "user_id" not in session:
        return redirect(url_for("login"))


    user_id = session["user_id"]
    role = session.get("role")


    # ===========================
    # ROLE CHECK
    # ===========================

    if role not in ["STUDENT", "COUNSELLOR"]:
        return redirect(url_for("login"))


    db = get_db_connection()
    cursor = db.cursor(dictionary=True)


    try:


        # =========================================
        # COUNSELLOR ACTION
        # APPROVE / CANCEL + MESSAGE
        # =========================================

        if request.method == "POST" and role == "COUNSELLOR":


            action = request.form.get("action")

            message = request.form.get(
                "counsellor_message"
            )


            if action == "approve":


                cursor.execute("""
                    UPDATE appointments

                    SET status = 'Approved',
                        counsellor_message = %s

                    WHERE appointment_id = %s
                    AND counsellor_id = %s

                """,
                (
                    message,
                    id,
                    user_id
                ))


                flash(
                    "Appointment Approved Successfully."
                )


            elif action == "cancel":


                cursor.execute("""
                    UPDATE appointments

                    SET status = 'Cancelled',
                        counsellor_message = %s

                    WHERE appointment_id = %s
                    AND counsellor_id = %s

                """,
                (
                    message,
                    id,
                    user_id
                ))


                flash(
                    "Appointment Cancelled."
                )


            db.commit()



        # =================================================
        # STUDENT VIEW
        # =================================================

        if role == "STUDENT":


            cursor.execute("""
                SELECT

                    a.appointment_id,
                    a.appointment_date,
                    a.appointment_time,
                    a.reason,
                    a.status,
                    a.counsellor_message,
                    a.created_at,


                    cuser.user_id AS counsellor_id,
                    cuser.username AS counsellor_name,
                    cuser.email AS counsellor_email,


                    cd.qualification,
                    cd.specialization,
                    cd.experience


                FROM appointments a


                INNER JOIN users cuser

                ON a.counsellor_id = cuser.user_id



                LEFT JOIN counsellor_details cd

                ON a.counsellor_id = cd.user_id



                WHERE a.appointment_id = %s

                AND a.user_id = %s


                LIMIT 1

            """,
            (
                id,
                user_id
            ))



            appointment = cursor.fetchone()



        # =================================================
        # COUNSELLOR VIEW
        # =================================================

        else:



            cursor.execute("""
                SELECT


                    a.appointment_id,
                    a.appointment_date,
                    a.appointment_time,
                    a.reason,
                    a.status,
                    a.counsellor_message,
                    a.created_at,


                    suser.user_id AS student_id,
                    suser.username AS student_name,
                    suser.email AS student_email,


                    sd.class AS student_class,
                    sd.stream AS student_stream


                FROM appointments a



                INNER JOIN users suser

                ON a.user_id = suser.user_id



                LEFT JOIN student_details sd

                ON a.user_id = sd.user_id



                WHERE a.appointment_id = %s

                AND a.counsellor_id = %s


                LIMIT 1


            """,
            (
                id,
                user_id
            ))



            appointment = cursor.fetchone()



    except mysql.connector.Error as err:


        print(
            "Appointment Detail Error:",
            err
        )


        flash(
            "Unable to update appointment."
        )


        return redirect(
            url_for("my_appointments")
        )



    finally:


        cursor.close()
        db.close()



    # ===========================
    # NOT FOUND
    # ===========================


    if not appointment:


        flash(
            "Appointment not found."
        )


        return redirect(
            url_for("my_appointments")
        )



    # ===========================
    # SAME PAGE RENDER
    # ===========================


    return render_template(

        "appointment_detail.html",

        appointment=appointment,

        role=role

    )
    # ===========================
# WELLNESS TRACKER
# ===========================

@app.route("/wellness_tracker", methods=["GET", "POST"])
def wellness_tracker():

    # Login Check
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":

        mood = request.form["mood"]
        stress_level = request.form["stress_level"]
        sleep_hours = request.form["sleep_hours"]
        note = request.form["note"]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO wellness_tracker
            (user_id, mood, stress_level, sleep_hours, note)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            user_id,
            mood,
            stress_level,
            sleep_hours,
            note
        ))

        conn.commit()
        cursor.close()
        conn.close()

        flash("Wellness record saved successfully.")

        return redirect(url_for("wellness_tracker"))

    return render_template(
        "wellness_tracker.html",
        role=session.get("role")
    )
    # ===========================
# WELLNESS HISTORY
# ===========================

@app.route("/wellness_history")
def wellness_history():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *
        FROM wellness_tracker
        WHERE user_id=%s
        ORDER BY created_at DESC
    """,(user_id,))

    records = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "wellness_history.html",
        records=records,
        role=session.get("role")
    )
# ===========================
# ALL COUNSELLORS PAGE
# ===========================

@app.route("/counsellors")
def counsellors():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "STUDENT":
        return redirect(url_for("dashboard_redirect"))


    db = get_db_connection()
    cursor = db.cursor(dictionary=True)


    try:

        cursor.execute("""
            SELECT

                u.user_id,
                u.username,
                u.email,

                c.qualification,
                c.specialization,
                c.experience

            FROM users u

            INNER JOIN roles r
            ON u.role_id = r.role_id

            LEFT JOIN counsellor_details c
            ON u.user_id = c.user_id


            WHERE r.role = 'COUNSELLOR'

            ORDER BY u.username ASC

        """)


        counsellors = cursor.fetchall()


        #print("COUNSELLORS DATA:", counsellors)



    except mysql.connector.Error as err:

        print(
            "Counsellor Page Error:",
            err
        )

        flash(
            "Unable to load counsellors."
        )

        counsellors = []



    finally:

        cursor.close()
        db.close()



    return render_template(
        "counsellors.html",
        counsellors=counsellors
    )
## ===========================
# WELLNESS RESOURCES
# ===========================

@app.route("/resources", methods=["GET", "POST"])
def resources():

    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # ADD RESOURCE
    if request.method == "POST" and session.get("role") == "ADMIN":
        print(request.form)
        print(request.form)   # Testing

        title = request.form["title"]
        category = request.form["category"]
        description = request.form["description"]
        language = request.form["language"]
        pdf = request.files["pdf"]  
        filename = secure_filename(pdf.filename)
        pdf.save(
            os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )
        )

        file_path = "resources/" + filename

        cursor.execute("""
            INSERT INTO wellness_resources
            (title, category, description, language, file_path)
            VALUES (%s, %s, %s, %s, %s)
            """, (
            title,
            category,
            description,
            language,
            file_path
        ))
        cursor.execute("""
            INSERT INTO wellness_resources
            (title, category, description, language, file_path)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            title,
            category,
            description,
            language,
            file_path
        ))

        db.commit()
        flash("Resource Added Successfully!")
        return redirect(url_for("resources"))

    # SHOW RESOURCES
    cursor.execute("""
        SELECT *
        FROM wellness_resources
        ORDER BY resource_id DESC
    """)

    resources = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "resources.html",
        resources=resources
    )
    # ===========================
# EDIT RESOURCE
# ===========================

@app.route("/edit_resource/<int:resource_id>", methods=["GET", "POST"])
def edit_resource(resource_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "ADMIN":
        return redirect(url_for("dashboard_redirect"))

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":

        title = request.form["title"]
        category = request.form["category"]
        description = request.form["description"]
        language = request.form["language"]
        file_path = request.form["file_path"]

        cursor.execute("""

            UPDATE wellness_resources

            SET

                title=%s,
                category=%s,
                description=%s,
                language=%s,
                file_path=%s

            WHERE resource_id=%s

        """,(

            title,
            category,
            description,
            language,
            file_path,
            resource_id

        ))

        db.commit()

        flash("Resource Updated Successfully!")

        cursor.close()
        db.close()

        return redirect(url_for("resources"))

    cursor.execute("""

        SELECT *

        FROM wellness_resources

        WHERE resource_id=%s

    """,(resource_id,))

    resource = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template(

        "edit_resource.html",

        resource=resource

    )
    # ===========================
# DELETE RESOURCE
# ===========================

@app.route("/delete_resource/<int:resource_id>")
def delete_resource(resource_id):

    print("Deleting:", resource_id)

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute(
        "DELETE FROM wellness_resources WHERE resource_id=%s",
        (resource_id,)
    )

    print(cursor.rowcount)

    db.commit()

    cursor.close()
    db.close()

    flash("Deleted")

    return redirect(url_for("resources"))
    
# ============================================================
# PROFILE
# STUDENT + COUNSELLOR + ADMIN
# ============================================================

@app.route("/profile", methods=["GET", "POST"])
def profile():

    # --------------------------------------------------------
    # LOGIN CHECK
    # --------------------------------------------------------

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        # ====================================================
        # UPDATE PROFILE
        # ====================================================

        if request.method == "POST" and request.form.get("update_profile"):

            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()

            # ------------------------------------------------
            # REQUIRED FIELDS
            # ------------------------------------------------

            if not name or not email:

                flash(
                    "Name and email are required.",
                    "danger"
                )

                return redirect(url_for("profile"))

            # ------------------------------------------------
            # CHECK EMAIL
            # ------------------------------------------------

            cursor.execute("""
                SELECT user_id
                FROM users
                WHERE email = %s
                AND user_id != %s
            """, (
                email,
                user_id
            ))

            existing_email = cursor.fetchone()

            if existing_email:

                flash(
                    "This email is already registered.",
                    "danger"
                )

                return redirect(url_for("profile"))

            # ------------------------------------------------
            # UPDATE BASIC USER INFORMATION
            # ------------------------------------------------

            cursor.execute("""
                UPDATE users
                SET
                    username = %s,
                    email = %s
                WHERE user_id = %s
            """, (
                name,
                email,
                user_id
            ))

            # =================================================
            # GET ROLE
            # =================================================

            cursor.execute("""
                SELECT r.role
                FROM users u

                INNER JOIN roles r
                    ON u.role_id = r.role_id

                WHERE u.user_id = %s
            """, (user_id,))

            role_data = cursor.fetchone()

            if not role_data:

                db.rollback()

                flash(
                    "User role could not be found.",
                    "danger"
                )

                return redirect(url_for("profile"))

            role = role_data["role"].upper()

            # =================================================
            # STUDENT PROFILE
            # =================================================

            if role == "STUDENT":

                student_class = request.form.get(
                    "class",
                    ""
                ).strip()

                stream = request.form.get(
                    "stream",
                    ""
                ).strip()

                if not student_class or not stream:

                    db.rollback()

                    flash(
                        "Please select class and stream.",
                        "danger"
                    )

                    return redirect(url_for("profile"))

                # Check whether details already exist
                cursor.execute("""
                    SELECT user_id
                    FROM student_details
                    WHERE user_id = %s
                """, (user_id,))

                student_exists = cursor.fetchone()

                if student_exists:

                    cursor.execute("""
                        UPDATE student_details

                        SET
                            class = %s,
                            stream = %s

                        WHERE user_id = %s
                    """, (
                        student_class,
                        stream,
                        user_id
                    ))

                else:

                    cursor.execute("""
                        INSERT INTO student_details
                        (
                            user_id,
                            class,
                            stream
                        )

                        VALUES
                        (
                            %s,
                            %s,
                            %s
                        )
                    """, (
                        user_id,
                        student_class,
                        stream
                    ))

            # =================================================
            # COUNSELLOR PROFILE
            # =================================================

            elif role == "COUNSELLOR":

                qualification = request.form.get(
                    "qualification",
                    ""
                ).strip()

                specialization = request.form.get(
                    "specialization",
                    ""
                ).strip()

                experience = request.form.get(
                    "experience",
                    ""
                ).strip()

                # Empty experience = 0
                if not experience:
                    experience = 0

                # Check whether details already exist
                cursor.execute("""
                    SELECT user_id
                    FROM counsellor_details
                    WHERE user_id = %s
                """, (user_id,))

                counsellor_exists = cursor.fetchone()

                if counsellor_exists:

                    cursor.execute("""
                        UPDATE counsellor_details

                        SET
                            qualification = %s,
                            specialization = %s,
                            experience = %s

                        WHERE user_id = %s
                    """, (
                        qualification,
                        specialization,
                        experience,
                        user_id
                    ))

                else:

                    cursor.execute("""
                        INSERT INTO counsellor_details
                        (
                            user_id,
                            qualification,
                            specialization,
                            experience
                        )

                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                    """, (
                        user_id,
                        qualification,
                        specialization,
                        experience
                    ))

            # =================================================
            # SAVE CHANGES
            # =================================================

            db.commit()

            # Update session information
            session["username"] = name
            session["email"] = email

            flash(
                "Profile updated successfully.",
                "success"
            )

            return redirect(url_for("profile"))

        # ====================================================
        # CHANGE PASSWORD
        # ====================================================

        if request.method == "POST" and request.form.get("change_password"):

            current_password = request.form.get(
                "current_password",
                ""
            )

            new_password = request.form.get(
                "new_password",
                ""
            )

            confirm_password = request.form.get(
                "confirm_password",
                ""
            )

            # ------------------------------------------------
            # REQUIRED
            # ------------------------------------------------

            if not current_password or not new_password or not confirm_password:

                flash(
                    "Please fill all password fields.",
                    "danger"
                )

                return redirect(url_for("profile"))

            # ------------------------------------------------
            # PASSWORD MATCH
            # ------------------------------------------------

            if new_password != confirm_password:

                flash(
                    "New password and confirm password do not match.",
                    "danger"
                )

                return redirect(url_for("profile"))

            # ------------------------------------------------
            # PASSWORD LENGTH
            # ------------------------------------------------

            if len(new_password) < 6:

                flash(
                    "New password must contain at least 6 characters.",
                    "danger"
                )

                return redirect(url_for("profile"))

            # ------------------------------------------------
            # GET OLD PASSWORD
            # ------------------------------------------------

            cursor.execute("""
                SELECT password
                FROM users
                WHERE user_id = %s
            """, (user_id,))

            password_data = cursor.fetchone()

            if not password_data:

                flash(
                    "User account not found.",
                    "danger"
                )

                return redirect(url_for("login"))

            stored_password = password_data["password"]

            # ------------------------------------------------
            # CHECK CURRENT PASSWORD
            # ------------------------------------------------

            try:

                password_valid = check_password_hash(
                    stored_password,
                    current_password
                )

            except (ValueError, TypeError):

                password_valid = False

            if not password_valid:

                flash(
                    "Current password is incorrect.",
                    "danger"
                )

                return redirect(url_for("profile"))

            # ------------------------------------------------
            # HASH NEW PASSWORD
            # ------------------------------------------------

            hashed_password = generate_password_hash(
                new_password
            )

            cursor.execute("""
                UPDATE users

                SET password = %s

                WHERE user_id = %s
            """, (
                hashed_password,
                user_id
            ))

            db.commit()

            flash(
                "Password updated successfully.",
                "success"
            )

            return redirect(url_for("profile"))

        # ====================================================
        # DELETE ACCOUNT
        # ====================================================

        if request.method == "POST" and request.form.get("delete_account"):

            # ------------------------------------------------
            # SOFT DELETE
            # ------------------------------------------------
            # We do NOT physically delete the user because
            # appointments and other records may depend on it.

            cursor.execute("""
                UPDATE users

                SET
                    is_active = FALSE,
                    is_deleted = TRUE

                WHERE user_id = %s
            """, (user_id,))

            db.commit()

            # Clear session
            session.clear()

            flash(
                "Your MindCare account has been deleted.",
                "success"
            )

            return redirect(url_for("login"))

        # ====================================================
        # GET COMPLETE PROFILE
        # ====================================================

        cursor.execute("""
            SELECT

                u.user_id,
                u.username,
                u.email,
                u.created_at,
                u.is_active,
                u.is_deleted,

                r.role,

                sd.class,
                sd.stream,

                cd.qualification,
                cd.specialization,
                cd.experience

            FROM users u

            INNER JOIN roles r
                ON u.role_id = r.role_id

            LEFT JOIN student_details sd
                ON u.user_id = sd.user_id

            LEFT JOIN counsellor_details cd
                ON u.user_id = cd.user_id

            WHERE u.user_id = %s

            LIMIT 1
        """, (user_id,))

        user = cursor.fetchone()

        if not user:

            flash(
                "User account not found.",
                "danger"
            )

            return redirect(url_for("login"))

        # ----------------------------------------------------
        # ROLE
        # ----------------------------------------------------

        role = str(
            user.get("role") or "STUDENT"
        ).upper()

        # ----------------------------------------------------
        # RENDER PROFILE
        # ----------------------------------------------------

        return render_template(
            "profile.html",
            user=user,
            role=role
        )
 
    except mysql.connector.Error as err:

        db.rollback()

        print(
            "PROFILE DATABASE ERROR:",
            err
        )

        flash(
            "Something went wrong while updating your profile.",
            "danger"
        )

        return redirect(url_for("profile"))

    finally:

        cursor.close()
        db.close()
# ===========================
# MINDCARE ASSESSMENT
# ===========================

@app.route("/assessment", methods=["GET", "POST"])
def assessment():

    # ---------------------------
    # LOGIN CHECK
    # ---------------------------
    if "user_id" not in session:
        return redirect(url_for("login"))

    # ---------------------------
    # STUDENT ONLY
    # ---------------------------
    if session.get("role") != "STUDENT":
        return redirect(url_for("dashboard_redirect"))

    # ---------------------------
    # QUESTIONS
    # ---------------------------
    questions = [
        {
            "id": 1,
            "question": "How often do you feel stressed because of your studies?"
        },
        {
            "id": 2,
            "question": "How often do you feel worried or nervous?"
        },
        {
            "id": 3,
            "question": "How often do you have difficulty sleeping or resting?"
        },
        {
            "id": 4,
            "question": "How often do you feel sad or lose interest in things you enjoy?"
        },
        {
            "id": 5,
            "question": "How often do you feel that your problems are difficult to manage?"
        }
    ]

    # ---------------------------
    # OPTIONS
    # ---------------------------
    options = [
        {
            "value": 0,
            "text": "Never"
        },
        {
            "value": 1,
            "text": "Sometimes"
        },
        {
            "value": 2,
            "text": "Often"
        },
        {
            "value": 3,
            "text": "Very Often"
        }
    ]

    # ===========================
    # POST - SUBMIT ASSESSMENT
    # ===========================

    if request.method == "POST":

        total_score = 0

        # Check every question
        for question in questions:

            answer = request.form.get(
                f"q{question['id']}"
            )

            # No answer
            if answer is None:

                flash(
                    "Please answer all questions.",
                    "warning"
                )

                return render_template(
                    "assessment.html",
                    questions=questions,
                    options=options
                )

            # Convert answer to integer
            try:
                answer = int(answer)

            except (ValueError, TypeError):

                flash(
                    "Invalid assessment response.",
                    "danger"
                )

                return render_template(
                    "assessment.html",
                    questions=questions,
                    options=options
                )

            # Validate answer
            if answer not in [0, 1, 2, 3]:

                flash(
                    "Invalid assessment response.",
                    "danger"
                )

                return render_template(
                    "assessment.html",
                    questions=questions,
                    options=options
                )

            total_score += answer

        # ===========================
        # RESULT / RISK LEVEL
        # ===========================

        if total_score <= 4:

            risk_level = "Healthy"

            recommendation = (
                "Your responses indicate that you are "
                "currently doing well. Continue taking "
                "care of your mental wellness."
            )

            support_required = False

        elif total_score <= 9:

            risk_level = "Needs Support"

            recommendation = (
                "Your responses indicate that you may "
                "be experiencing some emotional or "
                "mental health difficulties. Talking "
                "with a counsellor may be helpful."
            )

            support_required = True

        else:

            risk_level = "High Support Needed"

            recommendation = (
                "Your responses indicate that you may "
                "be experiencing significant emotional "
                "difficulties. We recommend speaking "
                "with a counsellor for additional support."
            )

            support_required = True

        # ===========================
        # SAVE ASSESSMENT
        # ===========================

        db = get_db_connection()
        cursor = db.cursor()

        try:

            cursor.execute(
                """
                INSERT INTO assessments
                (
                    user_id,
                    assessment_type,
                    score,
                    risk_level,
                    recommendation
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    session["user_id"],
                    "MindCare Quick Assessment",
                    total_score,
                    risk_level,
                    recommendation
                )
            )

            db.commit()

        except mysql.connector.Error as err:

            db.rollback()

            print("Assessment Database Error:", err)

            flash(
                "Unable to save assessment result.",
                "danger"
            )

            return render_template(
                "assessment.html",
                questions=questions,
                options=options
            )

        finally:

            cursor.close()
            db.close()
        # ===========================
        # SHOW RESULT
        # ===========================

        return render_template(
            "assessment_result.html",
            score=total_score,
            max_score=15,
            risk_level=risk_level,
            recommendation=recommendation,
            support_required=support_required
        )

    # ===========================
    # GET - SHOW QUESTIONS
    # ===========================

    return render_template(
        "assessment.html",
        questions=questions,
        options=options
    )
# ============================================================
# COUNSELLOR -> STUDENT CHAT
# ============================================================

@app.route("/counsellor/chat/<int:student_id>", methods=["GET", "POST"])
def counsellor_chat_student(student_id):

    # --------------------------------------------------------
    # LOGIN CHECK
    # --------------------------------------------------------

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("dashboard_redirect"))

    counsellor_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # GET STUDENT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                s.class,
                s.stream
            FROM users u

            INNER JOIN roles r
                ON u.role_id = r.role_id

            LEFT JOIN student_details s
                ON u.user_id = s.user_id

            WHERE u.user_id = %s
              AND r.role = 'STUDENT'
              AND u.is_active = TRUE
              AND u.is_deleted = FALSE

            LIMIT 1
        """, (student_id,))

        student = cursor.fetchone()

        if not student:

            flash("Student not found.", "danger")

            return redirect(
                url_for("counsellor_dashboard")
            )

        # ----------------------------------------------------
        # SEND MESSAGE
        # ----------------------------------------------------

        if request.method == "POST":

            message = request.form.get(
                "message",
                ""
            ).strip()

            if not message:

                flash(
                    "Please enter a message.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "counsellor_chat_student",
                        student_id=student_id
                    )
                )

            # -----------------------------------------------
            # SAVE COUNSELLOR MESSAGE
            # -----------------------------------------------

            cursor.execute("""
                INSERT INTO counsellor_chat
                (
                    student_id,
                    counsellor_id,
                    sender_role,
                    message
                )
                VALUES
                (
                    %s,
                    %s,
                    'COUNSELLOR',
                    %s
                )
            """, (
                student_id,
                counsellor_id,
                message
            ))

            db.commit()

            return redirect(
                url_for(
                    "counsellor_chat_student",
                    student_id=student_id
                )
            )

        # ----------------------------------------------------
        # CHAT HISTORY
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                chat_id,
                student_id,
                counsellor_id,
                sender_role,
                message,
                created_at
            FROM counsellor_chat
            WHERE student_id = %s
              AND counsellor_id = %s
            ORDER BY
                created_at ASC,
                chat_id ASC
        """, (
            student_id,
            counsellor_id
        ))

        messages = cursor.fetchall()

        # ----------------------------------------------------
        # STUDENT LATEST ASSESSMENT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                assessment_id,
                assessment_type,
                score,
                risk_level,
                recommendation,
                created_at
            FROM assessments
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (student_id,))

        assessment = cursor.fetchone()

        # ----------------------------------------------------
        # COUNSELLOR DETAILS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                c.qualification,
                c.specialization,
                c.experience
            FROM users u

            INNER JOIN roles r
                ON u.role_id = r.role_id

            LEFT JOIN counsellor_details c
                ON u.user_id = c.user_id

            WHERE u.user_id = %s
              AND r.role = 'COUNSELLOR'
              AND u.is_active = TRUE
              AND u.is_deleted = FALSE

            LIMIT 1
        """, (counsellor_id,))

        counsellor = cursor.fetchone()

        # ----------------------------------------------------
        # OPEN CHAT PAGE
        # ----------------------------------------------------

        return render_template(
            "counsellor_chat.html",
            student=student,
            counsellor=counsellor,
            messages=messages,
            role="COUNSELLOR",
            assessment=assessment
        )

    except mysql.connector.Error as err:

        db.rollback()

        print(
            "Counsellor Student Chat Error:",
            err
        )

        flash(
            "Unable to load chat.",
            "danger"
        )

        return redirect(
            url_for("counsellor_dashboard")
        )

    finally:

        cursor.close()
        db.close()
# ============================================================
# STUDENT -> COUNSELLOR CHAT
# ============================================================

@app.route("/student/chat/<int:counsellor_id>", methods=["GET", "POST"])
def student_counsellor_chat(counsellor_id):

    # --------------------------------------------------------
    # LOGIN CHECK
    # --------------------------------------------------------

    if "user_id" not in session:
        return redirect(url_for("login"))

    # --------------------------------------------------------
    # STUDENT ONLY
    # --------------------------------------------------------

    if session.get("role") != "STUDENT":
        return redirect(url_for("dashboard_redirect"))

    student_id = session["user_id"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # GET COUNSELLOR
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                c.qualification,
                c.specialization,
                c.experience
            FROM users u

            INNER JOIN roles r
                ON u.role_id = r.role_id

            LEFT JOIN counsellor_details c
                ON u.user_id = c.user_id

            WHERE u.user_id = %s
              AND r.role = 'COUNSELLOR'
              AND u.is_active = TRUE
              AND u.is_deleted = FALSE

            LIMIT 1
        """, (counsellor_id,))

        counsellor = cursor.fetchone()

        if not counsellor:

            flash(
                "Counsellor not found.",
                "danger"
            )

            return redirect(
                url_for("counsellors")
            )

        # ----------------------------------------------------
        # SEND STUDENT MESSAGE
        # ----------------------------------------------------

        if request.method == "POST":

            message = request.form.get(
                "message",
                ""
            ).strip()

            if not message:

                flash(
                    "Please enter a message.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "student_counsellor_chat",
                        counsellor_id=counsellor_id
                    )
                )

            cursor.execute("""
                INSERT INTO counsellor_chat
                (
                    student_id,
                    counsellor_id,
                    sender_role,
                    message
                )
                VALUES
                (
                    %s,
                    %s,
                    'STUDENT',
                    %s
                )
            """, (
                student_id,
                counsellor_id,
                message
            ))

            db.commit()

            return redirect(
                url_for(
                    "student_counsellor_chat",
                    counsellor_id=counsellor_id
                )
            )

        # ----------------------------------------------------
        # CHAT HISTORY
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                chat_id,
                sender_role,
                message,
                created_at
            FROM counsellor_chat
            WHERE student_id = %s
              AND counsellor_id = %s
            ORDER BY
                created_at ASC,
                chat_id ASC
        """, (
            student_id,
            counsellor_id
        ))

        messages = cursor.fetchall()

        # ----------------------------------------------------
        # STUDENT DETAILS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                u.user_id,
                u.username,
                u.email,
                s.class,
                s.stream
            FROM users u

            LEFT JOIN student_details s
                ON u.user_id = s.user_id

            WHERE u.user_id = %s

            LIMIT 1
        """, (student_id,))

        student = cursor.fetchone()

        # ----------------------------------------------------
        # STUDENT LATEST ASSESSMENT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                assessment_id,
                assessment_type,
                score,
                risk_level,
                recommendation,
                created_at
            FROM assessments
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (student_id,))

        assessment = cursor.fetchone()

        # ----------------------------------------------------
        # OPEN CHAT
        # ----------------------------------------------------

        return render_template(
            "counsellor_chat.html",
            student=student,
            counsellor=counsellor,
            messages=messages,
            role="STUDENT",
            assessment=assessment
        )

    except mysql.connector.Error as err:

        db.rollback()

        print(
            "Student Counsellor Chat Error:",
            err
        )

        flash(
            "Unable to load chat.",
            "danger"
        )

        return redirect(
            url_for("counsellors")
        )

    finally:

        cursor.close()
        db.close()
@app.route("/complete-counselling/<int:student_id>/<int:counsellor_id>", methods=["POST"])
def complete_counselling(student_id, counsellor_id):

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE counsellor_chat
        SET chat_status = 'Completed'
        WHERE student_id = %s
        AND counsellor_id = %s
    """, (student_id, counsellor_id))

    db.commit()

    cursor.close()
    db.close()

    if session["role"] == "STUDENT":
        return redirect(url_for("student_dashboard"))
    else:
        return redirect(url_for("counsellor_dashboard"))
# ===========================
# LOGOUT
# ===========================

@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully.")

    return redirect(
        url_for("home")
    )


# ===========================
# RUN APPLICATION
# ===========================

if __name__ == "__main__":

    app.run(
        debug=True
    )
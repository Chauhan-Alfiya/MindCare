from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
import os
import json
import traceback

from dotenv import load_dotenv
from groq import Groq

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()


# Create Flask application
app = Flask(__name__)


# Groq API Client
client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


# Resource upload folder
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
        return redirect(url_for("dashboard_redirect"))

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        user_id = session["user_id"]

        # Find existing ACTIVE session
        cursor.execute("""
            SELECT session_id
            FROM chat_sessions
            WHERE user_id = %s
            AND status = 'Active'
            ORDER BY session_id DESC
            LIMIT 1
        """, (user_id,))

        active_chat = cursor.fetchone()

        # Create only if no active session exists
        if active_chat:
            chat_session_id = active_chat["session_id"]

        else:
            cursor.execute("""
                INSERT INTO chat_sessions (user_id)
                VALUES (%s)
            """, (user_id,))

            chat_session_id = cursor.lastrowid
            db.commit()

        # Load previous messages from SAME session
        cursor.execute("""
            SELECT message, bot_reply, created_at
            FROM chat_support
            WHERE user_id = %s
            AND session_id = %s
            ORDER BY chat_id ASC
            LIMIT 30
        """, (user_id, chat_session_id))

        chat_history = cursor.fetchall()

        return render_template(
            "chatbot.html",
            chat_history=chat_history
        )

    except Exception as err:

        if db:
            db.rollback()

        print("Chat Error:", repr(err))

        return "Unable to load chat."

    finally:
        if cursor:
            cursor.close()

        if db:
            db.close()


@app.route("/chatbot/send", methods=["POST"])
def chatbot_send():

    if "user_id" not in session:
        return jsonify({"error": "Please login first."}), 401

    if session.get("role") != "STUDENT":
        return jsonify({"error": "Access denied."}), 403

    user_id = session["user_id"]

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({"error": "Please enter a message."}), 400

    if len(message) > 2000:
        return jsonify({"error": "Message is too long."}), 400

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return jsonify({
            "error": "Groq API key is missing."
        }), 500

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # 1. GET ACTIVE CHAT SESSION
        cursor.execute("""
            SELECT session_id
            FROM chat_sessions
            WHERE user_id = %s
            AND status = 'Active'
            ORDER BY session_id DESC
            LIMIT 1
        """, (user_id,))

        active_chat = cursor.fetchone()

        if not active_chat:

            cursor.execute("""
                INSERT INTO chat_sessions (user_id)
                VALUES (%s)
            """, (user_id,))

            chat_session_id = cursor.lastrowid
            db.commit()

        else:
            chat_session_id = active_chat["session_id"]

        # 2. GET SAME SESSION HISTORY
        cursor.execute("""
            SELECT message, bot_reply
            FROM chat_support
            WHERE user_id = %s
            AND session_id = %s
            ORDER BY chat_id DESC
            LIMIT 8
        """, (user_id, chat_session_id))

        history = cursor.fetchall()
        history.reverse()

        # 3. SYSTEM INSTRUCTIONS
        conversation = [
            {
                "role": "system",
                "content": """
You are MindCare AI Assistant for high-school students.

Be kind, friendly and supportive.
Use simple and easy English.

Help students with:
- Study stress
- Anxiety
- Sadness
- Sleep problems
- Daily challenges
- School pressure

Give practical, safe and supportive suggestions.

Do not diagnose medical conditions.
Do not prescribe medicines.
Do not claim to be a doctor or human counsellor.

If a student mentions suicide, self-harm or immediate danger,
encourage them to immediately contact a trusted adult,
parent, teacher, school counsellor or local emergency services.

Keep replies reasonably short and supportive.
"""
            }
        ]

        # 4. ADD OLD MESSAGES
        for chat in history:

            conversation.append({
                "role": "user",
                "content": chat["message"]
            })

            conversation.append({
                "role": "assistant",
                "content": chat["bot_reply"] or ""
            })

        # 5. ADD CURRENT MESSAGE
        conversation.append({
            "role": "user",
            "content": message
        })

        # 6. GROQ RESPONSE
        response = client.chat.completions.create(

            model=os.getenv(
                "GROQ_MODEL",
                "llama-3.3-70b-versatile"
            ),

            messages=conversation,
            temperature=0.7,
            max_completion_tokens=500
        )

        bot_reply = response.choices[0].message.content

        if not bot_reply or not bot_reply.strip():
            raise ValueError("AI returned an empty response.")

        bot_reply = bot_reply.strip()

        # 7. SAVE MESSAGE IN CURRENT SESSION
        cursor.execute("""
            INSERT INTO chat_support
            (user_id, session_id, message, bot_reply)
            VALUES (%s, %s, %s, %s)
        """, (
            user_id,
            chat_session_id,
            message,
            bot_reply
        ))

        db.commit()

        return jsonify({
            "reply": bot_reply
        })

    except Exception as err:

        if db:
            db.rollback()

        print("GROQ CHAT ERROR:", repr(err))
        traceback.print_exc()

        return jsonify({
            "error": "Unable to generate a reply right now. Please try again."
        }), 500

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

@app.route("/chatbot/complete", methods=["POST"])
def complete_chat():

    if "user_id" not in session:
        return jsonify({
            "error": "Please login first."
        }), 401

    if session.get("role") != "STUDENT":
        return jsonify({
            "error": "Access denied."
        }), 403

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        user_id = session["user_id"]

        # Find current active chat
        cursor.execute("""
            SELECT session_id
            FROM chat_sessions
            WHERE user_id = %s
            AND status = 'Active'
            ORDER BY session_id DESC
            LIMIT 1
            FOR UPDATE
        """, (user_id,))

        active_chat = cursor.fetchone()

        if not active_chat:
            return jsonify({
                "error": "No active chat found."
            }), 404

        old_session_id = active_chat["session_id"]

        # Complete current chat
        cursor.execute("""
            UPDATE chat_sessions
            SET status = 'Completed',
                completed_at = NOW()
            WHERE session_id = %s
            AND user_id = %s
        """, (old_session_id, user_id))

        # Create new chat session
        cursor.execute("""
            INSERT INTO chat_sessions (user_id)
            VALUES (%s)
        """, (user_id,))

        new_session_id = cursor.lastrowid

        db.commit()

        print("CHAT COMPLETED:", old_session_id)
        print("NEW CHAT CREATED:", new_session_id)

        return jsonify({
            "success": True,
            "message": "Your previous chat is completed. New chat started!",
            "new_session_id": new_session_id
        })

    except Exception as err:

        if db:
            db.rollback()

        print("Complete Chat Error:", repr(err))

        return jsonify({
            "error": "Unable to complete chat right now."
        }), 500

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

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
    # LOGIN CHECK
    if "user_id" not in session:
        return redirect(url_for("login"))
    # STUDENT ONLY
    if session.get("role") != "STUDENT":
        return redirect(url_for("login"))
    student_id = session["user_id"]
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # POST - BOOK APPOINTMENT
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
            # REQUIRED FIELDS
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
            # CHECK COUNSELLOR
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
            # CHECK DATE
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
            
            # CHECK COUNSELLOR SLOT
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
            # CHECK STUDENT SLOT
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
            # INSERT APPOINTMENT
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
                AND u.is_active = TRUE
                AND u.is_deleted = FALSE 
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

# ============================================================
# STUDENT - SEND CHAT REQUEST
# ============================================================

@app.route("/student/chat/request/<int:counsellor_id>", methods=["POST"])
def send_chat_request(counsellor_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "STUDENT":
        return redirect(url_for("dashboard_redirect"))

    student_id = session["user_id"]
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Check counsellor availability
        cursor.execute("""
            SELECT u.user_id, u.username
            FROM users u
            INNER JOIN roles r ON u.role_id = r.role_id
            WHERE u.user_id = %s
              AND r.role = 'COUNSELLOR'
              AND u.is_active = TRUE
              AND u.is_deleted = FALSE
            LIMIT 1
        """, (counsellor_id,))

        counsellor = cursor.fetchone()

        if not counsellor:
            flash("Counsellor is not available.", "danger")
            return redirect(url_for("counsellors"))

        # Check existing pending or accepted request
        cursor.execute("""
            SELECT request_id, status
            FROM chat_requests
            WHERE student_id = %s
              AND counsellor_id = %s
              AND status IN ('Pending', 'Accepted')
            ORDER BY request_id DESC
            LIMIT 1
        """, (student_id, counsellor_id))

        existing_request = cursor.fetchone()

        if existing_request:

            if existing_request["status"] == "Pending":
                flash(
                    "Your chat request is already pending. Please wait for the counsellor.",
                    "warning"
                )
                return redirect(url_for("counsellors"))

            if existing_request["status"] == "Accepted":
                return redirect(url_for(
                    "counsellor_chat",
                    request_id=existing_request["request_id"]
                ))

        # Create a new request
        cursor.execute("""
            INSERT INTO chat_requests
            (student_id, counsellor_id, status)
            VALUES (%s, %s, 'Pending')
        """, (student_id, counsellor_id))

        db.commit()

        flash(
            "Chat request sent successfully. Please wait for the counsellor to accept it.",
            "success"
        )

        return redirect(url_for("counsellors"))

    except mysql.connector.Error as err:
        if db:
            db.rollback()

        print("Send Chat Request Error:", err)
        flash("Unable to send chat request.", "danger")
        return redirect(url_for("counsellors"))

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


# ============================================================
# COUNSELLOR - CHAT REQUESTS PAGE
# ============================================================

@app.route("/counsellor/chat/requests")
def counsellor_chat_requests():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("dashboard_redirect"))

    counsellor_id = session["user_id"]
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Get pending requests
        cursor.execute("""
            SELECT
                cr.request_id,
                cr.status,
                cr.requested_at,
                u.user_id AS student_id,
                u.username,
                u.email,
                sd.class,
                sd.stream
            FROM chat_requests cr
            INNER JOIN users u
                ON cr.student_id = u.user_id
            LEFT JOIN student_details sd
                ON u.user_id = sd.user_id
            WHERE cr.counsellor_id = %s
              AND cr.status = 'Pending'
            ORDER BY cr.requested_at DESC
        """, (counsellor_id,))

        requests = cursor.fetchall()

        # Get accepted chats
        cursor.execute("""
            SELECT
                cr.request_id,
                cr.status,
                cr.requested_at,
                u.user_id AS student_id,
                u.username,
                u.email,
                sd.class,
                sd.stream,

                (
                    SELECT cc.message
                    FROM counsellor_chat cc
                    WHERE cc.request_id = cr.request_id
                    ORDER BY cc.chat_id DESC
                    LIMIT 1
                ) AS last_message,

                (
                    SELECT cc.created_at
                    FROM counsellor_chat cc
                    WHERE cc.request_id = cr.request_id
                    ORDER BY cc.chat_id DESC
                    LIMIT 1
                ) AS last_message_time

            FROM chat_requests cr
            INNER JOIN users u
                ON cr.student_id = u.user_id
            LEFT JOIN student_details sd
                ON u.user_id = sd.user_id
            WHERE cr.counsellor_id = %s
              AND cr.status = 'Accepted'
            ORDER BY
                COALESCE(last_message_time, cr.requested_at) DESC
        """, (counsellor_id,))

        active_chats = cursor.fetchall()

        return render_template(
            "chat_requests.html",
            requests=requests,
            active_chats=active_chats
        )

    except mysql.connector.Error as err:
        print("Chat Requests Error:", err)
        flash("Unable to load chat requests.", "danger")
        return redirect(url_for("counsellor_dashboard"))

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


# ============================================================
# COUNSELLOR - ACCEPT CHAT REQUEST
# ============================================================

@app.route("/counsellor/chat/accept/<int:request_id>", methods=["POST"])
def accept_chat_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("dashboard_redirect"))

    counsellor_id = session["user_id"]
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("""
            UPDATE chat_requests
            SET
                status = 'Accepted',
                responded_at = NOW()
            WHERE request_id = %s
              AND counsellor_id = %s
              AND status = 'Pending'
        """, (request_id, counsellor_id))

        if cursor.rowcount == 0:
            db.rollback()
            flash(
                "Chat request not found or already processed.",
                "warning"
            )
            return redirect(url_for("counsellor_chat_requests"))

        db.commit()

        flash("Chat request accepted. You can now start chatting.", "success")

        return redirect(url_for(
            "counsellor_chat",
            request_id=request_id
        ))

    except mysql.connector.Error as err:
        if db:
            db.rollback()

        print("Accept Chat Request Error:", err)
        flash("Unable to accept chat request.", "danger")
        return redirect(url_for("counsellor_chat_requests"))

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()


# ============================================================
# COUNSELLOR - DECLINE CHAT REQUEST
# ============================================================

@app.route("/counsellor/chat/reject/<int:request_id>", methods=["POST"])
def reject_chat_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("dashboard_redirect"))

    counsellor_id = session["user_id"]
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("""
            UPDATE chat_requests
            SET
                status = 'Declined',
                responded_at = NOW()
            WHERE request_id = %s
              AND counsellor_id = %s
              AND status = 'Pending'
        """, (request_id, counsellor_id))

        if cursor.rowcount == 0:
            db.rollback()
            flash(
                "Chat request not found or already processed.",
                "warning"
            )
            return redirect(url_for("counsellor_chat_requests"))

        db.commit()
        flash("Chat request declined.", "info")

    except mysql.connector.Error as err:
        if db:
            db.rollback()

        print("Decline Chat Request Error:", err)
        flash("Unable to decline chat request.", "danger")

    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

    return redirect(url_for("counsellor_chat_requests"))

# ============================================================
# STUDENT + COUNSELLOR - OPEN CHAT
# ============================================================

@app.route(
    "/counsellor/chat/<int:request_id>",
    methods=["GET", "POST"]
)
def counsellor_chat(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    role = session.get("role")

    if role not in ["STUDENT", "COUNSELLOR"]:
        return redirect(url_for("dashboard_redirect"))

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Check chat request and user ownership
        cursor.execute("""
            SELECT
                cr.request_id,
                cr.student_id,
                cr.counsellor_id,
                cr.status,

                su.username AS student_name,
                su.email AS student_email,

                cu.username AS counsellor_name,
                cu.email AS counsellor_email,

                sd.class,
                sd.stream,

                cd.qualification,
                cd.specialization

            FROM chat_requests cr

            INNER JOIN users su
                ON cr.student_id = su.user_id

            INNER JOIN users cu
                ON cr.counsellor_id = cu.user_id

            LEFT JOIN student_details sd
                ON su.user_id = sd.user_id

            LEFT JOIN counsellor_details cd
                ON cu.user_id = cd.user_id

            WHERE cr.request_id = %s
              AND (
                    (cr.student_id = %s AND %s = 'STUDENT')
                    OR
                    (cr.counsellor_id = %s AND %s = 'COUNSELLOR')
              )

            LIMIT 1
        """, (
            request_id,
            user_id,
            role,
            user_id,
            role
        ))

        chat_request = cursor.fetchone()

        if not chat_request:

            flash(
                "Chat not found or access denied.",
                "danger"
            )

            return redirect(url_for("dashboard_redirect"))

        # Only Accepted and Completed chats can be opened
        if chat_request["status"] not in ["Accepted", "Completed"]:

            if role == "STUDENT":

                flash(
                    "Please wait for the counsellor to accept your chat request.",
                    "warning"
                )

                return redirect(url_for("counsellors"))

            flash(
                "This chat is not active.",
                "warning"
            )

            return redirect(
                url_for("counsellor_chat_requests")
            )

        # Do not allow normal POST messages after completion
        if request.method == "POST":

            if chat_request["status"] != "Accepted":

                flash(
                    "This counselling session has been completed.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "counsellor_chat",
                        request_id=request_id
                    )
                )

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
                        "counsellor_chat",
                        request_id=request_id
                    )
                )

            if len(message) > 2000:

                flash(
                    "Message is too long.",
                    "warning"
                )

                return redirect(
                    url_for(
                        "counsellor_chat",
                        request_id=request_id
                    )
                )

            cursor.execute("""
                INSERT INTO counsellor_chat
                (
                    request_id,
                    student_id,
                    counsellor_id,
                    sender_role,
                    message
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                request_id,
                chat_request["student_id"],
                chat_request["counsellor_id"],
                role,
                message
            ))

            db.commit()

            return redirect(
                url_for(
                    "counsellor_chat",
                    request_id=request_id
                )
            )

        # Fetch previous messages
        cursor.execute("""
            SELECT
                chat_id,
                request_id,
                student_id,
                counsellor_id,
                sender_role,
                message,
                created_at

            FROM counsellor_chat

            WHERE request_id = %s

            ORDER BY chat_id ASC
        """, (request_id,))

        messages = cursor.fetchall()

        # Prepare student information
        student = {
            "user_id": chat_request["student_id"],
            "username": chat_request["student_name"],
            "email": chat_request["student_email"],
            "class": chat_request["class"],
            "stream": chat_request["stream"]
        }

        # Prepare counsellor information
        counsellor = {
            "user_id": chat_request["counsellor_id"],
            "username": chat_request["counsellor_name"],
            "email": chat_request["counsellor_email"],
            "qualification": chat_request["qualification"],
            "specialization": chat_request["specialization"]
        }

        return render_template(
            "counsellor_chat.html",
            chat_status=chat_request["status"],
            student=student,
            counsellor=counsellor,
            messages=messages,
            role=role,
            request_id=request_id
        )

    except mysql.connector.Error as err:

        if db:
            db.rollback()

        print("Counsellor Chat Error:", err)

        flash(
            "Unable to load chat.",
            "danger"
        )

        return redirect(url_for("dashboard_redirect"))

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ============================================================
# STUDENT + COUNSELLOR - AJAX SEND MESSAGE
# ============================================================

@app.route(
    "/counsellor/chat/<int:request_id>/send",
    methods=["POST"]
)
def send_counsellor_chat_message(request_id):

    if "user_id" not in session:

        return jsonify({
            "success": False,
            "error": "Login required"
        }), 401

    user_id = session["user_id"]
    role = session.get("role")

    if role not in ["STUDENT", "COUNSELLOR"]:

        return jsonify({
            "success": False,
            "error": "Access denied"
        }), 403

    data = request.get_json(silent=True) or {}

    message = str(
        data.get("message", "")
    ).strip()

    if not message:

        return jsonify({
            "success": False,
            "error": "Message cannot be empty"
        }), 400

    if len(message) > 2000:

        return jsonify({
            "success": False,
            "error": "Message is too long"
        }), 400

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Only Accepted chats can send messages
        cursor.execute("""
            SELECT
                request_id,
                student_id,
                counsellor_id

            FROM chat_requests

            WHERE request_id = %s
              AND status = 'Accepted'
              AND (
                    (student_id = %s AND %s = 'STUDENT')
                    OR
                    (counsellor_id = %s AND %s = 'COUNSELLOR')
              )

            LIMIT 1
        """, (
            request_id,
            user_id,
            role,
            user_id,
            role
        ))

        chat_request = cursor.fetchone()

        if not chat_request:

            return jsonify({
                "success": False,
                "error": "This counselling session has been completed or is not active."
            }), 403

        # Save message
        cursor.execute("""
            INSERT INTO counsellor_chat
            (
                request_id,
                student_id,
                counsellor_id,
                sender_role,
                message
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            request_id,
            chat_request["student_id"],
            chat_request["counsellor_id"],
            role,
            message
        ))

        chat_id = cursor.lastrowid

        db.commit()

        # Get saved message
        cursor.execute("""
            SELECT
                chat_id,
                sender_role,
                message,
                created_at

            FROM counsellor_chat

            WHERE chat_id = %s
        """, (chat_id,))

        saved_message = cursor.fetchone()

        return jsonify({
            "success": True,
            "message": {
                "chat_id": saved_message["chat_id"],
                "sender_role": saved_message["sender_role"],
                "message": saved_message["message"],
                "created_at": saved_message["created_at"].strftime(
                    "%d %b %Y, %I:%M %p"
                )
            }
        })

    except mysql.connector.Error as err:

        if db:
            db.rollback()

        print(
            "AJAX Send Message Error:",
            err
        )

        return jsonify({
            "success": False,
            "error": "Unable to send message"
        }), 500

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ============================================================
# STUDENT + COUNSELLOR - AJAX FETCH NEW MESSAGES
# ============================================================

@app.route(
    "/counsellor/chat/<int:request_id>/messages",
    methods=["GET"]
)
def get_counsellor_chat_messages(request_id):

    if "user_id" not in session:

        return jsonify({
            "success": False,
            "error": "Login required"
        }), 401

    user_id = session["user_id"]
    role = session.get("role")

    if role not in ["STUDENT", "COUNSELLOR"]:

        return jsonify({
            "success": False,
            "error": "Access denied"
        }), 403

    last_id = request.args.get(
        "last_id",
        0,
        type=int
    )

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Check ownership but allow Accepted AND Completed status
        cursor.execute("""
            SELECT
                request_id,
                status

            FROM chat_requests

            WHERE request_id = %s
              AND (
                    (student_id = %s AND %s = 'STUDENT')
                    OR
                    (counsellor_id = %s AND %s = 'COUNSELLOR')
              )

            LIMIT 1
        """, (
            request_id,
            user_id,
            role,
            user_id,
            role
        ))

        chat_request = cursor.fetchone()

        if not chat_request:

            return jsonify({
                "success": False,
                "error": "Chat not found or access denied"
            }), 403

        # Fetch messages created after last_id
        cursor.execute("""
            SELECT
                chat_id,
                sender_role,
                message,
                created_at

            FROM counsellor_chat

            WHERE request_id = %s
              AND chat_id > %s

            ORDER BY chat_id ASC
        """, (
            request_id,
            last_id
        ))

        rows = cursor.fetchall()

        messages = []

        for msg in rows:

            messages.append({
                "chat_id": msg["chat_id"],
                "sender_role": msg["sender_role"],
                "message": msg["message"],
                "created_at": msg["created_at"].strftime(
                    "%d %b %Y, %I:%M %p"
                )
            })

        return jsonify({
            "success": True,
            "status": chat_request["status"],
            "active": chat_request["status"] == "Accepted",
            "messages": messages
        })

    except mysql.connector.Error as err:

        print(
            "AJAX Fetch Messages Error:",
            err
        )

        return jsonify({
            "success": False,
            "error": "Unable to fetch messages"
        }), 500

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()


# ============================================================
# COUNSELLOR - COMPLETE COUNSELLING
# ============================================================

@app.route(
    "/counsellor/chat/complete/<int:request_id>",
    methods=["POST"]
)
def complete_counselling(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "COUNSELLOR":
        return redirect(url_for("dashboard_redirect"))

    counsellor_id = session["user_id"]

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        # Change chat status to Completed
        cursor.execute("""
            UPDATE chat_requests

            SET
                status = 'Completed',
                responded_at = NOW()

            WHERE request_id = %s
              AND counsellor_id = %s
              AND status = 'Accepted'
        """, (
            request_id,
            counsellor_id
        ))

        if cursor.rowcount == 0:

            db.rollback()

            flash(
                "Chat not found or already completed.",
                "warning"
            )

            return redirect(
                url_for("counsellor_chat_requests")
            )

        db.commit()

        flash(
            "Counselling session completed successfully.",
            "success"
        )

    except mysql.connector.Error as err:

        if db:
            db.rollback()

        print(
            "Complete Counselling Error:",
            err
        )

        flash(
            "Unable to complete counselling.",
            "danger"
        )

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

    return redirect(
        url_for("counsellor_chat_requests")
    )

# ============================================================
# AI DYNAMIC WELLNESS ASSESSMENT - START
# ============================================================

@app.route("/ai_assessment")
def ai_assessment():

    # Login check
    if "user_id" not in session:
        return redirect(url_for("login"))

    # Student check
    if session.get("role") != "STUDENT":
        return redirect(url_for("dashboard"))

    # Start fresh assessment
    session["ai_assessment_history"] = []
    session["ai_assessment_turns"] = 0

    try:

        response = client.chat.completions.create(

            model=os.getenv(
                "GROQ_MODEL",
                "openai/gpt-oss-120b"
            ),

            messages=[
                {
                    "role": "system",
                    "content": """
You are MindCare AI, a friendly wellness assessment assistant
for high-school students.

Generate ONE friendly opening question about how the student
has been feeling recently.

Rules:
- Ask only one question.
- Use simple, supportive English.
- Do not diagnose any condition.
- Do not prescribe medicine.
- Do not give an assessment result yet.

Return only the question, without JSON or markdown.
"""
                }
            ],

            temperature=0.7,
            max_completion_tokens=120
        )

        first_question = (
            response.choices[0].message.content or ""
        ).strip()

        if not first_question:
            raise ValueError("AI returned an empty opening question.")

    except Exception as err:

        print("AI Assessment Start Error:", repr(err))

        first_question = (
            "Hello! 💙 How have you been feeling recently?"
        )

    # Save first AI question
    session["ai_assessment_history"] = [
        {
            "role": "assistant",
            "content": first_question
        }
    ]

    session["ai_assessment_turns"] = 0
    session.modified = True

    return render_template(
        "ai_assessment.html",
        history=session["ai_assessment_history"],
        completed=False
    )


# ============================================================
# AI DYNAMIC ASSESSMENT - SEND ANSWER
# EXACTLY 5 STUDENT ANSWERS
# ============================================================

@app.route("/ai_assessment/send", methods=["POST"])
def ai_assessment_send():

    # --------------------------------------------------------
    # LOGIN CHECK
    # --------------------------------------------------------

    if "user_id" not in session:

        return jsonify({
            "error": "Please login first."
        }), 401

    # --------------------------------------------------------
    # STUDENT CHECK
    # --------------------------------------------------------

    if session.get("role") != "STUDENT":

        return jsonify({
            "error": "Access denied."
        }), 403

    # --------------------------------------------------------
    # GET STUDENT ANSWER
    # --------------------------------------------------------

    data = request.get_json(silent=True) or {}

    answer = str(
        data.get("message", "")
    ).strip()

    if not answer:

        return jsonify({
            "error": "Please enter your answer."
        }), 400

    if len(answer) > 2000:

        return jsonify({
            "error": "Your answer must be within 2000 characters."
        }), 400

    # --------------------------------------------------------
    # GET SESSION HISTORY
    # --------------------------------------------------------

    history = session.get(
        "ai_assessment_history",
        []
    )

    turns = session.get(
        "ai_assessment_turns",
        0
    )

    if not isinstance(history, list) or not history:

        return jsonify({
            "error": "Your assessment session has expired. Please start again."
        }), 400

    # Prevent more than 5 answers
    if turns >= 5:

        return jsonify({
            "error": "This assessment has already reached its answer limit."
        }), 400

    # Add student answer
    history.append({
        "role": "user",
        "content": answer
    })

    turns += 1

    # --------------------------------------------------------
    # BUILD CONVERSATION
    # --------------------------------------------------------

    conversation = ""

    for item in history:

        if item.get("role") == "assistant":

            conversation += (
                "AI QUESTION: "
                + str(item.get("content", ""))
                + "\n"
            )

        elif item.get("role") == "user":

            conversation += (
                "STUDENT ANSWER: "
                + str(item.get("content", ""))
                + "\n"
            )

    # --------------------------------------------------------
    # QUESTION OR FINAL RESULT
    # --------------------------------------------------------

    if turns < 5:

        instruction = """
The student has given fewer than 5 answers.

You MUST generate exactly ONE next question.

The question must be based on the student's previous answers.

Do not give the final assessment result yet.
Do not ask a question that has already been asked.
"""

    else:

        instruction = """
The student has now given EXACTLY 5 answers.

You MUST COMPLETE the assessment now.

Do NOT ask another question.
Do NOT return action ASK.
Analyse all five student answers and generate the final result.
"""

    # --------------------------------------------------------
    # AI PROMPT
    # --------------------------------------------------------

    prompt = f"""
You are MindCare AI Wellness Assessment Assistant for
high-school students.

You are conducting a dynamic wellness assessment.

COMPLETE CONVERSATION:

{conversation}

CURRENT INSTRUCTION:

{instruction}

IMPORTANT RULES:

1. Read the complete conversation carefully.

2. Generate questions dynamically from the student's answers.

3. Never repeat a previous question.

4. Ask only one question at a time.

5. Use simple, friendly English suitable for high-school students.

6. Do not diagnose any mental health condition.

7. Do not prescribe medicine.

8. Do not judge or blame the student.

9. Do not assume information the student has not shared.

10. If the student mentions study stress, anxiety, sadness,
sleep problems, family problems or other concerns, respond
sensitively to that specific concern.

11. If the student describes immediate danger or thoughts
of self-harm, treat this seriously and recommend urgent
support from a trusted adult and appropriate emergency help.

12. At the fifth student answer, you MUST return COMPLETE.
Never ask a sixth question.

RETURN ONLY VALID JSON.

--------------------------------------------------

WHEN ASKING A QUESTION:

{{
    "action": "ASK",
    "question": "One relevant question based on previous answers."
}}

--------------------------------------------------

WHEN COMPLETING THE ASSESSMENT:

{{
    "action": "COMPLETE",
    "risk_level": "Doing Well",
    "summary": "A short and supportive summary based on the student's answers.",
    "counsellor_recommended": false,
    "counsellor_message": "A supportive message about counsellor support.",
    "suggestions": [
        "Practical suggestion 1",
        "Practical suggestion 2",
        "Practical suggestion 3"
    ]
}}

--------------------------------------------------

ALLOWED RISK LEVELS:

- Doing Well
- Support Recommended
- Urgent Support

COUNSELLOR GUIDELINES:

- Doing Well: Counsellor support is generally optional.
- Support Recommended: Recommend talking to a counsellor.
- Urgent Support: Recommend immediate support from a trusted adult
  and appropriate emergency services.

Return JSON only.

Do not use markdown.
Do not use code fences.
"""

    # --------------------------------------------------------
    # CALL GROQ AI
    # --------------------------------------------------------

    try:

        response = client.chat.completions.create(

            model=os.getenv(
                "GROQ_MODEL",
                "llama-3.3-70b-versatile"
            ),

            messages=[
                {
                    "role": "system",
                    "content": """
You are a safe and supportive student wellness assistant.

Follow the current instruction exactly.

Generate dynamic questions before the fifth answer.
After the fifth answer, always complete the assessment.

Return valid JSON only.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.5,
            max_completion_tokens=700
        )

        ai_response = (
            response.choices[0].message.content or ""
        ).strip()

        # Handle accidental markdown code fences
        if ai_response.startswith("```"):

            ai_response = ai_response.replace(
                "```json", ""
            ).replace(
                "```", ""
            ).strip()

        ai_data = json.loads(ai_response)

        if not isinstance(ai_data, dict):
            raise ValueError("AI returned an invalid JSON object.")

    except Exception as err:

        print("AI Assessment Error:", repr(err))

        return jsonify({
            "error": "AI assessment could not continue. Please try again."
        }), 500

    # --------------------------------------------------------
    # GET AI ACTION
    # --------------------------------------------------------

    action = str(
        ai_data.get("action", "")
    ).strip().upper()

    # --------------------------------------------------------
    # BEFORE 5 ANSWERS: ASK NEXT QUESTION
    # --------------------------------------------------------

    if turns < 5:

        if action != "ASK":

            return jsonify({
                "error": "AI could not generate the next question. Please try again."
            }), 500

        next_question = str(
            ai_data.get("question", "")
        ).strip()

        if not next_question:

            return jsonify({
                "error": "AI returned an empty question. Please try again."
            }), 500

        # Save AI question
        history.append({
            "role": "assistant",
            "content": next_question
        })

        session["ai_assessment_history"] = history
        session["ai_assessment_turns"] = turns
        session.modified = True

        return jsonify({
            "completed": False,
            "reply": next_question,
            "turns": turns
        })

    # --------------------------------------------------------
    # FIFTH ANSWER: FORCE FINAL RESULT
    # NEVER ASK A SIXTH QUESTION
    # --------------------------------------------------------

    if turns == 5 and action != "COMPLETE":

        print(
            "AI did not return COMPLETE after 5 answers. "
            "Using safe fallback result."
        )

        ai_data = {
            "action": "COMPLETE",
            "risk_level": "Support Recommended",
            "summary": (
                "Thank you for sharing your feelings with MindCare. "
                "It may be helpful to talk with someone you trust "
                "about how you have been feeling."
            ),
            "counsellor_recommended": True,
            "counsellor_message": (
                "Talking with a school counsellor may help you "
                "understand your feelings and find support."
            ),
            "suggestions": [
                "Talk to a trusted parent, teacher or friend.",
                "Take short breaks and make time for activities you enjoy.",
                "Try to maintain a healthy sleep routine."
            ]
        }

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    risk_level = str(
        ai_data.get("risk_level", "Support Recommended")
    ).strip()

    summary = str(
        ai_data.get(
            "summary",
            "Thank you for sharing how you have been feeling."
        )
    ).strip()

    counsellor_recommended = (
        ai_data.get("counsellor_recommended") is True
    )

    counsellor_message = str(
        ai_data.get("counsellor_message", "")
    ).strip()

    suggestions = ai_data.get("suggestions", [])

    # --------------------------------------------------------
    # VALIDATE RESULT
    # --------------------------------------------------------

    valid_risk_levels = [
        "Doing Well",
        "Support Recommended",
        "Urgent Support"
    ]

    if risk_level not in valid_risk_levels:

        risk_level = "Support Recommended"

    # Counsellor recommendation rules
    if risk_level in [
        "Support Recommended",
        "Urgent Support"
    ]:

        counsellor_recommended = True

    if not counsellor_message:

        counsellor_message = (
            "Talking with a school counsellor may be helpful."
        )

    # Validate suggestions
    if not isinstance(suggestions, list):

        suggestions = []

    suggestions = [
        str(item).strip()
        for item in suggestions
        if isinstance(item, str) and item.strip()
    ]

    if not suggestions:

        suggestions = [
            "Talk to someone you trust about your feelings.",
            "Take regular breaks and do activities you enjoy.",
            "Maintain a healthy sleep routine."
        ]

    # --------------------------------------------------------
    # DATABASE SCORE
    # --------------------------------------------------------

    if risk_level == "Doing Well":

        score = 1

    elif risk_level == "Support Recommended":

        score = 2

    else:

        score = 3

    # --------------------------------------------------------
    # SAVE RESULT IN MYSQL
    # --------------------------------------------------------

    db = None
    cursor = None

    try:

        db = get_db_connection()

        if db is None:

            raise Exception("Database connection failed.")

        cursor = db.cursor()

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
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                session["user_id"],
                "AI Conversational Assessment",
                score,
                risk_level,
                summary
            )
        )

        db.commit()

    except Exception as err:

        if db:
            db.rollback()

        print("Assessment Database Error:", repr(err))

        return jsonify({
            "error": "Your assessment result could not be saved. Please try again."
        }), 500

    finally:

        if cursor:
            cursor.close()

        if db:
            db.close()

    # --------------------------------------------------------
    # CLEAR SESSION AFTER SUCCESSFUL SAVE
    # --------------------------------------------------------

    session.pop("ai_assessment_history", None)
    session.pop("ai_assessment_turns", None)

    session.modified = True

    # --------------------------------------------------------
    # SEND FINAL RESULT TO FRONTEND
    # --------------------------------------------------------

    return jsonify({

        "completed": True,

        "risk_level": risk_level,

        "summary": summary,

        "counsellor_recommended": counsellor_recommended,

        "counsellor_message": counsellor_message,

        "suggestions": suggestions,

        "total_answers": 5

    })


# ============================================================
# AI DYNAMIC WELLNESS ASSESSMENT - END
# ============================================================



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
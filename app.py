from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import random
import re


# ---------------- Load ENV ----------------
load_dotenv()

# ---------------- App Setup ----------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
basedir = os.path.abspath(os.path.dirname(__file__))

# ---------------- Database Setup ----------------
db_path = os.path.join(basedir, "database.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ---------------- Mail Setup ----------------
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USE_SSL"] = False
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = app.config["MAIL_USERNAME"]

mail = Mail(app)

# ---------------- Upload Setup ----------------
UPLOAD_FOLDER = os.path.join(basedir, "static", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------- Models ----------------
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    branch = db.Column(db.String(100))
    year = db.Column(db.String(50))
    is_verified = db.Column(db.Boolean, default=False)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    president = db.Column(db.String(100), nullable=False)
    vice_president = db.Column(db.String(100), nullable=False)
    secretary = db.Column(db.String(100), nullable=False)
    treasurer = db.Column(db.String(100), nullable=False)

class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    image = db.Column(db.String(200))

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

# ---------------- Init Admin ----------------
with app.app_context():
    db.create_all()
    if not Admin.query.first():
        admin = Admin(
            username=os.getenv("ADMIN_USERNAME", "Raju"),
            password_hash=generate_password_hash(os.getenv("ADMIN_PASSWORD", "Raju@02"))
        )
        db.session.add(admin)
        db.session.commit()

# ---------------- Helpers ----------------
# ---------------- Helpers ----------------
def normalize_roll(roll):
    return (roll or "").strip().upper()

def valid_password(pw):
    return len(pw) >= 6 and bool(re.search(r"[A-Z]", pw))


def generate_rolls(input_text):
    rolls = set()
    items = input_text.replace("\n", ",").split(",")

    for item in items:
        item = item.strip()
        if not item:
            continue

        if item.startswith("!"):
            rolls.discard(item[1:].upper())
            continue

        if "-" in item:
            start, end = item.split("-")
            start = start.strip().upper()
            end = end.strip().upper()

            prefix = re.match(r"(.*?)(\d+)$", start).group(1)
            s_num = int(re.search(r"\d+$", start).group())
            e_num = int(re.search(r"\d+$", end).group())

            for i in range(s_num, e_num + 1):
                rolls.add(f"{prefix}{i}")
        else:
            rolls.add(item.upper())

    return sorted(rolls)


# ---------------- Routes ----------------
@app.route("/")
def home():
    return redirect(url_for("register"))

# -------- Register --------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        roll = normalize_roll(request.form.get("roll_number"))
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not roll or not email or not password:
            flash("❌ All fields required", "error")
            return redirect(url_for("register"))

        if not valid_password(password):
            flash("❌ Password must contain uppercase & 6+ chars", "error")
            return redirect(url_for("register"))

        student = Student.query.filter_by(roll_number=roll).first()

        # ❌ student not added by admin
        if not student:
            flash("❌ Roll number not found. Contact admin.", "error")
            return redirect(url_for("register"))

        # ❌ already verified
        if student.is_verified:
            flash("⚠️ Already registered. Please login.", "error")
            return redirect(url_for("login"))

        # store in session
        session["reg_student_id"] = student.id
        session["reg_password_hash"] = generate_password_hash(password)

        otp = str(random.randint(1000, 9999))
        session["otp"] = otp

        try:
            msg = Message(
                subject="OTP Verification",
                recipients=[email],
                body=f"Your OTP is: {otp}"
            )
            mail.send(msg)
            flash("📧 OTP sent to your email", "success")
            return redirect(url_for("verify"))
        except Exception as e:
            print("MAIL ERROR:", e)
            flash("❌ Failed to send OTP", "error")
            return redirect(url_for("register"))

    return render_template("register.html")


# -------- Verify --------
@app.route("/verify", methods=["GET", "POST"])
def verify():
    # Session check
    if "otp" not in session or "reg_student_id" not in session or "reg_password_hash" not in session:
        flash("❌ Session expired. Please register again.", "error")
        session.clear()
        return redirect(url_for("register"))

    if request.method == "POST":
        entered_otp = request.form.get("otp")

        # OTP validation
        if entered_otp != session.get("otp"):
            flash("❌ Invalid OTP", "error")
            return redirect(url_for("verify"))

        # Fetch student using ID (BEST PRACTICE)
        student = Student.query.get(session["reg_student_id"])

        if not student:
            flash("❌ Student record not found", "error")
            session.clear()
            return redirect(url_for("register"))

        # Update student
        student.password_hash = session["reg_password_hash"]
        student.is_verified = True

        db.session.commit()
        session.clear()

        flash("✅ Registration successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("otp.html")



# -------- Login --------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        roll = normalize_roll(request.form.get("roll_number"))
        password = request.form.get("password")

        student = Student.query.filter_by(roll_number=roll).first()

        if student and student.is_verified and check_password_hash(student.password_hash, password):
            session["student_id"] = student.id
            session["roll_number"] = roll
            return redirect(url_for("vote"))

        flash("❌ Invalid credentials", "error")

    return render_template("login.html")

# -------- Vote --------
@app.route("/vote", methods=["GET", "POST"])
def vote():
    if "student_id" not in session:
        return redirect(url_for("login"))

    roll = session.get("roll_number")

    # ---------- POST (Already correct) ----------
    if request.method == "POST":
        if Vote.query.filter_by(roll_number=roll).first():
            flash("⚠️ Already voted", "error")
            return redirect(url_for("thank_you"))

        president = request.form.get("president")
        vice_president = request.form.get("vice_president")
        secretary = request.form.get("secretary")
        treasurer = request.form.get("treasurer")

        if not all([president, vice_president, secretary, treasurer]):
            flash("❌ Please select all positions", "error")
            return redirect(url_for("vote"))

        vote = Vote(
            roll_number=roll,
            president=president,
            vice_president=vice_president,
            secretary=secretary,
            treasurer=treasurer
        )
        db.session.add(vote)
        db.session.commit()
        flash("🎉 Vote recorded", "success")
        return redirect(url_for("thank_you"))
    president_candidates = Candidate.query.filter_by(position="President").all()
    vice_president_candidates = Candidate.query.filter_by(position="Vice President").all()
    secretary_candidates = Candidate.query.filter_by(position="Secretary").all()
    treasurer_candidates = Candidate.query.filter_by(position="Treasurer").all()

    return render_template(
        "vote.html",
        president_candidates=president_candidates,
        vice_president_candidates=vice_president_candidates,
        secretary_candidates=secretary_candidates,
        treasurer_candidates=treasurer_candidates
    )

@app.route("/thank_you")
def thank_you():
    if "student_id" not in session:
        return redirect(url_for("login"))
    return render_template("thank_you.html")
# ---------------- logout ----------------
@app.route("/logout")
def logout():
    session.clear()
    flash("✅ Logged out", "success")
    return redirect(url_for("login"))
# -------- Admin --------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin = Admin.query.filter_by(username=request.form.get("username")).first()
        if admin and check_password_hash(admin.password_hash, request.form.get("password")):
            session["admin_id"] = admin.id
            return redirect(url_for("admin_dashboard"))
        flash("❌ Invalid admin credentials", "error")

    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

# -------- Manage Candidates --------
@app.route("/admin/candidates", methods=["GET", "POST"])
def manage_candidates():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form.get("name")
        position = request.form.get("position")
        image = request.files.get("image")

        filename = None
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        candidate = Candidate(name=name, position=position, image=filename)
        db.session.add(candidate)
        db.session.commit()
        flash("✅ Candidate added", "success")

    candidates = Candidate.query.all()
    return render_template("admin_candidates.html", candidates=candidates)

@app.route("/admin/candidates/delete/<int:id>")
def delete_candidate(id):
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    candidate = Candidate.query.get_or_404(id)
    db.session.delete(candidate)
    db.session.commit()
    flash("🗑 Candidate deleted", "success")
    return redirect(url_for("manage_candidates"))

#-------- Add Students --------#
@app.route("/admin/add-student", methods=["GET", "POST"])
def admin_add_student():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        year = request.form.get("year")
        branch = request.form.get("branch")
        roll_numbers = request.form.get("roll_numbers")

        if not year or not branch or not roll_numbers:
            flash("❌ All fields are required", "error")
            return redirect(url_for("admin_add_student"))

        # ✅ NEW: generate rolls from range + exclude
        roll_list = generate_rolls(roll_numbers)

        added = 0
        skipped = 0

        for roll in roll_list:
            if Student.query.filter_by(roll_number=roll).first():
                skipped += 1
                continue

            student = Student(
                roll_number=roll,
                email="",               # set during student registration
                password_hash="TEMP",   # replaced after OTP
                branch=branch,
                year=year,
                is_verified=False
            )
            db.session.add(student)
            added += 1

        db.session.commit()

        flash(
            f"✅ Added {added} students | ⚠️ Skipped {skipped} existing",
            "success"
        )
        return redirect(url_for("view_students"))

    return render_template("admin_add_students.html")

# -------- STUDENTS (FIX ADDED) --------
@app.route("/admin/students")
def view_students():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    students = Student.query.all()
    return render_template("admin_students.html", students=students)

@app.route("/admin/students/delete/<int:student_id>")
def delete_student(student_id):
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    student = Student.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()
    flash("🗑 Student deleted", "success")
    return redirect(url_for("view_students"))

@app.route("/admin/results")
def admin_results():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    results = {}

    mapping = {
        "president": "President",
        "vice_president": "Vice President",
        "secretary": "Secretary",
        "treasurer": "Treasurer"
    }

    for pos, pos_name in mapping.items():
        vote_data = (
            db.session.query(
                getattr(Vote, pos),
                db.func.count(Vote.id)
            )
            .group_by(getattr(Vote, pos))
            .all()
        )

        enriched = []
        for name, count in vote_data:
            candidate = Candidate.query.filter_by(
                name=name,
                position=pos_name
            ).first()

            enriched.append({
                "name": name,
                "count": count,
                "image": candidate.image if candidate else None
            })

        results[pos_name] = enriched

    return render_template("results.html", results=results)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    flash("✅ Admin logged out", "success")
    return redirect(url_for("admin_login"))

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

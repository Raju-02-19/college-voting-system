from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import random
import re

# ---------------- Load ENV ----------------
load_dotenv()

# ---------------- MongoDB Setup ----------------
mongo_uri = os.getenv("MONGO_URI", "").replace("\n", "").strip()

client = MongoClient(
    mongo_uri,
    serverSelectionTimeoutMS=5000
)

db = client["college_voting"]

students_col = db["students"]
admins_col = db["admins"]
candidates_col = db["candidates"]
votes_col = db["votes"]

# ---------------- App Setup ----------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
basedir = os.path.abspath(os.path.dirname(__file__))

# ---------------- Mail Setup ----------------
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
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

# ---------------- INIT ADMIN ----------------
# ---------------- INIT ADMIN ----------------
def init_admin():
    try:
        if admins_col.count_documents({}) == 0:
            admins_col.insert_one({
                "username": os.getenv("ADMIN_USERNAME", "admin"),
                "password_hash": generate_password_hash(
                    os.getenv("ADMIN_PASSWORD", "admin123")
                )
            })
            print("✅ Admin created")
    except Exception as e:
        print("⚠️ Admin init skipped:", e)

init_admin()


# ---------------- Helpers ----------------
def normalize_roll(roll):
    return (roll or "").strip().upper()

def valid_password(pw):
    return len(pw) >= 6 and bool(re.search(r"[A-Z]", pw))

def generate_rolls(input_text):
    rolls = set()
    skip_list = []

    for line in input_text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.lower().startswith("skip"):
            skip_part = line.split(":", 1)[1]
            skip_list = [normalize_roll(r) for r in skip_part.split(",")]
            continue

        if "-" in line:
            start, end = line.split("-")
            prefix = start[:-3]
            start_num = int(start[-3:])
            end_num = int(end[-3:])
            for i in range(start_num, end_num + 1):
                rolls.add(f"{prefix}{i:03d}")
        else:
            rolls.add(normalize_roll(line))

    return [r for r in sorted(rolls) if r not in skip_list]

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
            flash("❌ Password must have uppercase & 6+ chars", "error")
            return redirect(url_for("register"))

        student = students_col.find_one({"roll_number": roll})

        if not student:
            flash("❌ Roll number not added by admin", "error")
            return redirect(url_for("register"))

        if student["is_verified"]:
            flash("⚠️ Already registered. Please login.", "error")
            return redirect(url_for("login"))

        session["reg_roll"] = roll
        session["reg_email"] = email
        session["reg_password_hash"] = generate_password_hash(password)

        otp = str(random.randint(1000, 9999))
        session["otp"] = otp

        msg = Message(
            subject="OTP Verification",
            recipients=[email],
            body=f"Your OTP is: {otp}"
        )
        mail.send(msg)

        flash("📧 OTP sent to email", "success")
        return redirect(url_for("verify"))

    return render_template("register.html")

# -------- Verify OTP --------
@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "otp" not in session:
        flash("❌ Session expired", "error")
        return redirect(url_for("register"))

    if request.method == "POST":
        if request.form.get("otp") != session["otp"]:
            flash("❌ Invalid OTP", "error")
            return redirect(url_for("verify"))

        students_col.update_one(
            {"roll_number": session["reg_roll"]},
            {"$set": {
                "email": session["reg_email"],
                "password_hash": session["reg_password_hash"],
                "is_verified": True
            }}
        )

        session.clear()
        flash("✅ Registration successful", "success")
        return redirect(url_for("login"))

    return render_template("otp.html")

# -------- Login --------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        roll = normalize_roll(request.form.get("roll_number"))
        password = request.form.get("password")

        student = students_col.find_one({"roll_number": roll})

        if student and student["is_verified"] and check_password_hash(student["password_hash"], password):
            session["student_id"] = str(student["_id"])
            session["roll_number"] = roll
            return redirect(url_for("vote"))

        flash("❌ Invalid credentials", "error")

    return render_template("login.html")

# -------- Vote --------
@app.route("/vote", methods=["GET", "POST"])
def vote():
    if "student_id" not in session:
        return redirect(url_for("login"))

    roll = session["roll_number"]

    if request.method == "POST":
        if votes_col.find_one({"roll_number": roll}):
            flash("⚠️ Already voted", "error")
            return redirect(url_for("thank_you"))

        votes_col.insert_one({
            "roll_number": roll,
            "president": request.form.get("president"),
            "vice_president": request.form.get("vice_president"),
            "secretary": request.form.get("secretary"),
            "treasurer": request.form.get("treasurer")
        })

        flash("🎉 Vote recorded", "success")
        return redirect(url_for("thank_you"))

    return render_template(
        "vote.html",
        president_candidates=list(candidates_col.find({"position": "President"})),
        vice_president_candidates=list(candidates_col.find({"position": "Vice President"})),
        secretary_candidates=list(candidates_col.find({"position": "Secretary"})),
        treasurer_candidates=list(candidates_col.find({"position": "Treasurer"}))
    )

@app.route("/thank_you")
def thank_you():
    return render_template("thank_you.html")

# -------- Logout --------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------- Admin Login --------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin = admins_col.find_one({"username": request.form.get("username")})
        if admin and check_password_hash(admin["password_hash"], request.form.get("password")):
            session["admin_id"] = str(admin["_id"])
            return redirect(url_for("admin_dashboard"))
        flash("❌ Invalid admin login", "error")

    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

# -------- Add Students --------
@app.route("/admin/add-student", methods=["GET", "POST"])
def admin_add_student():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        roll_list = generate_rolls(request.form.get("roll_numbers"))
        year = request.form.get("year")
        branch = request.form.get("branch")

        added = skipped = 0
        for roll in roll_list:
            if students_col.find_one({"roll_number": roll}):
                skipped += 1
            else:
                students_col.insert_one({
                    "roll_number": roll,
                    "year": year,
                    "branch": branch,
                    "email": "",
                    "password_hash": "",
                    "is_verified": False
                })
                added += 1

        flash(f"✅ Added {added} | ⚠️ Skipped {skipped}", "success")
        return redirect(url_for("view_students"))

    return render_template("admin_add_students.html")
#-----manage candidates -----#
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

        candidates_col.insert_one({
            "name": name,
            "position": position,
            "image": filename
        })

        flash("✅ Candidate added", "success")

    candidates = list(candidates_col.find())
    return render_template("admin_candidates.html", candidates=candidates)

# -------- Delete Candidate --------
@app.route("/admin/candidates/delete/<candidate_id>")
def delete_candidate(candidate_id):
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    candidates_col.delete_one({
        "_id": ObjectId(candidate_id)
    })

    flash("🗑 Candidate deleted successfully", "success")
    return redirect(url_for("manage_candidates"))



# -------- View Students --------

@app.route("/admin/students")
def view_students():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    students_by_year = {}

    for year in ["1st Year", "2nd Year", "3rd Year", "4th Year"]:
        students = list(
            students_col.find({"year": year}).sort("roll_number", 1)
        )
        students_by_year[year] = students

    return render_template(
        "admin_students.html",
        students_by_year=students_by_year
    )
    
#--------- bulk delete students --------
@app.route("/admin/students/bulk-delete", methods=["POST"])
def bulk_delete_students():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    ids = request.form.getlist("student_ids")

    if not ids:
        flash("⚠️ No students selected", "error")
        return redirect(url_for("view_students"))

    object_ids = [ObjectId(i) for i in ids]

    result = students_col.delete_many({
        "_id": {"$in": object_ids}
    })

    flash(f"🗑 Deleted {result.deleted_count} students", "success")
    return redirect(url_for("view_students"))

#----------- Admin Results --------

@app.route("/admin/results")
def admin_results():
    if "admin_id" not in session:
        return redirect(url_for("admin_login"))

    results = {}

    positions = {
        "President": "president",
        "Vice President": "vice_president",
        "Secretary": "secretary",
        "Treasurer": "treasurer"
    }

    for pos_name, field in positions.items():
        vote_count = {}

        # Count votes
        for vote in votes_col.find():
            candidate_name = vote.get(field)
            if candidate_name:
                vote_count[candidate_name] = vote_count.get(candidate_name, 0) + 1

        enriched = []

        for name, count in vote_count.items():
            candidate = candidates_col.find_one({
                "name": name,
                "position": pos_name
            })

            enriched.append({
                "name": name,
                "count": count,
                "image": candidate.get("image") if candidate else None
            })

        results[pos_name] = enriched

    return render_template("results.html", results=results)



# -------- Admin Logout --------
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin_login"))

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
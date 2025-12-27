from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
import os
import re
from zoneinfo import ZoneInfo   # Python 3.9+


# ================= LOAD ENV =================
load_dotenv()

# ================= APP SETUP =================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ================= TIMEZONE (IST) =================
IST = timezone(timedelta(hours=5, minutes=30))

# ================= MONGODB =================
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["college_voting"]

students_col = db.students
admins_col = db.admins
candidates_col = db.candidates
votes_col = db.votes
settings_col = db.election_settings

# ================= FILE UPLOAD =================
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ================= HELPERS =================
def normalize_roll(roll):
    return (roll or "").strip().upper()

def valid_password(password):
    if not password:
        return False
    if len(password) < 6:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    return True

def generate_temp_password(roll):
    # first 2 digits + last 4 digits
    roll = normalize_roll(roll)
    return roll[:2] + roll[-4:]

def generate_rolls(input_text):
    rolls = set()
    skip = set()

    lines = input_text.replace(",", "\n").splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("!"):
            skip.add(normalize_roll(line[1:]))
            continue

        if "-" in line:
            start, end = line.split("-")
            start = normalize_roll(start)
            end = normalize_roll(end)

            prefix = start[:-4]
            s = int(start[-4:])
            e = int(end[-4:])

            for i in range(s, e + 1):
                rolls.add(f"{prefix}{i:04d}")
        else:
            rolls.add(normalize_roll(line))

    return sorted(rolls - skip)

# ================= INIT ADMIN =================
def init_admin():
    if admins_col.count_documents({}) == 0:
        admins_col.insert_one({
            "username": "admin",
            "password_hash": generate_password_hash("admin123")
        })
        print("✅ Default admin created (admin / admin123)")

init_admin()

# ================= VOTING TIME CHECK =================


from datetime import datetime
from zoneinfo import ZoneInfo

def is_voting_open():
    settings = settings_col.find_one()
    if not settings:
        return False, "❌ Voting schedule not set"

    tz = ZoneInfo("Asia/Kolkata")

    # current IST time
    now = datetime.now(tz)

    # MongoDB lo already +05:30 undi → direct parse
    start = datetime.fromisoformat(settings["start_time"])
    end = datetime.fromisoformat(settings["end_time"])

    # safety: ensure timezone
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)

    if now < start:
        return False, "⏳ Voting not started yet"
    if now > end:
        return False, "⛔ Voting ended"

    return True, ""



# =====================================================
# ================= STUDENT ROUTES ====================
# =====================================================

@app.route("/")
def home():
    return redirect(url_for("login"))

# ---------- REGISTER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        roll = normalize_roll(request.form.get("roll_number"))
        temp_pw = request.form.get("temp_password")
        email = request.form.get("email")
        new_pw = request.form.get("password")

        student = students_col.find_one({"roll_number": roll})
        if not student:
            flash("❌ Roll number not found", "error")
            return redirect(url_for("register"))

        if student.get("is_registered"):
            flash("⚠️ Already registered", "error")
            return redirect(url_for("login"))

        if not check_password_hash(student["password_hash"], temp_pw):
            flash("❌ Invalid temporary password", "error")
            return redirect(url_for("register"))

        if not valid_password(new_pw):
            flash("❌ Password must be 6+ chars & 1 uppercase", "error")
            return redirect(url_for("register"))

        students_col.update_one(
            {"roll_number": roll},
            {"$set": {
                "email": email,
                "password_hash": generate_password_hash(new_pw),
                "is_registered": True,
                "is_verified": True
            }}
        )

        flash("✅ Registration successful", "success")
        return redirect(url_for("login"))

    return render_template("student/register.html")

# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        roll = normalize_roll(request.form.get("roll_number"))
        password = request.form.get("password")

        student = students_col.find_one({"roll_number": roll})
        if student and check_password_hash(student["password_hash"], password):
            session["student_id"] = str(student["_id"])
            session["roll_number"] = roll
            return redirect(url_for("vote"))

        flash("❌ Invalid login", "error")

    return render_template("student/login.html")

# ---------- VOTE ----------
@app.route("/vote", methods=["GET", "POST"])
def vote():
    if "student_id" not in session:
        return redirect(url_for("login"))

    allowed, msg = is_voting_open()
    if not allowed:
        flash(msg, "error")
        return redirect(url_for("login"))

    roll = session["roll_number"]
    student = students_col.find_one({"roll_number": roll})

    if student.get("has_voted"):
        flash("⚠️ You already voted", "error")
        return redirect(url_for("thank_you"))

    if request.method == "POST":
        votes_col.insert_one({
            "roll_number": roll,
            "president": request.form.get("president"),
            "vice_president": request.form.get("vice_president"),
            "secretary": request.form.get("secretary"),
            "treasurer": request.form.get("treasurer"),
            "time": datetime.now(IST)
        })

        students_col.update_one(
            {"roll_number": roll},
            {"$set": {"has_voted": True}}
        )

        flash("🎉 Vote submitted successfully", "success")
        return redirect(url_for("thank_you"))

    return render_template(
        "student/vote.html",
        president_candidates=list(candidates_col.find({"position": "President"})),
        vice_president_candidates=list(candidates_col.find({"position": "Vice President"})),
        secretary_candidates=list(candidates_col.find({"position": "Secretary"})),
        treasurer_candidates=list(candidates_col.find({"position": "Treasurer"}))
    )

@app.route("/thank_you")
def thank_you():
    return render_template("student/thank_you.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =====================================================
# ================= ADMIN ROUTES ======================
# =====================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin = admins_col.find_one({"username": request.form.get("username")})
        if admin and check_password_hash(admin["password_hash"], request.form.get("password")):
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))

        flash("❌ Invalid admin login", "error")

    return render_template("admin/admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin/admin_dashboard.html")

# ---------- SET ELECTION TIME ----------

from datetime import datetime
from zoneinfo import ZoneInfo

@app.route("/admin/election-settings", methods=["GET", "POST"])
def admin_election_settings():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    tz = ZoneInfo("Asia/Kolkata")

    if request.method == "POST":
        start_date = request.form.get("start_date")
        start_time = request.form.get("start_time")
        end_date = request.form.get("end_date")
        end_time = request.form.get("end_time")

        # 🔒 basic validation
        if not all([start_date, start_time, end_date, end_time]):
            flash("❌ All date & time fields are required", "error")
            return redirect(url_for("admin_election_settings"))

        # ✅ create IST-aware datetime
        start_dt = datetime.fromisoformat(
            f"{start_date}T{start_time}"
        ).replace(tzinfo=tz)

        end_dt = datetime.fromisoformat(
            f"{end_date}T{end_time}"
        ).replace(tzinfo=tz)

        if start_dt >= end_dt:
            flash("❌ End time must be after start time", "error")
            return redirect(url_for("admin_election_settings"))

        # 🧹 allow only ONE election config
        settings_col.delete_many({})

        settings_col.insert_one({
            "start_time": start_dt.isoformat(),  # 2025-12-27T12:17:00+05:30
            "end_time": end_dt.isoformat(),
            "timezone": "Asia/Kolkata",
            "created_at": datetime.now(tz)
        })

        flash("✅ Election time saved successfully (IST)", "success")
        return redirect(url_for("admin_dashboard"))

    # GET request
    settings = settings_col.find_one()
    return render_template(
        "admin/admin_election_settings.html",
        settings=settings
    )





# ---------- ADD STUDENTS ----------
@app.route("/admin/add-student", methods=["GET", "POST"])
def admin_add_student():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        roll_text = request.form.get("roll_numbers")
        year = request.form.get("year")
        branch = request.form.get("branch")

        roll_list = generate_rolls(roll_text)
        added = skipped = 0

        for roll in roll_list:
            if students_col.find_one({"roll_number": roll}):
                skipped += 1
                continue

            temp_pw = generate_temp_password(roll)

            students_col.insert_one({
                "roll_number": roll,
                "year": year,
                "branch": branch,
                "email": "",
                "password_hash": generate_password_hash(temp_pw),
                "is_registered": False,
                "is_verified": False,
                "has_voted": False
            })
            added += 1

        flash(f"✅ Added {added} students | ⚠️ Skipped {skipped}", "success")
        return redirect(url_for("view_students"))

    return render_template("admin/admin_add_students.html")

# ---------- VIEW STUDENTS ----------
@app.route("/admin/students")
def view_students():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    students_by_year = {}
    for year in ["1st Year", "2nd Year", "3rd Year", "4th Year"]:
        students_by_year[year] = list(
            students_col.find({"year": year}).sort("roll_number", 1)
        )

    return render_template("admin/admin_students.html", students_by_year=students_by_year)

# ---------- BULK DELETE ----------
@app.route("/admin/students/bulk-delete", methods=["POST"])
def bulk_delete_students():
    ids = request.form.getlist("student_ids")
    students_col.delete_many({"_id": {"$in": [ObjectId(i) for i in ids]}})
    flash("🗑 Students deleted", "success")
    return redirect(url_for("view_students"))

# ---------- MANAGE CANDIDATES ----------
@app.route("/admin/candidates", methods=["GET", "POST"])
def manage_candidates():
    if not session.get("admin"):
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

    return render_template("admin/admin_candidates.html",
                           candidates=list(candidates_col.find()))

@app.route("/admin/candidates/delete/<cid>")
def delete_candidate(cid):
    candidates_col.delete_one({"_id": ObjectId(cid)})
    flash("🗑 Candidate deleted", "success")
    return redirect(url_for("manage_candidates"))

# ---------- RESULTS ----------



@app.route("/admin/results")
def admin_results():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    settings = settings_col.find_one()
    if not settings:
        flash("❌ Election time not set", "error")
        return redirect(url_for("admin_dashboard"))

    # 👇 IST now (aware)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    # 👇 Make stored time also aware
    end_time = datetime.fromisoformat(settings["end_time"])
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

    # ⛔ Lock results till voting ends
    if now < end_time:
        return render_template(
            "admin/results.html",
            results_open=False,
            results={}
        )

    # ✅ RESULTS OPEN
    results = {}
    positions = {
        "President": "president",
        "Vice President": "vice_president",
        "Secretary": "secretary",
        "Treasurer": "treasurer"
    }

    for pos, field in positions.items():
        count = {}
        for v in votes_col.find():
            name = v.get(field)
            if name:
                count[name] = count.get(name, 0) + 1

        enriched = []
        for name, votes in count.items():
            cand = candidates_col.find_one({"name": name, "position": pos})
            enriched.append({
                "name": name,
                "count": votes,
                "image": cand.get("image") if cand else None
            })

        results[pos] = enriched

    return render_template(
        "admin/results.html",
        results_open=True,
        results=results
    )


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, random, pandas as pd, re
from dotenv import load_dotenv

load_dotenv()

# ---- Flask App Setup ----
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")
basedir = os.path.abspath(os.path.dirname(__file__))

# ---- Database Setup ----
db_path = os.path.join(basedir, "database.db")  # write in project folder
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ---- Mail Setup ----
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() in ("true","1","yes")
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False').lower() in ("true","1","yes")
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_DEFAULT_SENDER", app.config.get("MAIL_USERNAME"))
mail = Mail(app)

# ---- File Upload Setup ----
UPLOAD_FOLDER = os.path.join(basedir, "static", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ---- Load Allowed Students from Excel ----
students_xlsx = os.path.join(basedir, "students.xlsx")
if os.path.exists(students_xlsx):
    allowed_students = pd.read_excel(students_xlsx, dtype=str).fillna("")
    allowed_students.columns = allowed_students.columns.str.strip().str.lower()
    col_map = {}
    for col in allowed_students.columns:
        if "roll" in col: col_map[col] = "roll_number"
        if "email" in col: col_map[col] = "email"
        if "branch" in col: col_map[col] = "branch"
        if "year" in col: col_map[col] = "year"
    if col_map:
        allowed_students = allowed_students.rename(columns=col_map)
    for c in ["roll_number", "email", "branch", "year"]:
        if c not in allowed_students.columns:
            allowed_students[c] = ""
    allowed_students["roll_number"] = allowed_students["roll_number"].astype(str).str.strip().str.upper()
else:
    allowed_students = pd.DataFrame(columns=["roll_number", "email", "branch", "year"])

# ---- Database Models ----
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
    image = db.Column(db.String(200))  # optional

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

# ---- Initialize Admin ----
with app.app_context():
    db.create_all()
    if not Admin.query.first():
        admin_username = os.getenv("ADMIN_USERNAME", "Raju")
        admin_password = os.getenv("ADMIN_PASSWORD", "Raju@02")
        admin = Admin(username=admin_username, password_hash=generate_password_hash(admin_password))
        db.session.add(admin)
        db.session.commit()
        print(f"Admin created: {admin_username}")

# ---- Helper Functions ----
def normalize_roll(roll):
    return (roll or "").strip().upper()

def valid_password(pw):
    return len(pw) >= 6 and bool(re.search(r"[A-Z]", pw))

# ---------------- Student Routes ----------------
@app.route("/")
def home():
    return redirect(url_for("register"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        roll = normalize_roll(request.form.get("roll_number"))
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not roll or not email or not password:
            flash("❌ All fields required","error")
            return redirect(url_for("register"))
        if not valid_password(password):
            flash("❌ Password must have 6+ chars and uppercase","error")
            return redirect(url_for("register"))

        student_excel = allowed_students[allowed_students["roll_number"]==roll]
        if student_excel.empty:
            flash("❌ Roll number not allowed","error")
            return redirect(url_for("register"))
        if Student.query.filter_by(roll_number=roll).first():
            flash("⚠️ Already registered","error")
            return redirect(url_for("register"))

        # Save session for OTP
        session["reg_roll"] = roll
        session["reg_email"] = email
        session["reg_password_hash"] = generate_password_hash(password)
        session["reg_branch"] = student_excel.iloc[0].get("branch","")
        session["reg_year"] = str(student_excel.iloc[0].get("year",""))

        # Generate OTP
        otp = str(random.randint(1000,9999))
        session["otp"] = otp

        # Send OTP if possible, else flash it
        try:
            if app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD'):
                msg = Message(subject="Your College Voting OTP", recipients=[email], body=f"Your OTP is: {otp}")
                mail.send(msg)
                flash("ℹ️ OTP sent to email","info")
            else:
                flash(f"ℹ️ Mail suppressed. OTP: {otp}","info")
        except Exception as e:
            flash(f"ℹ️ Unable to send email. OTP: {otp}","info")

        return redirect(url_for("verify"))
    return render_template("register.html")

@app.route("/verify", methods=["GET","POST"])
def verify():
    if request.method=="POST":
        otp_entered = request.form.get("otp","").strip()
        if otp_entered==session.get("otp"):
            student = Student(
                roll_number=session.get("reg_roll"),
                email=session.get("reg_email"),
                password_hash=session.get("reg_password_hash"),
                branch=session.get("reg_branch"),
                year=session.get("reg_year"),
                is_verified=True
            )
            db.session.add(student)
            db.session.commit()
            for key in ["otp","reg_roll","reg_email","reg_password_hash","reg_branch","reg_year"]:
                session.pop(key,None)
            flash("🎉 Verified! You can login","success")
            return redirect(url_for("login"))
        else:
            flash("❌ Invalid OTP","error")
            return redirect(url_for("verify"))
    return render_template("otp.html")

# ---------------- Login / Logout ----------------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        roll = normalize_roll(request.form.get("roll_number"))
        password = request.form.get("password")
        student = Student.query.filter_by(roll_number=roll).first()
        if student and student.is_verified and check_password_hash(student.password_hash,password):
            session["student_id"] = student.id
            session["roll_number"] = student.roll_number
            flash("✅ Login successful","success")
            return redirect(url_for("vote"))
        flash("❌ Invalid credentials","error")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("student_id",None)
    session.pop("roll_number",None)
    flash("✅ Logged out","success")
    return redirect(url_for("login"))

# ---------------- Voting Routes ----------------
@app.route("/vote", methods=["GET","POST"])
def vote():
    if "student_id" not in session:
        flash("⚠️ Login first","error")
        return redirect(url_for("login"))
    roll = session.get("roll_number")
    if request.method=="POST":
        if Vote.query.filter_by(roll_number=roll).first():
            flash("⚠️ Already voted","error")
            return redirect(url_for("thank_you"))
        president = request.form.get("president")
        vice_president = request.form.get("vice_president")
        secretary = request.form.get("secretary")
        treasurer = request.form.get("treasurer")
        if not all([president,vice_president,secretary,treasurer]):
            flash("❌ Select all positions","error")
            return redirect(url_for("vote"))
        new_vote = Vote(
            roll_number=roll,
            president=president,
            vice_president=vice_president,
            secretary=secretary,
            treasurer=treasurer
        )
        db.session.add(new_vote)
        db.session.commit()
        flash("🎉 Vote recorded","success")
        return redirect(url_for("thank_you"))

    president_candidates = Candidate.query.filter_by(position="President").all()
    vice_president_candidates = Candidate.query.filter_by(position="Vice President").all()
    secretary_candidates = Candidate.query.filter_by(position="Secretary").all()
    treasurer_candidates = Candidate.query.filter_by(position="Treasurer").all()

    return render_template("vote.html",
        president_candidates=president_candidates,
        vice_president_candidates=vice_president_candidates,
        secretary_candidates=secretary_candidates,
        treasurer_candidates=treasurer_candidates
    )

@app.route("/thank_you")
def thank_you():
    return render_template("thank_you.html")

# ---------------- Admin Routes ----------------
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash,password):
            session["admin_id"] = admin.id
            flash("✅ Admin login successful","success")
            return redirect(url_for("admin_dashboard"))
        flash("❌ Invalid admin credentials","error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id",None)
    flash("✅ Admin logged out","success")
    return redirect(url_for("admin_login"))

@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin_id" not in session:
        flash("⚠️ Admin login required","error")
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

# ----- View / Delete Students -----
@app.route("/admin/students")
def view_students():
    if "admin_id" not in session:
        flash("⚠️ Admin login required","error")
        return redirect(url_for("admin_login"))
    students = Student.query.all()
    return render_template("admin_students.html", students=students)

@app.route("/admin/students/delete/<int:student_id>")
def delete_student(student_id):
    if "admin_id" not in session:
        flash("⚠️ Admin login required","error")
        return redirect(url_for("admin_login"))
    student = Student.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()
    flash("✅ Student deleted","success")
    return redirect(url_for("view_students"))

# ----- Manage Candidates -----
@app.route("/admin/candidates", methods=["GET","POST"])
def manage_candidates():
    if "admin_id" not in session:
        flash("⚠️ Admin login required","error")
        return redirect(url_for("admin_login"))
    if request.method=="POST":
        name = request.form.get("name")
        position = request.form.get("position")
        image_file = request.files.get("image")
        filename = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        candidate = Candidate(name=name, position=position, image=filename)
        db.session.add(candidate)
        db.session.commit()
        flash("✅ Candidate added","success")
        return redirect(url_for("manage_candidates"))
    candidates = Candidate.query.all()
    return render_template("admin_candidates.html", candidates=candidates)

@app.route("/admin/candidates/delete/<int:candidate_id>")
def delete_candidate(candidate_id):
    if "admin_id" not in session:
        flash("⚠️ Admin login required","error")
        return redirect(url_for("admin_login"))
    candidate = Candidate.query.get_or_404(candidate_id)
    if candidate.image:
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], candidate.image)
        if os.path.exists(img_path):
            os.remove(img_path)
    db.session.delete(candidate)
    db.session.commit()
    flash("✅ Candidate deleted","success")
    return redirect(url_for("manage_candidates"))

# ----- View Results -----
@app.route("/admin/results")
def admin_results():
    if "admin_id" not in session:
        flash("⚠️ Admin login required","error")
        return redirect(url_for("admin_login"))
    results_dict = {}
    positions = ["President","Vice President","Secretary","Treasurer"]
    for pos in positions:
        candidates = Candidate.query.filter_by(position=pos).all()
        candidate_results = []
        for c in candidates:
            votes_count = Vote.query.filter(getattr(Vote,pos.lower().replace(" ","_"))==c.name).count()
            candidate_results.append({"name":c.name,"votes":votes_count,"image":c.image})
        results_dict[pos] = candidate_results
    return render_template("results.html", results_dict=results_dict)

# ---------------- Run App ----------------
if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)

# ============================================================
# auth.py — Login / Register / Logout routes
# ============================================================

from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_bcrypt import Bcrypt
from database import create_user, get_user_by_username

auth = Blueprint("auth", __name__)
bcrypt = Bcrypt()


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_username(username)
        if not user:
            error = "ไม่พบ username นี้ในระบบ"
        elif not bcrypt.check_password_hash(user["password"], password):
            error = "รหัสผ่านไม่ถูกต้อง"
        else:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))

    return render_template("login.html", error=error)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username  = request.form.get("username", "").strip()
        email     = request.form.get("email", "").strip()
        password  = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not username or not email or not password:
            error = "กรุณากรอกข้อมูลให้ครบ"
        elif len(username) < 3:
            error = "Username ต้องมีอย่างน้อย 3 ตัวอักษร"
        elif len(password) < 6:
            error = "Password ต้องมีอย่างน้อย 6 ตัวอักษร"
        elif password != password2:
            error = "รหัสผ่านทั้งสองไม่ตรงกัน"
        elif "@" not in email:
            error = "รูปแบบ Email ไม่ถูกต้อง"
        else:
            hashed = bcrypt.generate_password_hash(password).decode("utf-8")
            user_id = create_user(username, email, hashed)
            if user_id is None:
                error = "Username หรือ Email นี้ถูกใช้ไปแล้ว"
            else:
                session["user_id"]  = user_id
                session["username"] = username
                return redirect(url_for("index"))

    return render_template("register.html", error=error)


@auth.route("/logout")
def logout():
    session.clear()# ============================================================
# auth.py — Login / Register / Logout routes
# ============================================================

from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_bcrypt import Bcrypt
from database import create_user, get_user_by_username

auth = Blueprint("auth", __name__)
bcrypt = Bcrypt()


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_username(username)
        if not user:
            error = "ไม่พบ username นี้ในระบบ"
        elif not bcrypt.check_password_hash(user["password"], password):
            error = "รหัสผ่านไม่ถูกต้อง"
        else:
            session["user_id"]      = user["id"]
            session["username"]     = user["username"]
            session["groq_api_key"] = user["groq_api_key"]  # โหลด key เข้า session
            return redirect(url_for("index"))

    return render_template("login.html", error=error)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username     = request.form.get("username", "").strip()
        email        = request.form.get("email", "").strip()
        password     = request.form.get("password", "")
        password2    = request.form.get("password2", "")
        groq_api_key = request.form.get("groq_api_key", "").strip()

        # ── Validate ─────────────────────────────────────────
        if not username or not email or not password:
            error = "กรุณากรอกข้อมูลให้ครบ"
        elif len(username) < 3:
            error = "Username ต้องมีอย่างน้อย 3 ตัวอักษร"
        elif len(password) < 6:
            error = "Password ต้องมีอย่างน้อย 6 ตัวอักษร"
        elif password != password2:
            error = "รหัสผ่านทั้งสองไม่ตรงกัน"
        elif "@" not in email:
            error = "รูปแบบ Email ไม่ถูกต้อง"
        elif not groq_api_key:
            error = "กรุณากรอก Groq API Key"
        elif not groq_api_key.startswith("gsk_"):
            error = "API Key ต้องขึ้นต้นด้วย gsk_"
        elif len(groq_api_key) != 56:
            error = f"ความยาว API Key ไม่ถูกต้อง (ต้องมี 52 ตัวอักษร, ปัจจุบัน {len(groq_api_key)} ตัว)"
        elif not groq_api_key[4:].isalnum():
            error = "API Key มีตัวอักษรที่ไม่ถูกต้อง (ใช้ได้เฉพาะ a-z, A-Z, 0-9)"
        else:
            hashed = bcrypt.generate_password_hash(password).decode("utf-8")
            user_id = create_user(username, email, hashed, groq_api_key)
            if user_id is None:
                error = "Username หรือ Email นี้ถูกใช้ไปแล้ว"
            else:
                session["user_id"]      = user_id
                session["username"]     = username
                session["groq_api_key"] = groq_api_key
                return redirect(url_for("index"))

    return render_template("register.html", error=error)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
    return redirect(url_for("auth.login"))
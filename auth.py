# ============================================================
# auth.py — Login / Register / Logout routes
# ============================================================

import time
from collections import defaultdict, deque
from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_bcrypt import Bcrypt
from database_postgres import create_user, get_user_by_username

auth = Blueprint("auth", __name__)
bcrypt = Bcrypt()

MAX_FAILED_LOGINS = 8
LOGIN_WINDOW_SECONDS = 300
_failed_logins = defaultdict(deque)


def _login_keys(username):
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    ip = forwarded or request.remote_addr or "unknown"
    return [f"ip:{ip}", f"user:{username.lower()}"]


def _is_locked(keys):
    now = time.time()
    for key in keys:
        attempts = _failed_logins[key]
        while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= MAX_FAILED_LOGINS:
            return True
    return False


def _record_failure(keys):
    now = time.time()
    for key in keys:
        _failed_logins[key].append(now)


def _clear_failures(keys):
    for key in keys:
        _failed_logins.pop(key, None)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        keys = _login_keys(username)
        user = None if _is_locked(keys) else get_user_by_username(username)
        if _is_locked(keys):
            error = "พยายามเข้าสู่ระบบผิดหลายครั้งเกินไป กรุณารอ 5 นาทีแล้วลองใหม่"
        elif not user or not bcrypt.check_password_hash(user["password_hash"], password):
            _record_failure(keys)
            error = "Username หรือรหัสผ่านไม่ถูกต้อง"
        else:
            _clear_failures(keys)
            session.clear()
            session.permanent = True
            session["user_id"]      = user["id"]
            session["username"]     = user["username"]
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
            error = f"ความยาว API Key ไม่ถูกต้อง (ปัจจุบัน {len(groq_api_key)} ตัว)"
        elif not groq_api_key[4:].isalnum():
            error = "API Key มีตัวอักษรที่ไม่ถูกต้อง (ใช้ได้เฉพาะ a-z, A-Z, 0-9)"
        else:
            hashed = bcrypt.generate_password_hash(password).decode("utf-8")
            user_id = create_user(username, email, hashed, groq_api_key)
            if user_id is None:
                error = "Username หรือ Email นี้ถูกใช้ไปแล้ว"
            else:
                session.clear()
                session.permanent = True
                session["user_id"]      = user_id
                session["username"]     = username
                return redirect(url_for("index"))

    return render_template("register.html", error=error)


@auth.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
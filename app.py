import os
import re
import secrets
import sqlite3
import time
from hashlib import sha256
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.security import check_password_hash, generate_password_hash


COOKIE_NAME = "task_list_id"
SESSION_COOKIE = "task_list_session"
SESSION_AGE = 14 * 24 * 60 * 60
MAX_TITLE_LENGTH = 120


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    url_prefix = os.environ.get("TASK_LIST_URL_PREFIX", "").rstrip("/")
    if url_prefix:
        app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {url_prefix: app.wsgi_app})
    data_dir = Path(os.environ.get("TASK_LIST_DATA_DIR", app.instance_path))
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "tasks.sqlite3"
    secure_cookies = os.environ.get("TASK_LIST_HTTPS") == "1"

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(database_path, timeout=5)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    with app.app_context():
        db().executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_id TEXT NOT NULL,
                title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1))
            );
            CREATE INDEX IF NOT EXISTS tasks_by_list ON tasks (list_id, id);
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_sessions (
                token_hash TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
        """)

    def current_account():
        if "account" not in g:
            token = cookie_token(SESSION_COOKIE)
            g.account = db().execute(
                """
                SELECT accounts.id, accounts.username FROM accounts
                JOIN account_sessions ON account_sessions.account_id = accounts.id
                WHERE account_sessions.token_hash = ? AND account_sessions.expires_at > ?
                """,
                (sha256(token.encode()).hexdigest(), int(time.time())),
            ).fetchone() if token else None
        return g.account

    def current_list_id():
        account = current_account()
        return f"account:{account['id']}" if account is not None else cookie_token(COOKIE_NAME)

    def start_session(connection, account_id):
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        previous = cookie_token(SESSION_COOKIE)
        connection.execute("DELETE FROM account_sessions WHERE expires_at <= ?", (now,))
        if previous:
            connection.execute(
                "DELETE FROM account_sessions WHERE token_hash = ?",
                (sha256(previous.encode()).hexdigest(),),
            )
        connection.execute(
            "INSERT INTO account_sessions (token_hash, account_id, expires_at) VALUES (?, ?, ?)",
            (sha256(token.encode()).hexdigest(), account_id, now + SESSION_AGE),
        )
        response = jsonify({"status": "ok"})
        set_cookie(response, SESSION_COOKIE, token, SESSION_AGE)
        return response

    def set_cookie(response, name, value, max_age):
        response.set_cookie(
            name, value, max_age=max_age, path=request.script_root or "/",
            httponly=True, samesite="Lax", secure=secure_cookies,
        )

    @app.after_request
    def avoid_caching_personal_content(response):
        if request.path == "/" or request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        return render_template("index.html", max_title_length=MAX_TITLE_LENGTH, account=current_account())

    @app.post("/api/register")
    def register():
        username, password = credentials()
        if not re.fullmatch(r"[a-z0-9_-]{3,32}", username):
            return {"error": "账号使用 3 至 32 位英文字母、数字、下划线或短横线。"}, 400
        if not 8 <= len(password) <= 128:
            return {"error": "请输入 8 至 128 个字符的密码。"}, 400

        password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO accounts (username, password_hash) VALUES (?, ?) ON CONFLICT (username) DO NOTHING",
                (username, password_hash),
            )
            if cursor.rowcount == 0:
                return {"error": "这个账号名已被使用。请登录或换一个账号名。"}, 409
            response = start_session(connection, cursor.lastrowid)
        return response, 201

    @app.post("/api/login")
    def login():
        username, password = credentials()
        account = db().execute(
            "SELECT id, password_hash FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if account is None or not 8 <= len(password) <= 128 or not check_password_hash(account["password_hash"], password):
            return {"error": "账号或密码有误。"}, 401

        with db() as connection:
            return start_session(connection, account["id"])

    @app.post("/api/logout")
    def logout():
        if not request.is_json:
            return {"error": "请从任务清单页面退出登录。"}, 415
        token = cookie_token(SESSION_COOKIE)
        if token:
            with db() as connection:
                connection.execute(
                    "DELETE FROM account_sessions WHERE token_hash = ?", (sha256(token.encode()).hexdigest(),)
                )
        response = jsonify({"status": "ok"})
        set_cookie(response, SESSION_COOKIE, "", 0)
        return response

    @app.get("/healthz")
    def health():
        db().execute("SELECT 1 FROM tasks LIMIT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/tasks")
    def list_tasks():
        list_id = current_list_id()
        if list_id is None:
            response = jsonify([])
            set_cookie(response, COOKIE_NAME, secrets.token_urlsafe(32), 60 * 60 * 24 * 365)
            return response

        rows = db().execute(
            "SELECT id, title, done FROM tasks WHERE list_id = ? ORDER BY id DESC",
            (list_id,),
        ).fetchall()
        return jsonify([serialize_task(row) for row in rows])

    @app.post("/api/tasks")
    def add_task():
        list_id = current_list_id()
        if list_id is None:
            return {"error": "请允许浏览器保存 Cookie，然后刷新页面。"}, 400

        payload = request.get_json(silent=True)
        title = payload.get("title") if isinstance(payload, dict) else None
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= MAX_TITLE_LENGTH:
            return {"error": f"请输入 1 至 {MAX_TITLE_LENGTH} 个字符的任务。"}, 400

        title = title.strip()
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks (list_id, title) VALUES (?, ?)", (list_id, title)
            )
        return {"id": cursor.lastrowid, "title": title, "done": False}, 201

    @app.patch("/api/tasks/<int:task_id>")
    def change_task(task_id):
        payload = request.get_json(silent=True)
        done = payload.get("done") if isinstance(payload, dict) else None
        if not isinstance(done, bool):
            return {"error": "请选择任务是否完成。"}, 400

        with db() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET done = ? WHERE id = ? AND list_id = ?",
                (done, task_id, current_list_id()),
            )
        if cursor.rowcount == 0:
            return {"error": "找不到这项任务。"}, 404
        return "", 204

    @app.delete("/api/tasks/<int:task_id>")
    def delete_task(task_id):
        with db() as connection:
            cursor = connection.execute(
                "DELETE FROM tasks WHERE id = ? AND list_id = ?",
                (task_id, current_list_id()),
            )
        if cursor.rowcount == 0:
            return {"error": "找不到这项任务。"}, 404
        return "", 204

    return app


def cookie_token(name):
    token = request.cookies.get(name, "")
    return token if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None


def credentials():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return "", ""
    username = payload.get("username")
    password = payload.get("password")
    return (username.strip().lower() if isinstance(username, str) else "",
            password if isinstance(password, str) else "")


def serialize_task(row):
    return {"id": row["id"], "title": row["title"], "done": bool(row["done"])}

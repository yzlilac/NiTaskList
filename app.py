import os
import re
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request
from werkzeug.middleware.dispatcher import DispatcherMiddleware


COOKIE_NAME = "task_list_id"
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

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(database_path, timeout=5)
            g.db.row_factory = sqlite3.Row
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
        """)

    def current_list_id():
        token = request.cookies.get(COOKIE_NAME, "")
        return token if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None

    @app.after_request
    def avoid_caching_tasks(response):
        if request.path.startswith("/api/tasks"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        return render_template("index.html", max_title_length=MAX_TITLE_LENGTH)

    @app.get("/healthz")
    def health():
        db().execute("SELECT 1 FROM tasks LIMIT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/tasks")
    def list_tasks():
        list_id = current_list_id()
        if list_id is None:
            response = jsonify([])
            response.set_cookie(
                COOKIE_NAME,
                secrets.token_urlsafe(32),
                max_age=60 * 60 * 24 * 365,
                path=request.script_root or "/",
                httponly=True,
                samesite="Lax",
                secure=os.environ.get("TASK_LIST_HTTPS") == "1",
            )
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


def serialize_task(row):
    return {"id": row["id"], "title": row["title"], "done": bool(row["done"])}

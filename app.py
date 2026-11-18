"""
IELTS Backend  (Flask + SQLite)
Testlar, savollar va natijalar uchun REST API.
GET   -> hamma uchun ochiq (faqat published testlar)
POST/PUT/PATCH/DELETE -> X-API-Key header (ADMIN_KEY) talab qiladi
Istisno: POST /api/tests/<id>/submit  (talaba javob yuboradi) - ochiq
"""
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_env()
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "ielts.db"))

SECTIONS = ("reading", "listening", "writing")
DIFFICULTIES = ("easy", "medium", "hard")
Q_TYPES = ("multiple_choice", "true_false_not_given", "fill_blank", "short_answer", "matching")

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
app.json.sort_keys = False


# ───────────────────────── DB ─────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    section TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'medium',
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    description TEXT NOT NULL DEFAULT '',
    passage TEXT NOT NULL DEFAULT '',
    audio_url TEXT NOT NULL DEFAULT '',
    is_published INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    number INTEGER NOT NULL DEFAULT 1,
    type TEXT NOT NULL DEFAULT 'multiple_choice',
    text TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',
    correct_answer TEXT NOT NULL DEFAULT '""',
    points REAL NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_test ON questions(test_id, number);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    student_name TEXT NOT NULL DEFAULT '',
    answers TEXT NOT NULL DEFAULT '{}',
    writing_text TEXT NOT NULL DEFAULT '',
    correct_count REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    band REAL,
    status TEXT NOT NULL DEFAULT 'graded',
    teacher_comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ───────────────────── yordamchi funksiyalar ─────────────────────
class ApiError(Exception):
    def __init__(self, message, status=400, details=None):
        self.message, self.status, self.details = message, status, details


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"error": e.message}
    if e.details:
        body["details"] = e.details
    return jsonify(body), e.status


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "Topilmadi"}), 404


@app.errorhandler(405)
def method_not_allowed(_e):
    return jsonify({"error": "Bu metod ruxsat etilmagan"}), 405


@app.errorhandler(Exception)
def unhandled(e):
    app.logger.exception(e)
    return jsonify({"error": "Server xatosi"}), 500


def is_admin():
    if not ADMIN_KEY:
        return False
    key = request.headers.get("X-API-Key") or request.args.get("key", "")
    return key == ADMIN_KEY


def require_admin():
    if not ADMIN_KEY:
        raise ApiError("Serverda ADMIN_KEY sozlanmagan (.env faylini tekshiring)", 500)
    if not is_admin():
        raise ApiError("Ruxsat yo'q: X-API-Key noto'g'ri yoki yo'q", 401)


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("JSON body kerak (Content-Type: application/json)")
    return data


def paging():
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        raise ApiError("limit/offset son bo'lishi kerak")
    return limit, offset


def jload(s, default):
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "ha")
    return False


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# ───────────────────── serializatsiya ─────────────────────
def test_out(r, question_count=None):
    d = {
        "id": r["id"], "title": r["title"], "section": r["section"],
        "difficulty": r["difficulty"], "duration_minutes": r["duration_minutes"],
        "description": r["description"], "passage": r["passage"],
        "audio_url": r["audio_url"], "is_published": bool(r["is_published"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }
    if question_count is not None:
        d["question_count"] = question_count
    return d


def question_out(r, with_answer):
    d = {
        "id": r["id"], "test_id": r["test_id"], "number": r["number"],
        "type": r["type"], "text": r["text"], "options": jload(r["options"], []),
        "points": r["points"],
    }
    if with_answer:
        d["correct_answer"] = jload(r["correct_answer"], "")
    return d


def result_out(r):
    return {
        "id": r["id"], "test_id": r["test_id"], "student_name": r["student_name"],
        "answers": jload(r["answers"], {}), "writing_text": r["writing_text"],
        "correct_count": r["correct_count"], "total": r["total"], "band": r["band"],
        "status": r["status"], "teacher_comment": r["teacher_comment"],
        "created_at": r["created_at"],
    }


# ───────────────────── validatsiya ─────────────────────
def clean_test(data, partial=False):
    if not isinstance(data, dict):
        raise ApiError("Body obyekt bo'lishi kerak")
    out, errors = {}, {}
    if "title" in data or not partial:
        t = str(data.get("title", "")).strip()
        if not t:
            errors["title"] = "majburiy"
        else:
            out["title"] = t
    if "section" in data or not partial:
        s = str(data.get("section", "")).strip().lower()
        if s not in SECTIONS:
            errors["section"] = f"quyidagilardan biri bo'lsin: {', '.join(SECTIONS)}"
        else:
            out["section"] = s
    if "difficulty" in data:
        d = str(data["difficulty"]).strip().lower()
        if d not in DIFFICULTIES:
            errors["difficulty"] = f"quyidagilardan biri bo'lsin: {', '.join(DIFFICULTIES)}"
        else:
            out["difficulty"] = d
    if "duration_minutes" in data:
        try:
            m = int(data["duration_minutes"])
            if m < 1:
                raise ValueError
            out["duration_minutes"] = m
        except (TypeError, ValueError):
            errors["duration_minutes"] = "musbat butun son bo'lsin"
    for f in ("description", "passage", "audio_url"):
        if f in data:
            out[f] = str(data[f] or "")
    if "is_published" in data:
        out["is_published"] = 1 if to_bool(data["is_published"]) else 0
    if errors:
        raise ApiError("Validatsiya xatosi", 422, errors)
    return out


def clean_question(data, partial=False):
    if not isinstance(data, dict):
        raise ApiError("Savol obyekt bo'lishi kerak")
    out, errors = {}, {}
    if "text" in data or not partial:
        t = str(data.get("text", "")).strip()
        if not t:
            errors["text"] = "majburiy"
        else:
            out["text"] = t
    if "type" in data:
        ty = str(data["type"]).strip().lower()
        if ty not in Q_TYPES:
            errors["type"] = f"quyidagilardan biri bo'lsin: {', '.join(Q_TYPES)}"
        else:
            out["type"] = ty
    if "number" in data:
        try:
            out["number"] = int(data["number"])
        except (TypeError, ValueError):
            errors["number"] = "butun son bo'lsin"
    if "points" in data:
        try:
            p = float(data["points"])
            if p < 0:
                raise ValueError
            out["points"] = p
        except (TypeError, ValueError):
            errors["points"] = "manfiy bo'lmagan son bo'lsin"
    if "options" in data:
        if not isinstance(data["options"], list):
            errors["options"] = "ro'yxat (list) bo'lsin"
        else:
            out["options"] = json.dumps(data["options"], ensure_ascii=False)
    if "correct_answer" in data:
        ca = data["correct_answer"]
        if not isinstance(ca, (str, int, float, list)):
            errors["correct_answer"] = "matn yoki matnlar ro'yxati bo'lsin"
        else:
            out["correct_answer"] = json.dumps(ca, ensure_ascii=False)
    if errors:
        raise ApiError("Validatsiya xatosi", 422, errors)
    return out


def get_test_or_404(test_id):
    row = get_db().execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
    if not row or (not row["is_published"] and not is_admin()):
        raise ApiError("Test topilmadi", 404)
    return row


def get_question_or_404(qid):
    row = get_db().execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        raise ApiError("Savol topilmadi", 404)
    return row


def insert_question(db, test_id, data):
    q = clean_question(data)
    if "number" not in q:
        n = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM questions WHERE test_id=?", (test_id,)).fetchone()[0]
        q["number"] = n
    ts = now()
    cur = db.execute(
        """INSERT INTO questions (test_id, number, type, text, options, correct_answer, points, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (test_id, q["number"], q.get("type", "multiple_choice"), q["text"],
         q.get("options", "[]"), q.get("correct_answer", '""'), q.get("points", 1), ts, ts),
    )
    return cur.lastrowid


def update_row(table, row_id, fields):
    if not fields:
        return
    fields = dict(fields, updated_at=now())
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), row_id))


# ───────────────────── CORS ─────────────────────
@app.after_request
def add_cors(resp):
    origin = request.headers.get("Origin")
    if origin and ("*" in CORS_ORIGINS or origin in CORS_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = "*" if "*" in CORS_ORIGINS else origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@app.before_request
def preflight():
    if request.method == "OPTIONS":
        return app.make_response(("", 204))


# ───────────────────── sahifalar ─────────────────────
@app.get("/")
def docs():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "docs.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "time": now(), "admin_key_configured": bool(ADMIN_KEY)})


@app.get("/api/auth/check")
def auth_check():
    """Frontend admin kalitini tekshirishi uchun."""
    require_admin()
    return jsonify({"ok": True})


# ───────────────────── TESTS ─────────────────────
@app.get("/api/tests")
def list_tests():
    limit, offset = paging()
    where, params = [], []
    if not is_admin():
        where.append("t.is_published=1")
    elif request.args.get("published") is not None:
        where.append("t.is_published=?")
        params.append(1 if to_bool(request.args["published"]) else 0)
    if request.args.get("section"):
        where.append("t.section=?")
        params.append(request.args["section"].lower())
    if request.args.get("difficulty"):
        where.append("t.difficulty=?")
        params.append(request.args["difficulty"].lower())
    if request.args.get("q"):
        where.append("t.title LIKE ?")
        params.append(f"%{request.args['q']}%")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM tests t {w}", params).fetchone()[0]
    rows = db.execute(
        f"""SELECT t.*, (SELECT COUNT(*) FROM questions q WHERE q.test_id=t.id) AS qc
            FROM tests t {w} ORDER BY t.id DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    ).fetchall()
    return jsonify({"total": total, "limit": limit, "offset": offset,
                    "items": [test_out(r, r["qc"]) for r in rows]})


@app.post("/api/tests")
def create_test():
    require_admin()
    data = body_json()
    t = clean_test(data)
    ts = now()
    db = get_db()
    cur = db.execute(
        """INSERT INTO tests (title, section, difficulty, duration_minutes, description, passage,
           audio_url, is_published, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (t["title"], t["section"], t.get("difficulty", "medium"), t.get("duration_minutes", 60),
         t.get("description", ""), t.get("passage", ""), t.get("audio_url", ""),
         t.get("is_published", 1), ts, ts),
    )
    test_id = cur.lastrowid
    # xohlasangiz test bilan birga savollarni ham yuborish mumkin: "questions": [...]
    qs = data.get("questions") or []
    if not isinstance(qs, list):
        raise ApiError("questions ro'yxat bo'lishi kerak", 422)
    for q in qs:
        insert_question(db, test_id, q)
    db.commit()
    return get_test_detail(test_id, force_admin=True), 201


def get_test_detail(test_id, force_admin=False):
    row = get_test_or_404(test_id)
    admin = force_admin or is_admin()
    qs = get_db().execute("SELECT * FROM questions WHERE test_id=? ORDER BY number, id", (test_id,)).fetchall()
    d = test_out(row, len(qs))
    d["questions"] = [question_out(q, admin) for q in qs]
    return jsonify(d)


@app.get("/api/tests/<int:test_id>")
def get_test(test_id):
    return get_test_detail(test_id)


@app.put("/api/tests/<int:test_id>")
def replace_test(test_id):
    require_admin()
    get_test_or_404(test_id)
    t = clean_test(body_json())
    defaults = {"difficulty": "medium", "duration_minutes": 60, "description": "",
                "passage": "", "audio_url": "", "is_published": 1}
    update_row("tests", test_id, {**defaults, **t})
    get_db().commit()
    return get_test_detail(test_id)


@app.patch("/api/tests/<int:test_id>")
def patch_test(test_id):
    require_admin()
    get_test_or_404(test_id)
    update_row("tests", test_id, clean_test(body_json(), partial=True))
    get_db().commit()
    return get_test_detail(test_id)


@app.delete("/api/tests/<int:test_id>")
def delete_test(test_id):
    require_admin()
    get_test_or_404(test_id)
    get_db().execute("DELETE FROM tests WHERE id=?", (test_id,))
    get_db().commit()
    return jsonify({"deleted": test_id})


# ───────────────────── QUESTIONS ─────────────────────
@app.get("/api/tests/<int:test_id>/questions")
def list_questions(test_id):
    get_test_or_404(test_id)
    rows = get_db().execute("SELECT * FROM questions WHERE test_id=? ORDER BY number, id", (test_id,)).fetchall()
    admin = is_admin()
    return jsonify({"total": len(rows), "items": [question_out(r, admin) for r in rows]})


@app.post("/api/tests/<int:test_id>/questions")
def create_questions(test_id):
    """Bitta savol (obyekt) yoki bir nechta (ro'yxat) yuborish mumkin."""
    require_admin()
    get_test_or_404(test_id)
    data = body_json()
    items = data if isinstance(data, list) else [data]
    if not items:
        raise ApiError("Bo'sh ro'yxat")
    db = get_db()
    ids = [insert_question(db, test_id, q) for q in items]
    db.commit()
    rows = [get_question_or_404(i) for i in ids]
    out = [question_out(r, True) for r in rows]
    return jsonify(out if isinstance(data, list) else out[0]), 201


@app.get("/api/questions/<int:qid>")
def get_question(qid):
    row = get_question_or_404(qid)
    get_test_or_404(row["test_id"])
    return jsonify(question_out(row, is_admin()))


@app.put("/api/questions/<int:qid>")
def replace_question(qid):
    require_admin()
    get_question_or_404(qid)
    q = clean_question(body_json())
    defaults = {"type": "multiple_choice", "options": "[]", "correct_answer": '""', "points": 1}
    fields = {**defaults, **q}
    fields.setdefault("number", get_question_or_404(qid)["number"])
    update_row("questions", qid, fields)
    get_db().commit()
    return jsonify(question_out(get_question_or_404(qid), True))


@app.patch("/api/questions/<int:qid>")
def patch_question(qid):
    require_admin()
    get_question_or_404(qid)
    update_row("questions", qid, clean_question(body_json(), partial=True))
    get_db().commit()
    return jsonify(question_out(get_question_or_404(qid), True))


@app.delete("/api/questions/<int:qid>")
def delete_question(qid):
    require_admin()
    get_question_or_404(qid)
    get_db().execute("DELETE FROM questions WHERE id=?", (qid,))
    get_db().commit()
    return jsonify({"deleted": qid})


# ───────────────────── SUBMIT + RESULTS ─────────────────────
def band_from_ratio(ratio):
    """To'g'ri javoblar ulushini 40 ballik shkalaga o'tkazib, IELTS band beradi."""
    raw = round(ratio * 40)
    table = [(39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0), (27, 6.5), (23, 6.0),
             (19, 5.5), (15, 5.0), (13, 4.5), (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5)]
    for lo, band in table:
        if raw >= lo:
            return band
    return 2.0 if raw >= 2 else (1.0 if raw >= 1 else 0.0)


def is_correct(q, given):
    if given is None:
        return False
    correct = jload(q["correct_answer"], "")
    accepted = correct if isinstance(correct, list) else [correct]
    return norm(given) in {norm(a) for a in accepted}


@app.post("/api/tests/<int:test_id>/submit")
def submit_test(test_id):
    """
    Talaba javoblarini yuboradi (ochiq endpoint).
    Body: {"student_name": "Ali", "answers": {"<question_id>": "B", ...}, "writing_text": "..."}
    """
    test = get_test_or_404(test_id)
    data = body_json()
    answers = data.get("answers") or {}
    if not isinstance(answers, dict):
        raise ApiError("answers obyekt bo'lishi kerak: {savol_id: javob}", 422)
    writing_text = str(data.get("writing_text") or "")
    name = str(data.get("student_name") or "").strip()[:100]
    db = get_db()
    qs = db.execute("SELECT * FROM questions WHERE test_id=? ORDER BY number, id", (test_id,)).fetchall()

    review, got, total = [], 0.0, 0.0
    for q in qs:
        given = answers.get(str(q["id"]))
        ok = is_correct(q, given)
        total += q["points"]
        got += q["points"] if ok else 0
        review.append({"question_id": q["id"], "number": q["number"], "your_answer": given,
                       "correct_answer": jload(q["correct_answer"], ""), "is_correct": ok})

    if test["section"] == "writing":
        if not writing_text.strip():
            raise ApiError("Writing testi uchun writing_text kerak", 422)
        status, band = "pending", None  # o'qituvchi baholaydi (PATCH /api/results/<id>)
    else:
        status = "graded"
        band = band_from_ratio(got / total) if total else None

    ts = now()
    cur = db.execute(
        """INSERT INTO results (test_id, student_name, answers, writing_text, correct_count, total,
           band, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (test_id, name, json.dumps(answers, ensure_ascii=False), writing_text, got, total, band, status, ts),
    )
    db.commit()
    res = result_out(db.execute("SELECT * FROM results WHERE id=?", (cur.lastrowid,)).fetchone())
    res["review"] = review
    return jsonify(res), 201


@app.get("/api/results")
def list_results():
    require_admin()
    limit, offset = paging()
    where, params = [], []
    for arg, col in (("test_id", "test_id"), ("status", "status")):
        if request.args.get(arg):
            where.append(f"{col}=?")
            params.append(request.args[arg])
    if request.args.get("student"):
        where.append("student_name LIKE ?")
        params.append(f"%{request.args['student']}%")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM results {w}", params).fetchone()[0]
    rows = db.execute(f"SELECT * FROM results {w} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
    return jsonify({"total": total, "limit": limit, "offset": offset, "items": [result_out(r) for r in rows]})


def get_result_or_404(rid):
    row = get_db().execute("SELECT * FROM results WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ApiError("Natija topilmadi", 404)
    return row


@app.get("/api/results/<int:rid>")
def get_result(rid):
    require_admin()
    return jsonify(result_out(get_result_or_404(rid)))


@app.patch("/api/results/<int:rid>")
@app.put("/api/results/<int:rid>")
def update_result(rid):
    """O'qituvchi Writing'ni baholaydi: {"band": 6.5, "teacher_comment": "...", "status": "graded"}"""
    require_admin()
    get_result_or_404(rid)
    data = body_json()
    fields, errors = {}, {}
    if "band" in data:
        try:
            b = None if data["band"] is None else float(data["band"])
            if b is not None and not 0 <= b <= 9:
                raise ValueError
            fields["band"] = b
        except (TypeError, ValueError):
            errors["band"] = "0 dan 9 gacha son bo'lsin"
    if "teacher_comment" in data:
        fields["teacher_comment"] = str(data["teacher_comment"] or "")
    if "status" in data:
        if data["status"] not in ("pending", "graded"):
            errors["status"] = "pending yoki graded"
        else:
            fields["status"] = data["status"]
    if errors:
        raise ApiError("Validatsiya xatosi", 422, errors)
    if "band" in fields and fields["band"] is not None and "status" not in fields:
        fields["status"] = "graded"
    if fields:
        cols = ", ".join(f"{k}=?" for k in fields)
        get_db().execute(f"UPDATE results SET {cols} WHERE id=?", (*fields.values(), rid))
        get_db().commit()
    return jsonify(result_out(get_result_or_404(rid)))


@app.delete("/api/results/<int:rid>")
def delete_result(rid):
    require_admin()
    get_result_or_404(rid)
    get_db().execute("DELETE FROM results WHERE id=?", (rid,))
    get_db().commit()
    return jsonify({"deleted": rid})


@app.get("/api/stats")
def stats():
    require_admin()
    db = get_db()
    one = lambda sql: db.execute(sql).fetchone()[0]
    by_section = {r["section"]: r["c"] for r in db.execute("SELECT section, COUNT(*) c FROM tests GROUP BY section")}
    avg = db.execute("SELECT AVG(band) FROM results WHERE band IS NOT NULL").fetchone()[0]
    return jsonify({
        "tests": one("SELECT COUNT(*) FROM tests"),
        "tests_by_section": by_section,
        "questions": one("SELECT COUNT(*) FROM questions"),
        "results": one("SELECT COUNT(*) FROM results"),
        "pending_writing": one("SELECT COUNT(*) FROM results WHERE status='pending'"),
        "average_band": round(avg, 2) if avg is not None else None,
    })


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)

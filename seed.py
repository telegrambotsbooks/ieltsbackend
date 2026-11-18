"""Namuna ma'lumotlar: python seed.py   (faqat baza bo'sh bo'lsa qo'shadi)"""
import json
import sqlite3

import app as backend

backend.init_db()
con = sqlite3.connect(backend.DB_PATH)
if con.execute("SELECT COUNT(*) FROM tests").fetchone()[0]:
    print("Bazada ma'lumot bor, seed o'tkazib yuborildi.")
    raise SystemExit
ts = backend.now()


def add_test(title, section, difficulty, minutes, description, passage="", audio=""):
    cur = con.execute(
        "INSERT INTO tests (title,section,difficulty,duration_minutes,description,passage,audio_url,is_published,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,1,?,?)",
        (title, section, difficulty, minutes, description, passage, audio, ts, ts))
    return cur.lastrowid


def add_q(tid, n, typ, text, options, answer):
    con.execute(
        "INSERT INTO questions (test_id,number,type,text,options,correct_answer,points,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,1,?,?)",
        (tid, n, typ, text, json.dumps(options, ensure_ascii=False), json.dumps(answer, ensure_ascii=False), ts, ts))


t1 = add_test("Reading Practice 1 — Urban Gardens", "reading", "medium", 60,
              "Shahar bog'lari haqida matn",
              "Urban gardening has grown rapidly in the last decade. Rooftop farms now supply restaurants with fresh herbs...")
add_q(t1, 1, "multiple_choice", "What has grown rapidly in the last decade?", ["A) Urban gardening", "B) Rural farming", "C) Fishing", "D) Mining"], "A")
add_q(t1, 2, "true_false_not_given", "Rooftop farms supply restaurants with herbs.", ["True", "False", "Not Given"], "True")
add_q(t1, 3, "fill_blank", "Rooftop farms supply restaurants with fresh ______.", [], ["herbs", "fresh herbs"])

t2 = add_test("Listening Practice 1 — Library Enrolment", "listening", "easy", 30,
              "Kutubxonaga a'zo bo'lish suhbati", "", "https://example.com/audio/listening1.mp3")
add_q(t2, 1, "short_answer", "What is the student's surname?", [], "Karimov")
add_q(t2, 2, "multiple_choice", "Which day does the library close early?", ["A) Monday", "B) Friday", "C) Sunday"], "B")

add_test("Writing Task 2 — Technology in Education", "writing", "hard", 40,
         "Essay yozing (kamida 250 so'z)",
         "Some people think technology has made learning easier, others disagree. Discuss both views and give your opinion.")
con.commit()
print("Namuna ma'lumotlar qo'shildi: 3 ta test.")

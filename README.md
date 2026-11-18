# IELTS Backend (Flask + SQLite)

Frontend (Vue + axios) uchun alohida REST API. Testlar, savollar, natijalar — GET / POST / PUT / PATCH / DELETE.

- Hamma o'qiy oladi (GET), faqat **published** testlar ko'rinadi, to'g'ri javoblar yashirin.
- Yozish/o'zgartirish/o'chirish uchun `X-API-Key: <ADMIN_KEY>` header kerak.
- Talaba javob yuborishi (`POST /api/tests/<id>/submit`) kalitsiz ishlaydi, server avtomatik band hisoblaydi.
- Brauzerda `https://SERVER/` ochsangiz — endpointlar ro'yxati va **sinov oynasi** chiqadi.

## Serverda ishga tushirish (Linux)
```bash
unzip ielts_backend.zip && cd ielts_backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # ADMIN_KEY va CORS_ORIGINS ni o'zgartiring
python seed.py                         # (ixtiyoriy) namunaviy testlar
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```
Doimiy ishlashi uchun systemd: `/etc/systemd/system/ielts.service`
```ini
[Unit]
Description=IELTS API
After=network.target
[Service]
WorkingDirectory=/home/USER/ielts_backend
ExecStart=/home/USER/ielts_backend/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app
Restart=always
User=USER
[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now ielts` — keyin nginx orqali domenga ulang (proxy_pass http://127.0.0.1:8000) va HTTPS qo'ying.

## Render'ga qo'yish
1. Kodni GitHub'ga yuklang (`.env` va `*.db` yuklanmaydi — `.gitignore` da).
2. render.com → New → **Blueprint** → repo'ni tanlang (`render.yaml` avtomatik o'qiladi).
   Yoki qo'lda: New → Web Service: Build `pip install -r requirements.txt`, Start `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`.
3. **Environment**: `ADMIN_KEY` (kuchli kalit), `CORS_ORIGINS` (frontend domeni yoki `*`), `DB_PATH=/data/ielts.db`
4. **Disk** qo'shing: Mount path `/data` (Starter tarif kerak). Free tarifda disk yo'q: baza har deploy va uyg'onishda o'chib ketadi!
5. Health Check Path: `/api/health`. Manzil `https://nom.onrender.com` — frontend `BASE_URL` shu.

## Endpointlar
| Metod | URL | Kalit | Izoh |
|---|---|---|---|
| GET | /api/tests?section=&difficulty=&q=&limit=&offset= | – | Testlar ro'yxati |
| GET | /api/tests/{id} | – | Test + savollar |
| POST | /api/tests | 🔒 | Test yaratish (`questions: [...]` bilan ham) |
| PUT / PATCH | /api/tests/{id} | 🔒 | To'liq / qisman yangilash |
| DELETE | /api/tests/{id} | 🔒 | O'chirish (savollar va natijalari bilan) |
| GET | /api/tests/{id}/questions | – | Savollar |
| POST | /api/tests/{id}/questions | 🔒 | Savol yoki savollar ro'yxati qo'shish |
| GET | /api/questions/{id} | – | Bitta savol |
| PUT / PATCH / DELETE | /api/questions/{id} | 🔒 | Yangilash / o'chirish |
| POST | /api/tests/{id}/submit | – | Javob yuborish → natija + band |
| GET | /api/results, /api/results/{id} | 🔒 | Natijalar |
| PATCH / DELETE | /api/results/{id} | 🔒 | Writing'ni baholash (`band`, `teacher_comment`) / o'chirish |
| GET | /api/stats | 🔒 | Statistika |

`section`: reading / listening / writing · `difficulty`: easy / medium / hard
Savol `type`: multiple_choice, true_false_not_given, fill_blank, short_answer, matching
`correct_answer`: matn yoki qabul qilinadigan variantlar ro'yxati, masalan `["herbs","fresh herbs"]`.

## Frontend
`frontend_example/api.js` ni `src/api.js` ga ko'chiring, `BASE_URL` ga server manzilini yozing, `npm install axios`.
Admin kalitini faqat o'zingiz ishlatadigan admin sahifada `setAdminKey()` bilan bering.

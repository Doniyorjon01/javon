# javon.uz

Kitob do'konlari uchun sayt va Telegram do'kon platformasi. Backend: FastAPI, PostgreSQL 16, Redis.
Kod yozish qoidalari: [CLAUDE.md](CLAUDE.md).

```
main.py  config.py  errors.py  middleware.py  translations.py
routers/  database/  models/  schemas/  services/  auth/  utils/
alembic/  tests/  scripts/postgres-init/
```

## Birinchi ishga tushirish

Kerak bo'ladi: Docker, Python 3.12.

```bash
cp .env.example .env                 # parollarni almashtiring: openssl rand -hex 24
                                     # DATABASE_URL / MIGRATION_DATABASE_URL dagi parollar ham bir xil bo'lsin

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

docker compose up -d --build         # postgres, redis, migratsiyalar va API
```

Tekshirish:

- http://127.0.0.1:8000/health → `{"status":"ok"}`
- http://127.0.0.1:8000/health/ready → baza va Redis holati
- http://127.0.0.1:8000/docs → API hujjati (production'dan tashqari)

To'xtatish: `docker compose down` (ma'lumotlar volume'larda qoladi).

## PyCharm'dan ishga tushirish

API'ni Docker'siz, o'z kompyuteringizda ishga tushirish (debugger bilan):

```bash
docker compose up -d postgres redis  # faqat baza va Redis
alembic upgrade head                 # migratsiyalar (MIGRATION_DATABASE_URL bilan)
uvicorn main:app --reload
```

PyCharm'da interpreter sifatida `.venv/bin/python` ni tanlang; Run configuration: modul `uvicorn`,
parametrlar `main:app --reload`, ishchi papka — loyiha ildizi.

## Kundalik buyruqlar

| Buyruq | Nima qiladi |
| --- | --- |
| `docker compose up -d --build` / `docker compose down` | Stekni ishga tushirish va to'xtatish |
| `docker compose logs -f backend` | Backend loglari |
| `alembic revision --autogenerate -m "..."` | Yangi migratsiya |
| `alembic upgrade head` | Migratsiyalarni qo'llash |
| `python -m scripts.seed_catalog books.csv` | Katalogga kitoblarni CSV'dan yuklash (`--dry-run` bilan avval tekshiring) |
| `ruff check . && ruff format --check .` | Ruff tekshiruvi |
| `ruff check --fix . && ruff format .` | Formatlash |
| `pytest -q` | Testlar |

Postgres init skripti (`scripts/postgres-init/01-roles.sh`) faqat bo'sh volume'da ishlaydi. Rollarni
qaytadan yaratish kerak bo'lsa: `docker compose down -v`. Bu barcha lokal ma'lumotni o'chiradi.

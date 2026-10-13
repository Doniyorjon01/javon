# javon.uz

Kitob do'konlari uchun sayt va Telegram do'kon platformasi. Backend: FastAPI, PostgreSQL 16, Redis,
SeaweedFS (S3 fayl ombori). Kod yozish qoidalari: [CLAUDE.md](CLAUDE.md).

```
main.py  config.py  errors.py  middleware.py  translations.py
routers/  database/  models/  schemas/  services/  auth/  utils/  workers/
alembic/  tests/  scripts/
```

## Servislar (docker compose)

| Servis | Nima qiladi | Kompyuteringizdagi port |
| --- | --- | --- |
| `postgres` | Baza | 5440 |
| `redis` | Kesh, so'rov chegaralari | 6385 |
| `storage` | SeaweedFS: muqova va logolar (S3 API) | 9010 |
| `storage-init` | Bucket yaratadi va ommaviy o'qishga ochadi, keyin to'xtaydi | — |
| `migrate` | `alembic upgrade head`, keyin to'xtaydi | — |
| `backend` | API | 8010 |
| `worker` | Fon vazifalari: Excel import, buyurtma xabarlari | — |

Portlar shu kompyuterdagi boshqa loyihalar (annur, saxovat) bilan to'qnashmaydigan qilib tanlangan.

## Birinchi ishga tushirish

Kerak bo'ladi: Docker, Python 3.12.

```bash
cp .env.example .env                 # parol va kalitlarni almashtiring: openssl rand -hex 24
                                     # DATABASE_URL / MIGRATION_DATABASE_URL dagi parollar ham bir xil bo'lsin

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

docker compose up -d --build         # hamma servislar
docker compose ps                    # migrate va storage-init: Exited (0); qolganlari: healthy / running
```

Tekshirish:

- http://127.0.0.1:8010/health → `{"status":"ok"}`
- http://127.0.0.1:8010/health/ready → baza va Redis holati
- http://127.0.0.1:8010/docs → API hujjati (production'dan tashqari)

To'xtatish: `docker compose down` (ma'lumotlar volume'larda qoladi).

## PyCharm'dan ishga tushirish

API'ni Docker'siz, o'z kompyuteringizda ishga tushirish (debugger bilan):

```bash
docker compose up -d postgres redis storage storage-init   # baza, Redis va fayl ombori
alembic upgrade head                                       # migratsiyalar (MIGRATION_DATABASE_URL bilan)
uvicorn main:app --reload --port 8011
python -m workers.main                                     # boshqa terminalda: fon vazifalari
```

PyCharm'da interpreter sifatida `.venv/bin/python` ni tanlang; Run configuration: modul `uvicorn`,
parametrlar `main:app --reload --port 8011`, ishchi papka — loyiha ildizi.

## Kundalik buyruqlar

| Buyruq | Nima qiladi |
| --- | --- |
| `docker compose up -d --build` / `docker compose down` | Stekni ishga tushirish va to'xtatish |
| `docker compose logs -f backend worker` | Backend va worker loglari |
| `alembic revision --autogenerate -m "..."` | Yangi migratsiya |
| `alembic upgrade head` | Migratsiyalarni qo'llash |
| `python -m scripts.seed_catalog kitoblar.csv` | Katalogga haqiqiy kitoblar ro'yxatini CSV'dan yuklash (`--dry-run` bilan avval tekshiring). CSV fayllar git'ga qo'shilmaydi |
| `python -m scripts.storage_init` | Bucket'ni yaratish va ommaviy o'qishga ochish (qayta ishga tushirsa zarar qilmaydi) |
| `ruff check . && ruff format --check .` | Ruff tekshiruvi |
| `ruff check --fix . && ruff format .` | Formatlash |
| `pytest -q` | Testlar |

Postgres init skripti (`scripts/postgres-init/01-roles.sh`) faqat bo'sh volume'da ishlaydi. Rollarni
qaytadan yaratish kerak bo'lsa: `docker compose down -v`. Bu barcha lokal ma'lumotni o'chiradi.

## Fayl ombori haqida

Muqova va logolar SeaweedFS'da saqlanadi (Apache-2.0, faol rivojlanadi). Dastlabki rejadagi MinIO
2025-yil oktyabridan community versiyasini chiqarmay qo'ydi, 2026-yil aprelda repozitoriysi arxivlandi.
Kod oddiy S3 API (boto3) bilan ishlaydi, shuning uchun omborni sozlamalar orqali almashtirish mumkin.
Bucket ommaviy o'qiladi, lekin ro'yxatini ko'rish, fayl yozish va o'chirish faqat kalit bilan.

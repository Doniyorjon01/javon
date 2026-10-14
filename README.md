# javon.uz

Kitob do'konlari uchun sayt va Telegram do'kon platformasi. Backend: FastAPI, PostgreSQL 16, Redis,
SeaweedFS (S3 fayl ombori). Kod yozish qoidalari: [CLAUDE.md](CLAUDE.md).

```
main.py  config.py  errors.py  middleware.py  translations.py
routers/  database/  models/  schemas/  services/  auth/  utils/  workers/
alembic/  tests/  scripts/  deploy/ (Caddy, zaxira)  .github/workflows/ (CI)
```

## Backend nimalarni qiladi

| Soha | API | Asosiy fayllar |
| --- | --- | --- |
| Kirish | `/auth/*` (Telegram Login Widget, sessiya cookie) | `auth/` |
| Do'kon va sozlash ustasi | `/tenants`, `/tenants/{id}`, `launch`, `logo` | `routers/tenants.py` |
| Katalog va moderatsiya | `/tenants/{id}/catalog/*`, `/system/catalog/*` | `routers/catalog.py` |
| Javon (narx, qoldiq), Excel | `/tenants/{id}/inventory/*` | `routers/inventory.py` |
| Vitrina va buyurtma | `/storefront/{slug}/*` | `routers/storefront.py`, `routers/orders.py` |
| Buyurtmalarni boshqarish, kartaga o'tkazma | `/tenants/{id}/orders/*` | `routers/orders.py` |
| Telegram bot, Mini App | `/tenants/{id}/telegram`, `/telegram/*` | `routers/telegram.py` |
| Obuna va tariflar | `/plans`, `/tenants/{id}/subscription` | `routers/subscription.py` |
| Xodimlar | `/tenants/{id}/staff/*`, `/invites/{token}` | `routers/staff.py` |
| QR va yorliqlar | `/tenants/{id}/qr/*` | `routers/qr.py` |
| Statistika | `/tenants/{id}/stats` | `routers/stats.py` |
| Platforma admini | `/system/*` | `routers/system.py` |

To'liq ro'yxat va sxemalar: `/docs` (production'dan tashqari).

## Servislar (docker compose)

| Servis | Nima qiladi | Kompyuteringizdagi port |
| --- | --- | --- |
| `postgres` | Baza | 5440 |
| `redis` | Kesh, so'rov chegaralari | 6385 |
| `storage` | SeaweedFS: muqova, logolar va to'lov cheklari (S3 API) | 9010 |
| `storage-init` | `javon-media` (ommaviy o'qiladi) va `javon-private` (yopiq, cheklar) bucket'larini yaratadi, keyin to'xtaydi | — |
| `migrate` | `alembic upgrade head`, keyin to'xtaydi | — |
| `backend` | API | 8010 |
| `worker` | Fon vazifalari: Excel import, Telegram xabarlari, to'lanmagan karta buyurtmalarini bekor qilish | — |
| `telegram-poll` | Faqat lokal (`--profile telegram`): do'kon botlari va platforma botining xabarlarini `getUpdates` bilan o'qiydi | — |

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

## Telegram botni lokal sinash

Har do'konning o'z boti bor: egasi @BotFather'da bot yaratib, tokenini admin panelda
(`PUT /tenants/{id}/telegram`) kiritadi. Lokal kompyuterda ommaviy https manzil yo'q, shuning uchun
botlar webhook emas, polling bilan ishlaydi (`TELEGRAM_MODE=polling`, standart):

```bash
docker compose --profile telegram up -d       # telegram-poll servisi ham ishga tushadi
# yoki PyCharm'dan: python -m scripts.telegram_poll
```

Serverda `TELEGRAM_MODE=webhook`, `PUBLIC_API_URL=https://api.javon.uz` va `BOT_TOKEN_KEYS` majburiy;
`telegram-poll` ishga tushirilmaydi. Sinov uchun alohida bot oching: bitta bot bir vaqtda faqat
bitta joyda (webhook yoki polling) ishlaydi.

## PyCharm'dan ishga tushirish

API'ni Docker'siz, o'z kompyuteringizda ishga tushirish (debugger bilan):

```bash
docker compose up -d postgres redis storage storage-init   # baza, Redis va fayl ombori
alembic upgrade head                                       # migratsiyalar (MIGRATION_DATABASE_URL bilan)
uvicorn main:app --reload --port 8011
python -m workers.main                                     # boshqa terminalda: fon vazifalari
python -m scripts.telegram_poll                             # kerak bo'lsa: do'kon botlari (polling)
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
| `python -m scripts.storage_init` | Bucket'larni yaratish: ommaviy `javon-media` va yopiq `javon-private` (qayta ishga tushirsa zarar qilmaydi) |
| `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | `BOT_TOKEN_KEYS` uchun kalit |
| `python -m scripts.platform_bot` | Platforma botini sozlash: serverda webhook, lokalda polling |
| `python -m scripts.backup_files ./backups/files` | Fayllarni bir martalik zaxiralash |
| `ruff check . && ruff format --check .` | Ruff tekshiruvi |
| `ruff check --fix . && ruff format .` | Formatlash |
| `pytest -q` | Testlar |

Postgres init skripti (`scripts/postgres-init/01-roles.sh`) faqat bo'sh volume'da ishlaydi. Rollarni
qaytadan yaratish kerak bo'lsa: `docker compose down -v`. Bu barcha lokal ma'lumotni o'chiradi.

## Serverga chiqarish

Server O'zbekistonda bo'ladi (shaxsiy ma'lumotlar qonuni). Kerak: Docker, 80 va 443 portlar ochiq,
DNS'da `javon.uz`, `www`, `api`, `media` va `*.javon.uz` shu serverga qaragan.

```bash
git clone https://github.com/Doniyorjon01/javon.git && cd javon
cp .env.production.example .env          # hamma qiymatni to'ldiring
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec backend python -m scripts.platform_bot
```

Oxirgi buyruq platforma botining webhook'ini o'rnatadi. Uni bir marta, `SECRET_KEY` yoki domen
o'zgarganda esa yana ishga tushiring. @BotFather'da `/setdomain javon.uz` ham kerak: busiz Login Widget
ishlamaydi.

- **Kirish nuqtasi:** faqat Caddy (`deploy/Caddyfile`). Baza, Redis, fayl ombori va API tashqariga port ochmaydi.
- **HTTPS:** do'kon subdomenlari uchun sertifikat birinchi kirishda olinadi. Caddy oldin
  `/internal/tls-ask` dan "bu bizning do'konmi?" deb so'raydi.
- **Media:** `media.javon.uz` faqat `javon-media` bucket'ini o'qishga beradi. Cheklar turgan
  `javon-private` internetdan umuman ko'rinmaydi.
- **Zaxira:** `backup-db` har kuni `pg_dump` qiladi va uni `./backups/db` ga 14 kun saqlaydi.
  `backup-files` ikkala bucket'ni `./backups/files` ga ko'chiradi. `./backups` papkasini
  O'zbekistondagi ikkinchi serverga ham nusxalang (masalan, `rsync` bilan kuniga bir marta).
- **Tiklash:** `backend` va `worker` ni to'xtating, keyin
  `docker compose -f docker-compose.prod.yml exec backup-db pg_restore -h postgres -U javon_owner -d javon --clean --if-exists /backups/db/<fayl>.dump`.
- **Xatolar:** `SENTRY_DSN` berilsa, xatolar Sentry'ga (yoki GlitchTip'ga) shaxsiy ma'lumotsiz yuboriladi.
- **Loglar:** `docker compose -f docker-compose.prod.yml logs -f backend worker caddy`. Loglar JSON'da,
  har bir servis uchun 5 × 20 MB.
- **Yangilash:** `git pull && docker compose -f docker-compose.prod.yml up -d --build`. Migratsiyalar `migrate`
  servisida o'zi bajariladi.

Frontend (Next.js) keyin `frontend` servisi sifatida qo'shiladi. Ungacha `javon.uz` va do'kon
subdomenlari 502 qaytaradi, `api.javon.uz` esa ishlaydi.

## CI

`.github/workflows/ci.yml` har push va pull request'da ishlaydi:

- ruff;
- PostgreSQL 16 va Redis bilan to'liq testlar;
- `alembic check`;
- Docker image yig'ilishi.

## Fayl ombori haqida

Muqova va logolar SeaweedFS'da saqlanadi (Apache-2.0, faol rivojlanadi). Dastlabki rejadagi MinIO
2025-yil oktyabridan community versiyasini chiqarmay qo'ydi, 2026-yil aprelda repozitoriysi arxivlandi.
Kod oddiy S3 API (boto3) bilan ishlaydi, shuning uchun omborni sozlamalar orqali almashtirish mumkin.
`javon-media` ommaviy o'qiladi, lekin ro'yxatini ko'rish, fayl yozish va o'chirish faqat kalit bilan.
`javon-private` (to'lov cheklari) hech kimga ochiq emas: chekni faqat do'kon xodimi API orqali ko'radi.

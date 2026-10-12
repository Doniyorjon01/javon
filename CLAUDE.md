# javon.uz

## Loyiha

- javon.uz: kitob do'konlari uchun sayt va Telegram do'kon platformasi.
- Stack: Python 3.12, FastAPI, async SQLAlchemy 2 + asyncpg, PostgreSQL 16 (RLS), Redis, Alembic.
- Tuzilma tekis: `app/` papkasi yo'q, hamma modul loyiha ildizida (`from config import settings`,
  `from database.config import get_pg_db`).
- Javoblar o'zbek tilida.
- Har o'zgarishdan keyin: `ruff check . && ruff format --check . && pytest -q`.

## Backend qoidalari

Tuzilma hik-backend'dan olingan. Undagi xatolar bu yerda takrorlanmaydi. Yangi kod yozishdan oldin shu faylni o'qing.

## Qatlamlar

```
main.py         FastAPI ilovasi (create_app, lifespan). uvicorn main:app.
config.py       Sozlamalar (settings, VERSION).
errors.py       Xato formati va handler'lar.
middleware.py   RequestContextMiddleware (request_id, access log) va BodySizeLimitMiddleware (413).
translations.py Msg kodlari va uz/ru/en matnlar.
routers/        HTTP: parametrlar, rol tekshiruvi, javob sxemasi. Biznes mantiq YO'Q.
database/       db_<soha>.py: barcha so'rovlar va o'zgarishlar, commit shu yerda.
models/         SQLAlchemy jadvallari. Har biri BaseModel'dan meros oladi.
schemas/        Pydantic: XBase, XCreate, XUpdate, XOut, XOutFull.
services/       Tashqi xizmatlar (Telegram, fayl ombori, to'lov). Routerlar protobuf yoki
                SDK obyektlariga tegmaydi, faqat oddiy dataclass'lar bilan ishlaydi.
workers/        arq fon vazifalari. Har biri o'z sessiyasini ochadi (SessionLocal()).
auth/           Kirish va rol dependency'lari.
utils/          i18n, pagination, redis_cache, log.
alembic/        Migratsiyalar.
scripts/        Yordamchi skriptlar; postgres-init/ — Postgres rollari (faqat bo'sh volume'da).
tests/          pytest.
```

## Router imzosi

```python
@router.get("/books/{pk}", response_model=BookOut)
async def get_book(
    pk: int,
    db: AsyncSession = Depends(get_pg_db),
    member=Security(get_current_member),  # rol shu yerda
    lang: Lang = Depends(get_lang),
):
    return await db_inventory.get_book(db, member.tenant_id, pk, lang)
```

## Database qatlami

- Nomlar: `create_x`, `get_x`, `get_xs`, `update_x`, `delete_x`.
- `get_xs` `Select` qaytaradi, router uni `await apaginate(db, stmt)` qiladi (`fastapi_pagination.ext.sqlalchemy`; async sessiya uchun `paginate` emas, `apaginate`).
- **Do'konga tegishli har bir funksiya `tenant_id` oladi va u bo'yicha filtrlaydi.** RLS ikkinchi himoya qatlami, birinchisi emas. hik'dagi `get_camera(db, pk)` kabi chegarasiz so'rov yozilmaydi.
- Topilmasa: `raise generate_error(Msg.X_NOT_FOUND, lang, status.HTTP_404_NOT_FOUND)`.
- Update faqat yuborilgan maydonlar bo'yicha: `for k, v in data.model_dump(exclude_unset=True).items(): setattr(obj, k, v)`. `if data.x:` uslubi ishlatilmaydi, chunki u `0`, `False` va bo'sh qiymatni yo'qotadi.
- `XCreate` ichida `tenant_id`, `id`, `status` kabi server belgilaydigan maydonlar bo'lmaydi (mass assignment).
- O'chirish yumshoq (`is_active = False`). Yumshoq o'chiriladigan jadvaldagi noyoblik qisman indeks bilan beriladi: `WHERE is_active`.

## Do'konlar (multi-tenancy) va RLS

- `tenants` va `memberships` platforma jadvallari: RLS yo'q, so'rovlar slug yoki id bo'yicha aniq filtrlanadi.
- Do'konga tegishli har bir yangi jadvalda `tenant_id BIGINT NOT NULL REFERENCES tenants(id)` bo'ladi va migratsiyada `database/rls.py` dagi `enable_tenant_rls("jadval")` chaqiriladi. Downgrade'da `disable_tenant_rls`.
- Route do'konni o'z parametrlaridan emas, dependency'dan oladi: vitrina uchun `auth/tenant.py` dagi `get_storefront_tenant`, admin panel uchun 3-qadamdagi member dependency. Ular sessiyani `bind_tenant(db, tenant_id)` bilan do'konga bog'laydi.
- Bog'lanmagan sessiya do'kon jadvallaridan hech narsa ko'rmaydi (xavfsiz standart). Fon vazifalari `SessionLocal()` ochib, o'zlari `bind_tenant` chaqiradi.
- Vitrina API'si slug bo'yicha: `/storefront/{slug}/...`. Subdomen (`varaq.javon.uz`) ni Next.js shu yo'lga aylantiradi, API `Host` sarlavhasiga ishonmaydi.
- Slug hech qachon bo'shatilmaydi (o'chirilgan do'konniki ham), shuning uchun `uq_tenants_slug` oddiy UNIQUE.
- Bitta akkaunt `users.max_stores` tagacha do'kon ochadi (standart 1, platforma admini `PATCH /system/users/{id}` bilan oshiradi). `create_tenant` foydalanuvchi qatorini `FOR NO KEY UPDATE` bilan qulflab sanaydi, shuning uchun parallel so'rovlar chegaradan o'tolmaydi.
- Vitrina faqat egasi `POST /tenants/{id}/launch` bosgandan keyin ochiladi (`tenants.launched_at`). Ishga tushmagan, to'xtatilgan yoki o'chirilgan do'kon vitrinada "topilmadi" (404) bo'lib ko'rinadi.
- To'xtatilgan (`suspended`) do'kon faqat o'qiladi: `get_current_member` har qanday yozish so'roviga 403 `store_suspended` qaytaradi.
- Relation'lar `lazy="raise"`: kerakli bog'lanish `selectinload` bilan aniq yuklanadi.

## Katalog

- Kitoblar bitta umumiy katalogda (`books`, `authors`, `publishers`, `book_authors`). Platforma jadvallari: RLS yo'q, ko'rinish `database/db_catalog.py` dagi `_visible_to(tenant_id)` bilan aniq filtrlanadi: `approved` hammaga, `pending` faqat qo'shgan do'konga, `rejected` qidiruvda hech kimga. Qo'shgan do'kon rad etilgan kitobini id bo'yicha va `/catalog/submissions` da sababi (`review_note`) bilan ko'radi.
- Bir do'kondan moderatsiya kutayotgan kitoblar soni `MAX_PENDING_BOOKS_PER_STORE` (50) dan oshmaydi. Tekshiruv do'kon qatorini qulflab bajariladi.
- ISBN'siz kitobning takrori `books.dedupe_key` bilan aniqlanadi (`utils/translit.book_dedupe_key`: til, yozuv, sarlavha, mualliflar, nashriyot). Takror 409 `book_duplicate` va mavjud kitobning `book_id` sini qaytaradi. Lotin va kirill nashrlari alohida mahsulot: `books.script` (`latn`/`cyrl`/`other`), berilmasa sarlavhadan aniqlanadi.
- Narx va qoldiq katalogda emas, do'konning zaxirasida (6-qadam).
- ISBN faqat ISBN-13 raqamlari ko'rinishida saqlanadi (`utils/isbn.py`). ISBN-10 avtomatik aylantiriladi. ISBN ixtiyoriy, chunki ko'p o'zbek kitoblarida yo'q.
- `books.search_text` va `books.dedupe_key` ni faqat `db_catalog` yozadi (`_set_derived`). Sarlavha, muallif, nashriyot, ISBN, til yoki yozuv o'zgarsa, qayta hisoblanadi. `utils/translit.py` qoidalari o'zgarsa, migratsiya bilan ikkalasi ham qayta hisoblanadi.
- Qidiruv pg_trgm bilan ishlaydi: `<%` (imlo xatolari) va `LIKE` (qisman so'z), ikkalasi ham GIN indeksidan foydalanadi.
- Enum ustunlar uchun `models/tenant.py` dagi `str_enum()` va `enum_check()` ishlatiladi. `Enum(create_constraint=True)` ishlatilmaydi: autogenerate CHECK'ni takrorlaydi.
- Boshlang'ich katalog: `python -m scripts.seed_catalog kitoblar.csv` (format skript boshida yozilgan). CSV fayllar repoga qo'shilmaydi (`.gitignore`).

## Kirish va rollar

- Kirish Telegram Login Widget orqali: frontend widget ma'lumotini `POST /auth/telegram` ga o'zgartirmasdan yuboradi. Imzo `utils/telegram_auth.py` da tekshiriladi.
- Sessiya server tomonda saqlanadi (`user_sessions`), httpOnly cookie'da tasodifiy token yuradi, bazada faqat SHA-256 xeshi turadi. JWT ishlatilmaydi.
- Route'lar rolni dependency orqali oladi: `get_current_user`, `get_current_member` (yo'ldagi `{tenant_id}` + `bind_tenant`), `get_current_owner`, `get_current_sysadmin` (`auth/oauth2.py`).
- Foydalanuvchi ishlamaydigan do'kon 404 qaytaradi (403 emas): do'kon borligini ham oshkor qilmaymiz.
- CSRF: cookie bilan keladigan har bir POST/PUT/PATCH/DELETE so'rovining `Origin` sarlavhasi `CORS_ORIGINS` ichida bo'lishi shart.
- `/auth/dev-login` faqat `ENV=test` yoki `ENV=local` + `DEBUG=true` da mavjud, boshqa hollarda bu yo'nalish umuman ro'yxatga olinmaydi.
- `ENV` majburiy, standart qiymati yo'q: ENV'siz ishga tushgan server xato beradi.

## So'rov chegaralari

- So'rov tanasi `MAX_REQUEST_BODY_BYTES` (1 MB) dan katta bo'lsa, 413 `payload_too_large`. Fayl yuklash yo'llari o'z chegarasini oladi (5-qadam).
- Yo'l va so'rovdagi har bir id `Path(gt=0, le=BIGINT_MAX)` bilan cheklanadi (`schemas/base.py`): katta son 500 emas, 422 beradi.

## Testlar

- Bazasiz unit testlar har doim ishlaydi. Bazali testlar `pytestmark = pytest.mark.db` bilan belgilanadi va `.env` dagi `TEST_DATABASE_URL`, `TEST_MIGRATION_DATABASE_URL` bo'lmasa o'tkazib yuboriladi.
- Test bazasi nomi `_test` bilan tugashi shart: testlar uni har safar tozalaydi.
- Har bir yangi do'kon jadvali uchun test: boshqa do'konning yozuvi ko'rinmaydi va unga yozib bo'lmaydi.

## Async qoidalari

- Hamma narsa `async def` va `AsyncSession`.
- `async` ichida bloklovchi chaqiruv yo'q: `requests`, `time.sleep`, sinxron fayl yoki tarmoq. Tashqi HTTP `httpx.AsyncClient` orqali, og'ir CPU ishi `asyncio.to_thread` yoki worker'da. Ruff `ASYNC` qoidalari buni tekshiradi.
- Relation'lar `selectinload` bilan oldindan yuklanadi. Async'da lazy load `MissingGreenlet` xatosini beradi.

## Ma'lumot turlari

- Pul: tiyinda, `BIGINT`.
- Vaqt: `DateTime(timezone=True)`, Python'da `datetime.now(UTC)`. Vaqt zonasisiz `datetime.now()` ishlatilmaydi (Ruff `DTZ`).
- Holatlar: `StrEnum` va bazada CHECK yoki enum, erkin matn emas.
- Fayl: bazada URL emas, ombordagi kalit saqlanadi.

## Xatolar va tillar

- Har bir xato `{"detail": {"code", "message"}}` ko'rinishida qaytadi.
- Yangi xabar: `Msg`ga kod qo'shiladi va uch tilda matn yoziladi. Test har bir til borligini va `{}` sonlari tengligini tekshiradi.
- Til `Accept-Language`dan olinadi, standart til o'zbekcha.

## Loglar va shaxsiy ma'lumot

- Logga faqat id'lar yoziladi. Telefon, manzil, ism, bot tokeni va to'lov kaliti logga ham, Sentry'ga ham tushmaydi.
- Har bir log qatorida `request_id` bor.

## Migratsiyalar

- Alembic `javon_owner` roli bilan ishlaydi, API esa `javon_app` roli bilan. `javon_app` hech bir jadvalning egasi emas, shuning uchun RLS doim ishlaydi.
- Bitta o'zgarish uchun bitta migratsiya. Avtomatik yaratilgan faylni har doim o'qib chiqing.
- `lock_timeout = 5s`: qulfni ololmagan migratsiya navbatda kutib qolmasdan xato beradi.

## Yangi soha qo'shish tartibi

1. `models/<soha>.py` va uni `models/__init__.py`ga import qilish.
2. `alembic revision --autogenerate -m "..."` va migratsiyani o'qib chiqish.
3. `schemas/<soha>.py`.
4. `database/db_<soha>.py`.
5. `translations.py`ga yangi `Msg` kodlari.
6. `routers/<soha>.py` va uni `main.py`ga ulash.
7. Testlar: tenant chegarasi (boshqa do'konning yozuvi 404 qaytaradi) va asosiy yo'l.

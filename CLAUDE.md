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
middleware.py   RequestContextMiddleware: request_id va til.
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
- `get_xs` `Select` qaytaradi, router uni `await paginate(db, stmt)` qiladi.
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
- Relation'lar `lazy="raise"`: kerakli bog'lanish `selectinload` bilan aniq yuklanadi.

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

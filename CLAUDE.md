# javon.uz

## Loyiha

- javon.uz: kitob do'konlari uchun sayt va Telegram do'kon platformasi.
- Stack: Python 3.12, FastAPI, async SQLAlchemy 2 + asyncpg, PostgreSQL 16 (RLS), Redis, Alembic,
  SeaweedFS (S3, boto3 orqali), Pillow, openpyxl.
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
middleware.py   RequestContextMiddleware (request_id, access log), BodySizeLimitMiddleware (413),
                StorefrontCORSMiddleware (do'kon subdomenlari uchun cookie'siz CORS).
translations.py Msg kodlari va uz/ru/en matnlar.
routers/        HTTP: parametrlar, rol tekshiruvi, javob sxemasi. Biznes mantiq YO'Q.
database/       db_<soha>.py: barcha so'rovlar va o'zgarishlar, commit shu yerda.
models/         SQLAlchemy jadvallari. Har biri BaseModel'dan meros oladi.
schemas/        Pydantic: XBase, XCreate, XUpdate, XOut, XOutFull.
services/       Tashqi xizmatlar va fayllar: storage.py (S3), media.py (rasm yuklash),
                excel.py (shablon va o'qish), telegram.py (Bot API klienti),
                telegram_updates.py (bot xabarlariga javob), telegram_texts.py (bot matnlari).
                Routerlar SDK obyektlariga tegmaydi.
workers/        Fon vazifalari (`jobs` jadvali): main.py sikl, har vazifa o'z sessiyasida,
                vazifa do'koniga bog'langan (RLS).
auth/           Kirish va rol dependency'lari.
utils/          i18n, pagination, redis_cache, log, images, phone, signing, rate_limit, translit, isbn,
                crypto (bot tokenlari), money (so'm formati), telegram_auth.
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

- Kitoblar bitta umumiy katalogda (`books`, `authors`, `publishers`, `book_authors`). Platforma jadvallari: RLS yo'q, ko'rinish `database/db_catalog.py` dagi `visible_to(tenant_id)` bilan aniq filtrlanadi: `approved` hammaga, `pending` faqat qo'shgan do'konga, `rejected` qidiruvda hech kimga. Qo'shgan do'kon rad etilgan kitobini id bo'yicha va `/catalog/submissions` da sababi (`review_note`) bilan ko'radi.
- Bir do'kondan moderatsiya kutayotgan kitoblar soni `MAX_PENDING_BOOKS_PER_STORE` (50) dan oshmaydi. Tekshiruv do'kon qatorini qulflab bajariladi.
- ISBN'siz kitobning takrori `books.dedupe_key` bilan aniqlanadi (`utils/translit.book_dedupe_key`: til, yozuv, sarlavha, mualliflar, nashriyot). Takror 409 `book_duplicate` va mavjud kitobning `book_id` sini qaytaradi. Lotin va kirill nashrlari alohida mahsulot: `books.script` (`latn`/`cyrl`/`other`), berilmasa sarlavhadan aniqlanadi.
- Narx va qoldiq katalogda emas, do'konning zaxirasida (6-qadam).
- ISBN faqat ISBN-13 raqamlari ko'rinishida saqlanadi (`utils/isbn.py`). ISBN-10 avtomatik aylantiriladi. ISBN ixtiyoriy, chunki ko'p o'zbek kitoblarida yo'q.
- `books.search_text` va `books.dedupe_key` ni faqat `db_catalog` yozadi (`_set_derived`). Sarlavha, muallif, nashriyot, ISBN, til yoki yozuv o'zgarsa, qayta hisoblanadi. `utils/translit.py` qoidalari o'zgarsa, migratsiya bilan ikkalasi ham qayta hisoblanadi.
- Qidiruv pg_trgm bilan ishlaydi: `<%` (imlo xatolari) va `LIKE` (qisman so'z), ikkalasi ham GIN indeksidan foydalanadi.
- Enum ustunlar uchun `models/tenant.py` dagi `str_enum()` va `enum_check()` ishlatiladi. `Enum(create_constraint=True)` ishlatilmaydi: autogenerate CHECK'ni takrorlaydi.
- Boshlang'ich katalog: `python -m scripts.seed_catalog kitoblar.csv` (format skript boshida yozilgan). CSV fayllar repoga qo'shilmaydi (`.gitignore`).

## Fayllar (5-qadam)

- Muqova va logolar S3 bucket'ida (lokal va serverda SeaweedFS). Bazada faqat kalit saqlanadi (`cover_key`, `logo_key`), URL emas; javobdagi URL `STORAGE_PUBLIC_URL` dan yasaladi (`services/media.image_urls`).
- Har bir yuklangan rasm Pillow bilan ochilib, qayta kodlanadi (`utils/images.py`): faqat JPEG/PNG/WebP, EXIF (GPS) o'chiriladi, burilish to'g'rilanadi, WebP o'lchamlari yasaladi, decompression bomb rad etiladi. Asl fayl saqlanmaydi.
- Har yuklash yangi kalit oladi; eski fayllar faqat baza yangi kalitga o'tgandan keyin o'chiriladi. Commit muvaffaqiyatsiz bo'lsa, yangi fayllar o'chiriladi.
- Fayl yuklaydigan yo'llar `main.UPLOAD_PATHS` da: ularga `MAX_UPLOAD_BYTES` (5 MB) chegarasi, qolganlarga 1 MB.
- Testlar MinIO/SeaweedFS'siz ishlaydi: `storage` fixture'i `MemoryStorage`. `S3Storage` `tests/test_storage_s3.py` da haqiqiy S3 protokol serveriga (moto yoki `TEST_S3_ENDPOINT_URL`) qarshi tekshiriladi.

## Fon vazifalari va outbox

- Vazifa `jobs` jadvalidagi qator (`database/db_job.enqueue`). U o'zgarish bilan BITTA tranzaksiyada yoziladi va commit'ni chaqiruvchi qiladi: buyurtma va "do'konga xabar ber" vazifasi birga saqlanadi yoki birga yo'qoladi.
- arq ishlatilmaydi: u redis<6 talab qiladi, bizda redis 8; jadval esa tranzaksion navbat beradi.
- Worker `SELECT ... FOR UPDATE SKIP LOCKED` bilan oladi, xatoda eksponensial kutish bilan qayta urinadi, `max_attempts` dan keyin `failed`. 15 daqiqa `running` qolgan vazifa qayta navbatga qo'yiladi.
- Handler `(db, job)` oladi, sessiya `job.tenant_id` ga bog'langan. Vazifa qayta ishga tushsa ham natija bir xil bo'lishi kerak (idempotent).
- Payload'da faqat id'lar, shaxsiy ma'lumot yo'q.

## Zaxira (6-qadam)

- `inventory_items`: do'konning katalogdagi kitobga narxi (tiyin) va qoldig'i. Do'kon jadvali, RLS.
- Narx, ko'rinish, qo'shish/olib tashlash va import — egasi; qoldiqni xodim ham o'zgartiradi.
- Qoldiq nisbiy o'zgaradi (`/adjust`, `quantity = quantity + :delta WHERE quantity + :delta >= 0`), buyurtmalar bilan poygada yo'qolmaydi. Bazada `CHECK quantity >= 0`.
- Tarif bo'yicha kitoblar soni chegarasi `db_inventory.PLAN_ITEM_LIMITS` (Start 300, Standart 3000, Pro cheksiz); do'kon qatori qulflanib sanaladi.
- Do'kon kamida bitta sotuvdagi kitob bilan ishga tushadi (`launch_needs_books`).
- Excel import: fayl `inventory_imports.file_data` da saqlanadi va worker qatorma-qator qayta ishlaydi (har qator o'z commit'i). Katalogda yo'q kitob `submitted_via = import` bilan moderatsiyaga tushadi va alohida chegaraga ega (`MAX_PENDING_BOOKS_FROM_IMPORT`). Do'konning o'zi rad etilgan kitobi qayta yuborilmaydi. Hisobotdagi xato matnlari yuklagan odam tilida.

## Vitrina (7-qadam)

- `/storefront/{slug}/...` ochiq, faqat ishga tushgan do'kon. Ko'rinadigan qator: faol, `is_visible`, kitob shu do'konga ko'rinadi (`db_storefront.listed`). Qoldiq soni emas, faqat `in_stock` beriladi.
- Do'kon subdomenlari brauzerdan to'g'ridan-to'g'ri chaqiradi: `CORS_ORIGIN_REGEX` faqat `/storefront/*` uchun va hech qachon cookie bilan emas (`StorefrontCORSMiddleware`).

## Buyurtmalar (8-qadam)

- `create_order` bitta tranzaksiya: idempotency kaliti → do'kon qatori qulflanadi va raqam beriladi (`tenants.order_seq`) → zaxira qatorlari id tartibida `FOR UPDATE` → qoldiq tekshiriladi va kamayadi → mijoz (telefon bo'yicha bitta), buyurtma, qatorlar (nom, narx, MXIK nusxasi) va outbox vazifasi → commit.
- Qulf tartibi hamma joyda bir xil: avval `tenants` qatori, keyin zaxira qatorlari (deadlock bo'lmaydi).
- Narxni mijoz yubormaydi, server zaxiradan oladi. Bir IP bir do'konga `ORDER_RATE_LIMIT` dan ko'p buyurtma bera olmaydi (Redis; Redis ishlamasa ruxsat beriladi).
- Kuzatish havolasi: `/storefront/{slug}/orders/{id}?token=` — token `SECRET_KEY` bilan HMAC (`utils/signing.py`), bazada saqlanmaydi. Noto'g'ri token = 404.
- Holatlar `db_order.TRANSITIONS` da; olib ketiladigan buyurtma `shipping` dan o'tmaydi; bekor qilinganda qoldiq qaytadi; naqd buyurtma `completed` bo'lganda `paid`.
- Rollback ORM obyektlarini eskirtiradi: rollback'dan keyin kerak bo'ladigan qiymatni (id, holat) oldindan o'zgaruvchiga oling, aks holda `MissingGreenlet`. Uzoq yashaydigan kontekstda ORM obyekt emas, nusxa (`StoreInfo`, `BotInfo`) saqlanadi; bitta ustunni o'zgartirish `UPDATE ... WHERE id = :id` bilan (`db_telegram.set_group`, `mark_broken`).

## To'lov: kartaga o'tkazma (9-qadam)

- Usullar: `cash` va `card_transfer`. Do'kon sozlamasi: `cash_enabled`, `card_transfer_enabled`, `card_number` (16 raqam), `card_holder`; kamida bittasi yoqilgan bo'lishi shart (bazada CHECK ham bor). Yopiq usul bilan buyurtma 409 `payment_method_unavailable`.
- Holat: `unpaid` → chek yuborildi `under_review` → xodim tasdiqladi `paid` (`paid_at`). Rad etilsa `unpaid` ga qaytadi va `payment_note` da sabab; xaridor yangi chek yuboradi.
- Chek: vitrinadan `POST /storefront/{slug}/orders/{id}/payment-proof?token=` yoki botga rasm. Rasm qayta kodlanadi (`RECEIPT_SPEC`) va YOPIQ bucket'ga (`STORAGE_PRIVATE_BUCKET`, `receipts/{tenant}/{order}/...`) yoziladi. Ko'rish faqat xodimga, API orqali (`GET /tenants/{id}/orders/{id}/payment-proof`, `Cache-Control: private, no-store`). Ommaviy URL yo'q.
- Kartaga to'lanmagan buyurtmani `shipping`/`completed` ga o'tkazib bo'lmaydi (409 `order_not_paid`).
- Chek yuborilmagan karta buyurtmasi oxirgi o'zgarishdan `CARD_TRANSFER_HOLD_HOURS` (24) o'tib avtomatik bekor qilinadi va kitoblar javonga qaytadi (`workers/main.run_periodic_tasks`, har 5 daqiqada). Tekshiruvdagi chek hech qachon avtomatik bekor qilinmaydi.

## Telegram (9-qadam)

- Har do'konning o'z boti (`telegram_bots`, platforma jadvali, RLS yo'q, `tenant_id` bo'yicha aniq filtr). Token `BOT_TOKEN_KEYS` (MultiFernet) bilan shifrlanib saqlanadi (`utils/crypto.py`); token logga, xatoga, javobga tushmaydi.
- aiogram ishlatilmaydi (pydantic<2.14 talab qiladi): `services/telegram.TelegramClient` — httpx ustidagi yupqa klient, token har chaqiruvning argumenti.
- Rejimlar: serverda `TELEGRAM_MODE=webhook` (`POST /telegram/webhook/{bot_user_id}`, `X-Telegram-Bot-Api-Secret-Token` har botning o'z siri bilan solishtiriladi, takror update Redis bilan bir marta ishlanadi, javob doim 200); lokal `polling` (`scripts/telegram_poll.py`).
- Xodimlar guruhi: egasi `group_link_url` orqali botni guruhga qo'shadi; imzolangan kod (`utils/signing.group_link_code`) va qo'shgan odam do'kon xodimi bo'lsagina guruh ulanadi. Guruh supergroup'ga aylansa (`migrate_to_chat_id`) id yangilanadi; bot chiqarib yuborilsa guruh uziladi.
- Guruhdagi tugmalar (qabul qilish, chekni tasdiqlash/rad etish) bosgan odamning do'kon xodimi ekanini `telegram_id` bo'yicha tekshiradi.
- Xaridor: `/start` → Mini App tugmasi; `/start o{id}_{token}` → buyurtma shu Telegram akkauntga bog'lanadi va holat xabarlari keladi. Mini App `X-Telegram-Init-Data` sarlavhasini yuboradi, imzo `utils/telegram_auth.verify_init_data` da (`WebAppData` kaliti) tekshiriladi.
- Shaxsiy ma'lumot: xaridor telefoni va manzili Telegram'ga yuborilmaydi (`TELEGRAM_ORDER_CONTACTS=False`, Telegram serverlari chet elda). Vitrinadan yuklangan chek ham Telegram'ga yuborilmaydi; botga yuborilgan chek guruhga `copyMessage` bilan o'tadi (u allaqachon Telegram'da).
- Xabarlar faqat worker'dan (outbox), so'rov ichidan emas. 401 (token bekor qilingan) → bot `broken`; 400/403 → log; boshqa xato → guruh xabari qayta urinadi.
- Bot matnlari `services/telegram_texts.TEXTS` da, uch tilda; qiymatlar HTML-escape qilinadi (`raw()` faqat o'zimiz yasagan matn uchun).

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
- Har bir yangi do'kon jadvali uchun test: boshqa do'konning yozuvi ko'rinmaydi va unga yozib bo'lmaydi. `tests/test_rls.py::test_every_store_table_has_rls` `tenant_id` ustunli har bir jadvalda RLS va siyosat borligini tekshiradi (ataylab platforma jadvallari ro'yxatda).
- `tests/factories.py`: `make_user`, `make_tenant` (standart holatda ishga tushgan), `make_book` (tasdiqlangan), `make_item` (do'kon javoniga, RLS bilan).
- Poyga holatlari parallel so'rovlar bilan tekshiriladi (`asyncio.gather`): oxirgi nusxa, bir kalitli takror buyurtma, bir kitobni ikki marta qo'shish.

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
- Engine `hide_parameters=True`: SQL xatolari va traceback'larda so'rov parametrlari (telefon, manzil) ko'rinmaydi.
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

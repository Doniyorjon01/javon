"""
User-facing messages
====================
`Msg` value is the stable machine code the frontend switches on; the text is for
people. Never change a code once the frontend uses it — add a new one instead.

`{}` placeholders are filled by generate_error(..., format_values=(...)).
Every language must have the same number of placeholders (tests enforce it).
"""

from enum import StrEnum

from utils.i18n import DEFAULT_LANG, Lang


class Msg(StrEnum):
    # --- generic ------------------------------------------------------------
    UNKNOWN_ERROR = "unknown_error"
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    PAYLOAD_TOO_LARGE = "payload_too_large"

    # --- auth ---------------------------------------------------------------
    INVALID_CREDENTIALS = "invalid_credentials"
    FORBIDDEN = "forbidden"
    TELEGRAM_AUTH_INVALID = "telegram_auth_invalid"
    TELEGRAM_AUTH_EXPIRED = "telegram_auth_expired"
    TELEGRAM_LOGIN_UNAVAILABLE = "telegram_login_unavailable"
    ACCOUNT_DISABLED = "account_disabled"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"
    # --- stores -------------------------------------------------------------
    STORE_NOT_FOUND = "store_not_found"
    SLUG_TAKEN = "slug_taken"
    SLUG_RESERVED = "slug_reserved"
    SLUG_CHECK_EMPTY = "slug_check_empty"
    LOCATION_INCOMPLETE = "location_incomplete"
    STORE_LIMIT_REACHED = "store_limit_reached"
    STORE_SUSPENDED = "store_suspended"
    USER_NOT_FOUND = "user_not_found"

    # --- catalog ------------------------------------------------------------
    BOOK_NOT_FOUND = "book_not_found"
    BOOK_ISBN_NOT_FOUND = "book_isbn_not_found"
    BOOK_ISBN_EXISTS = "book_isbn_exists"
    INVALID_ISBN = "invalid_isbn"
    SEARCH_QUERY_TOO_SHORT = "search_query_too_short"
    BOOK_DUPLICATE = "book_duplicate"
    PENDING_BOOKS_LIMIT = "pending_books_limit"

    # --- files --------------------------------------------------------------
    STORAGE_UNAVAILABLE = "storage_unavailable"
    FILE_EMPTY = "file_empty"
    IMAGE_INVALID = "image_invalid"
    COVER_NOT_ALLOWED = "cover_not_allowed"

    # --- inventory ----------------------------------------------------------
    INVENTORY_ITEM_NOT_FOUND = "inventory_item_not_found"
    INVENTORY_ITEM_EXISTS = "inventory_item_exists"
    STOCK_OUT_OF_RANGE = "stock_out_of_range"
    PLAN_ITEM_LIMIT = "plan_item_limit"
    LAUNCH_NEEDS_BOOKS = "launch_needs_books"
    IMPORT_FILE_INVALID = "import_file_invalid"
    IMPORT_NOT_FOUND = "import_not_found"
    IMPORT_ROW_BAD_PRICE = "import_row_bad_price"
    IMPORT_ROW_BAD_QUANTITY = "import_row_bad_quantity"
    IMPORT_ROW_BOOK_UNKNOWN = "import_row_book_unknown"
    IMPORT_ROW_BOOK_REJECTED = "import_row_book_rejected"
    IMPORT_ROW_INVALID = "import_row_invalid"

    # --- orders -------------------------------------------------------------
    FULFILMENT_REQUIRED = "fulfilment_required"
    DELIVERY_UNAVAILABLE = "delivery_unavailable"
    PICKUP_UNAVAILABLE = "pickup_unavailable"
    ORDER_ITEMS_UNAVAILABLE = "order_items_unavailable"
    OUT_OF_STOCK = "out_of_stock"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    ORDER_NOT_FOUND = "order_not_found"
    ORDER_STATUS_INVALID = "order_status_invalid"
    TOO_MANY_REQUESTS = "too_many_requests"

    # --- payments -----------------------------------------------------------
    PAYMENT_METHOD_UNAVAILABLE = "payment_method_unavailable"
    PAYMENT_OPTION_REQUIRED = "payment_option_required"
    CARD_DETAILS_REQUIRED = "card_details_required"
    ORDER_NOT_PAID = "order_not_paid"
    ORDER_NOT_PAID_IN_TIME = "order_not_paid_in_time"
    PAYMENT_PROOF_NOT_EXPECTED = "payment_proof_not_expected"
    PAYMENT_PROOF_NOT_FOUND = "payment_proof_not_found"
    PAYMENT_NOT_UNDER_REVIEW = "payment_not_under_review"

    # --- telegram -----------------------------------------------------------
    BOT_TOKEN_INVALID = "bot_token_invalid"  # noqa: S105 — a message code
    BOT_IN_USE = "bot_in_use"
    BOT_SETUP_FAILED = "bot_setup_failed"
    BOT_NOT_CONNECTED = "bot_not_connected"
    BOT_GROUP_NOT_LINKED = "bot_group_not_linked"
    TELEGRAM_UNAVAILABLE = "telegram_unavailable"

    # --- subscription and plans ----------------------------------------------
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    PLAN_FEATURE_UNAVAILABLE = "plan_feature_unavailable"
    PAYMENT_NOT_FOUND = "payment_not_found"

    # --- staff ----------------------------------------------------------------
    STAFF_LIMIT_REACHED = "staff_limit_reached"
    TOO_MANY_INVITES = "too_many_invites"
    INVITE_INVALID = "invite_invalid"
    ALREADY_MEMBER = "already_member"
    MEMBER_NOT_FOUND = "member_not_found"
    OWNER_CANNOT_LEAVE = "owner_cannot_leave"

    # --- printables and admin --------------------------------------------------
    LABEL_ITEMS_INVALID = "label_items_invalid"
    JOB_NOT_RETRYABLE = "job_not_retryable"

    # --- validation (422 errors[].type) and store closing -----------------------
    FIELD_REQUIRED = "field_required"
    TOO_SHORT = "text_too_short"
    TOO_LONG = "text_too_long"
    LIST_TOO_SHORT = "list_too_short"
    LIST_TOO_LONG = "list_too_long"
    WRONG_FORMAT = "wrong_format"
    NOT_A_NUMBER = "not_a_number"
    NUMBER_ABOVE = "number_above"
    NUMBER_MIN = "number_min"
    NUMBER_MAX = "number_max"
    NOT_ALLOWED_VALUE = "not_allowed_value"
    UNKNOWN_FIELD = "unknown_field"
    BAD_REQUEST_BODY = "bad_request_body"
    NOT_BOOL = "not_bool"
    BAD_DATE = "bad_date"
    INVALID_VALUE = "invalid_value"
    PHONE_INVALID = "phone_invalid"
    CARD_NUMBER_INVALID = "card_number_invalid"
    ISBN_INVALID = "isbn_invalid"
    ISBN_CHECK_DIGIT = "isbn_check_digit"
    COLOR_INVALID = "color_invalid"
    SLUG_INVALID = "slug_invalid"
    USERNAME_INVALID = "username_invalid"
    PRICE_POSITIVE = "price_positive"
    DUPLICATE_ORDER_LINES = "duplicate_order_lines"
    ADDRESS_REQUIRED = "address_required"
    LOCATION_PAIR = "location_pair"
    REFUSAL_NOTE_REQUIRED = "refusal_note_required"
    NOT_NULL = "not_null"
    HOURS_ORDER = "hours_order"
    LANGUAGES_REPEAT = "languages_repeat"
    TEXT_NEEDS_LETTERS = "text_needs_letters"
    AUTHOR_REPEAT = "author_repeat"
    BOOK_LANGUAGE_INVALID = "book_language_invalid"
    BOOK_SCRIPT_INVALID = "book_script_invalid"
    STORE_HAS_OPEN_ORDERS = "store_has_open_orders"
    STORE_DELETE_CONFIRM = "store_delete_confirm"


MESSAGES: dict[Msg, dict[Lang, str]] = {
    Msg.UNKNOWN_ERROR: {
        Lang.uz: "Nomaʼlum xatolik: {}",
        Lang.ru: "Неизвестная ошибка: {}",
        Lang.en: "Unknown error: {}",
    },
    Msg.INTERNAL_ERROR: {
        Lang.uz: "Serverda kutilmagan xatolik yuz berdi. Birozdan soʻng qayta urinib koʻring.",
        Lang.ru: "На сервере произошла непредвиденная ошибка. Попробуйте чуть позже.",
        Lang.en: "Something went wrong on our side. Please try again shortly.",
    },
    Msg.VALIDATION_ERROR: {
        Lang.uz: "Yuborilgan maʼlumotlarda xato bor.",
        Lang.ru: "В отправленных данных есть ошибка.",
        Lang.en: "The submitted data is invalid.",
    },
    Msg.NOT_FOUND: {
        Lang.uz: "Soʻralgan manzil topilmadi.",
        Lang.ru: "Запрошенный адрес не найден.",
        Lang.en: "The requested resource was not found.",
    },
    Msg.METHOD_NOT_ALLOWED: {
        Lang.uz: "Bu soʻrov usuli qoʻllab-quvvatlanmaydi.",
        Lang.ru: "Этот метод запроса не поддерживается.",
        Lang.en: "This request method is not supported.",
    },
    Msg.SERVICE_UNAVAILABLE: {
        Lang.uz: "Xizmat vaqtincha ishlamayapti.",
        Lang.ru: "Сервис временно недоступен.",
        Lang.en: "The service is temporarily unavailable.",
    },
    Msg.INVALID_CREDENTIALS: {
        Lang.uz: "Tizimga kirish talab qilinadi yoki sessiya yaroqsiz.",
        Lang.ru: "Требуется вход в систему или сессия недействительна.",
        Lang.en: "Sign-in required or the session is invalid.",
    },
    Msg.FORBIDDEN: {
        Lang.uz: "Bu amalni bajarishga ruxsatingiz yoʻq.",
        Lang.ru: "У вас нет прав на это действие.",
        Lang.en: "You are not allowed to do this.",
    },
    Msg.TELEGRAM_AUTH_INVALID: {
        Lang.uz: "Telegram orqali kirish tasdiqlanmadi. Qaytadan urinib koʻring.",
        Lang.ru: "Вход через Telegram не подтверждён. Попробуйте ещё раз.",
        Lang.en: "Telegram sign-in could not be verified. Please try again.",
    },
    Msg.TELEGRAM_AUTH_EXPIRED: {
        Lang.uz: "Kirish havolasining muddati oʻtgan. Telegram orqali qaytadan kiring.",
        Lang.ru: "Срок действия входа истёк. Войдите через Telegram ещё раз.",
        Lang.en: "The sign-in has expired. Please sign in with Telegram again.",
    },
    Msg.TELEGRAM_LOGIN_UNAVAILABLE: {
        Lang.uz: "Telegram orqali kirish hozircha sozlanmagan.",
        Lang.ru: "Вход через Telegram пока не настроен.",
        Lang.en: "Telegram sign-in is not configured yet.",
    },
    Msg.ACCOUNT_DISABLED: {
        Lang.uz: "Hisobingiz bloklangan. Qoʻllab-quvvatlash xizmatiga murojaat qiling.",
        Lang.ru: "Ваш аккаунт заблокирован. Обратитесь в поддержку.",
        Lang.en: "Your account is disabled. Please contact support.",
    },
    Msg.ORIGIN_NOT_ALLOWED: {
        Lang.uz: "Soʻrov ruxsat etilmagan saytdan yuborildi.",
        Lang.ru: "Запрос отправлен с недоверенного сайта.",
        Lang.en: "The request came from a site that is not allowed.",
    },
    Msg.STORE_NOT_FOUND: {
        Lang.uz: "Doʻkon topilmadi.",
        Lang.ru: "Магазин не найден.",
        Lang.en: "Store not found.",
    },
    Msg.SLUG_TAKEN: {
        Lang.uz: "«{}» manzili band. Boshqasini tanlang.",
        Lang.ru: "Адрес «{}» уже занят. Выберите другой.",
        Lang.en: "The address “{}” is taken. Please choose another one.",
    },
    Msg.SLUG_RESERVED: {
        Lang.uz: "«{}» manzilini ishlatib boʻlmaydi. Boshqasini tanlang.",
        Lang.ru: "Адрес «{}» использовать нельзя. Выберите другой.",
        Lang.en: "The address “{}” cannot be used. Please choose another one.",
    },
    Msg.SLUG_CHECK_EMPTY: {
        Lang.uz: "Doʻkon nomini yoki sayt manzilini kiriting.",
        Lang.ru: "Введите название магазина или адрес сайта.",
        Lang.en: "Enter the store name or the site address.",
    },
    Msg.LOCATION_INCOMPLETE: {
        Lang.uz: "Xaritadagi joylashuv toʻliq emas: kenglik va uzunlik birga berilishi kerak.",
        Lang.ru: "Местоположение неполное: широта и долгота указываются вместе.",
        Lang.en: "The location is incomplete: latitude and longitude go together.",
    },
    Msg.BOOK_NOT_FOUND: {
        Lang.uz: "Kitob topilmadi.",
        Lang.ru: "Книга не найдена.",
        Lang.en: "Book not found.",
    },
    Msg.BOOK_ISBN_NOT_FOUND: {
        Lang.uz: "ISBN {} boʻyicha kitob katalogda yoʻq. Uni yangi kitob sifatida qoʻshing.",
        Lang.ru: "Книги с ISBN {} нет в каталоге. Добавьте её как новую книгу.",
        Lang.en: "No book with ISBN {} in the catalog. Add it as a new book.",
    },
    Msg.BOOK_ISBN_EXISTS: {
        Lang.uz: "ISBN {} bilan kitob katalogda allaqachon bor.",
        Lang.ru: "Книга с ISBN {} уже есть в каталоге.",
        Lang.en: "A book with ISBN {} is already in the catalog.",
    },
    Msg.INVALID_ISBN: {
        Lang.uz: "«{}» toʻgʻri ISBN emas. Raqamlarni tekshiring.",
        Lang.ru: "«{}» — неверный ISBN. Проверьте цифры.",
        Lang.en: "“{}” is not a valid ISBN. Check the digits.",
    },
    Msg.SEARCH_QUERY_TOO_SHORT: {
        Lang.uz: "Qidirish uchun kamida 2 ta harf yoki raqam kiriting.",
        Lang.ru: "Для поиска введите хотя бы 2 буквы или цифры.",
        Lang.en: "Enter at least 2 letters or digits to search.",
    },
    Msg.PAYLOAD_TOO_LARGE: {
        Lang.uz: "Yuborilgan maʼlumot juda katta (koʻpi bilan {} KB).",
        Lang.ru: "Слишком большой запрос (не более {} КБ).",
        Lang.en: "The request is too large (at most {} KB).",
    },
    Msg.STORE_LIMIT_REACHED: {
        Lang.uz: (
            "Siz ochishingiz mumkin boʻlgan doʻkonlar soni ({}) toʻldi. "
            "Yana doʻkon kerak boʻlsa, qoʻllab-quvvatlash xizmatiga yozing."
        ),
        Lang.ru: "Достигнут лимит магазинов ({}). Если нужен ещё один, напишите в поддержку.",
        Lang.en: "You have reached your store limit ({}). Contact support if you need another store.",
    },
    Msg.STORE_SUSPENDED: {
        Lang.uz: "Doʻkon toʻxtatilgan. Maʼlumotlarni koʻrish mumkin, oʻzgartirish mumkin emas.",
        Lang.ru: "Магазин приостановлен. Данные можно смотреть, но не изменять.",
        Lang.en: "The store is suspended. You can view its data but not change it.",
    },
    Msg.USER_NOT_FOUND: {
        Lang.uz: "Foydalanuvchi topilmadi.",
        Lang.ru: "Пользователь не найден.",
        Lang.en: "User not found.",
    },
    Msg.BOOK_DUPLICATE: {
        Lang.uz: "Bu kitob katalogda allaqachon bor. Yangisini qoʻshish oʻrniga oʻshani tanlang.",
        Lang.ru: "Эта книга уже есть в каталоге. Выберите её вместо добавления новой.",
        Lang.en: "This book is already in the catalog. Pick it instead of adding a new one.",
    },
    Msg.PENDING_BOOKS_LIMIT: {
        Lang.uz: (
            "Moderatsiyani kutayotgan kitoblaringiz soni chegaraga yetdi ({}). "
            "Ular tekshirilgach, yana qoʻsha olasiz."
        ),
        Lang.ru: "Достигнут лимит книг на модерации ({}). Добавьте новые после проверки этих.",
        Lang.en: (
            "You have reached the limit of books awaiting moderation ({}). Add more once they are reviewed."
        ),
    },
    Msg.STORAGE_UNAVAILABLE: {
        Lang.uz: "Fayl omborini hozir ishlatib boʻlmaydi. Birozdan keyin qayta urinib koʻring.",
        Lang.ru: "Хранилище файлов сейчас недоступно. Попробуйте чуть позже.",
        Lang.en: "File storage is unavailable right now. Please try again shortly.",
    },
    Msg.FILE_EMPTY: {
        Lang.uz: "Fayl boʻsh.",
        Lang.ru: "Файл пустой.",
        Lang.en: "The file is empty.",
    },
    Msg.IMAGE_INVALID: {
        Lang.uz: "Rasmni qabul qilib boʻlmadi. JPEG, PNG yoki WebP formatidagi, juda kichik yoki juda choʻziq boʻlmagan rasm yuklang.",
        Lang.ru: "Не удалось принять изображение. Загрузите JPEG, PNG или WebP не слишком маленького размера и обычных пропорций.",
        Lang.en: "The image could not be accepted. Upload a JPEG, PNG or WebP picture that is not too small or too stretched.",
    },
    Msg.COVER_NOT_ALLOWED: {
        Lang.uz: "Muqovani faqat oʻzingiz qoʻshgan va hali tekshirilmagan kitobga yuklay olasiz.",
        Lang.ru: "Обложку можно загрузить только для добавленной вами книги, пока она на модерации.",
        Lang.en: "You can only upload a cover for a book you added while it is awaiting moderation.",
    },
    Msg.INVENTORY_ITEM_NOT_FOUND: {
        Lang.uz: "Bu kitob doʻkoningizda yoʻq.",
        Lang.ru: "Этой книги нет в вашем магазине.",
        Lang.en: "This book is not in your store.",
    },
    Msg.INVENTORY_ITEM_EXISTS: {
        Lang.uz: "Bu kitob doʻkoningizda allaqachon bor.",
        Lang.ru: "Эта книга уже есть в вашем магазине.",
        Lang.en: "This book is already in your store.",
    },
    Msg.STOCK_OUT_OF_RANGE: {
        Lang.uz: "Qoldiq manfiy boʻlib qoladi yoki juda katta.",
        Lang.ru: "Остаток станет отрицательным или слишком большим.",
        Lang.en: "The stock would go below zero or become too large.",
    },
    Msg.PLAN_ITEM_LIMIT: {
        Lang.uz: "Tarifingiz boʻyicha kitoblar soni toʻldi ({}). Koʻproq kitob uchun tarifni oshiring.",
        Lang.ru: "Достигнут лимит книг по тарифу ({}). Для большего числа книг смените тариф.",
        Lang.en: "Your plan's book limit is reached ({}). Upgrade the plan to add more.",
    },
    Msg.LAUNCH_NEEDS_BOOKS: {
        Lang.uz: "Doʻkonni ishga tushirish uchun kamida bitta kitob sotuvda boʻlishi kerak.",
        Lang.ru: "Чтобы запустить магазин, добавьте в продажу хотя бы одну книгу.",
        Lang.en: "Add at least one book for sale before launching the store.",
    },
    Msg.IMPORT_FILE_INVALID: {
        Lang.uz: "Faylni oʻqib boʻlmadi. Shablon asosidagi .xlsx fayl yuklang: birinchi qatorda ustun nomlari, narx ustuni bilan, koʻpi bilan {} qator.",
        Lang.ru: "Не удалось прочитать файл. Загрузите .xlsx по шаблону: названия столбцов в первой строке, со столбцом цены, не более {} строк.",
        Lang.en: "The file could not be read. Upload an .xlsx made from the template: column names in the first row, a price column, at most {} rows.",
    },
    Msg.IMPORT_NOT_FOUND: {
        Lang.uz: "Import topilmadi.",
        Lang.ru: "Импорт не найден.",
        Lang.en: "Import not found.",
    },
    Msg.IMPORT_ROW_BAD_PRICE: {
        Lang.uz: "Narx notoʻgʻri: soʻmda son yozing, masalan 45000.",
        Lang.ru: "Неверная цена: укажите сумму в сумах, например 45000.",
        Lang.en: "Invalid price: write the amount in so'm, e.g. 45000.",
    },
    Msg.IMPORT_ROW_BAD_QUANTITY: {
        Lang.uz: "Soni notoʻgʻri: 0 yoki undan katta butun son yozing.",
        Lang.ru: "Неверное количество: укажите целое число от 0.",
        Lang.en: "Invalid quantity: write a whole number, 0 or more.",
    },
    Msg.IMPORT_ROW_BOOK_UNKNOWN: {
        Lang.uz: "Kitob katalogda topilmadi. Yangi kitob uchun nomi va muallifini yozing.",
        Lang.ru: "Книга не найдена в каталоге. Для новой книги укажите название и автора.",
        Lang.en: "The book is not in the catalog. For a new book, fill in the title and author.",
    },
    Msg.IMPORT_ROW_BOOK_REJECTED: {
        Lang.uz: "Bu kitob avval rad etilgan: {}",
        Lang.ru: "Эта книга ранее была отклонена: {}",
        Lang.en: "This book was rejected earlier: {}",
    },
    Msg.IMPORT_ROW_INVALID: {
        Lang.uz: "Qatorda xato bor ({} ustuni).",
        Lang.ru: "Ошибка в строке (столбец {}).",
        Lang.en: "The row has an error (column {}).",
    },
    Msg.FULFILMENT_REQUIRED: {
        Lang.uz: "Olib ketish yoki yetkazib berishdan kamida bittasi yoqilgan boʻlishi kerak.",
        Lang.ru: "Должен быть включён самовывоз или доставка.",
        Lang.en: "Turn on pickup, delivery or both.",
    },
    Msg.DELIVERY_UNAVAILABLE: {
        Lang.uz: "Bu doʻkon yetkazib bermaydi.",
        Lang.ru: "Этот магазин не доставляет.",
        Lang.en: "This store does not deliver.",
    },
    Msg.PICKUP_UNAVAILABLE: {
        Lang.uz: "Bu doʻkondan olib ketib boʻlmaydi.",
        Lang.ru: "В этом магазине нет самовывоза.",
        Lang.en: "This store does not offer pickup.",
    },
    Msg.ORDER_ITEMS_UNAVAILABLE: {
        Lang.uz: "Savatdagi baʼzi kitoblar endi sotilmayapti.",
        Lang.ru: "Некоторые книги из корзины больше не продаются.",
        Lang.en: "Some books in the cart are no longer for sale.",
    },
    Msg.OUT_OF_STOCK: {
        Lang.uz: "Baʼzi kitoblar yetarli emas.",
        Lang.ru: "Некоторых книг недостаточно в наличии.",
        Lang.en: "Some books are not available in that quantity.",
    },
    Msg.IDEMPOTENCY_CONFLICT: {
        Lang.uz: "Bu buyurtma boshqa maʼlumot bilan allaqachon yuborilgan. Sahifani yangilab, qayta buyurtma bering.",
        Lang.ru: "Этот заказ уже отправлен с другими данными. Обновите страницу и оформите заказ заново.",
        Lang.en: "This order was already sent with different details. Refresh the page and order again.",
    },
    Msg.ORDER_NOT_FOUND: {
        Lang.uz: "Buyurtma topilmadi.",
        Lang.ru: "Заказ не найден.",
        Lang.en: "Order not found.",
    },
    Msg.ORDER_STATUS_INVALID: {
        Lang.uz: "Buyurtma holatini «{}» dan «{}» ga oʻzgartirib boʻlmaydi.",
        Lang.ru: "Нельзя изменить статус заказа с «{}» на «{}».",
        Lang.en: "The order cannot go from «{}» to «{}».",
    },
    Msg.TOO_MANY_REQUESTS: {
        Lang.uz: "Juda koʻp soʻrov. Birozdan keyin qayta urinib koʻring.",
        Lang.ru: "Слишком много запросов. Попробуйте чуть позже.",
        Lang.en: "Too many requests. Please try again a little later.",
    },
    Msg.PAYMENT_METHOD_UNAVAILABLE: {
        Lang.uz: "Bu doʻkonda bunday toʻlov usuli yoʻq.",
        Lang.ru: "Этот способ оплаты в магазине недоступен.",
        Lang.en: "This store does not accept this payment method.",
    },
    Msg.PAYMENT_OPTION_REQUIRED: {
        Lang.uz: "Naqd yoki kartaga oʻtkazmadan kamida bittasi yoqilgan boʻlishi kerak.",
        Lang.ru: "Должна быть включена оплата наличными или переводом на карту.",
        Lang.en: "Turn on cash, card transfer or both.",
    },
    Msg.CARD_DETAILS_REQUIRED: {
        Lang.uz: "Kartaga oʻtkazma uchun karta raqami va egasining ismini kiriting.",
        Lang.ru: "Для перевода на карту укажите номер карты и имя владельца.",
        Lang.en: "Card transfer needs the card number and the holder's name.",
    },
    Msg.ORDER_NOT_PAID: {
        Lang.uz: "Buyurtma hali toʻlanmagan: avval toʻlovni tasdiqlang.",
        Lang.ru: "Заказ ещё не оплачен: сначала подтвердите оплату.",
        Lang.en: "The order is not paid yet: confirm the payment first.",
    },
    Msg.ORDER_NOT_PAID_IN_TIME: {
        Lang.uz: "Toʻlov oʻz vaqtida qilinmadi.",
        Lang.ru: "Оплата не поступила вовремя.",
        Lang.en: "The payment did not arrive in time.",
    },
    Msg.PAYMENT_PROOF_NOT_EXPECTED: {
        Lang.uz: "Bu buyurtma uchun chek kutilmayapti.",
        Lang.ru: "По этому заказу чек не ожидается.",
        Lang.en: "No receipt is expected for this order.",
    },
    Msg.PAYMENT_PROOF_NOT_FOUND: {
        Lang.uz: "Bu buyurtmaga chek yuborilmagan.",
        Lang.ru: "Чек по этому заказу не отправлялся.",
        Lang.en: "No receipt was sent for this order.",
    },
    Msg.PAYMENT_NOT_UNDER_REVIEW: {
        Lang.uz: "Tekshirilishi kerak boʻlgan chek yoʻq.",
        Lang.ru: "Нет чека, ожидающего проверки.",
        Lang.en: "There is no receipt waiting for review.",
    },
    Msg.BOT_TOKEN_INVALID: {
        Lang.uz: "Bot tokeni notoʻgʻri. Uni @BotFather'dan qayta nusxalang.",
        Lang.ru: "Неверный токен бота. Скопируйте его заново из @BotFather.",
        Lang.en: "The bot token is wrong. Copy it again from @BotFather.",
    },
    Msg.BOT_IN_USE: {
        Lang.uz: "Bu bot boshqa doʻkonga ulangan.",
        Lang.ru: "Этот бот уже подключён к другому магазину.",
        Lang.en: "This bot is already connected to another store.",
    },
    Msg.BOT_SETUP_FAILED: {
        Lang.uz: "Telegram botni sozlashga ruxsat bermadi: {}",
        Lang.ru: "Telegram не позволил настроить бота: {}",
        Lang.en: "Telegram refused to set up the bot: {}",
    },
    Msg.BOT_NOT_CONNECTED: {
        Lang.uz: "Doʻkonga bot ulanmagan.",
        Lang.ru: "К магазину не подключён бот.",
        Lang.en: "No bot is connected to this store.",
    },
    Msg.BOT_GROUP_NOT_LINKED: {
        Lang.uz: "Bot hali guruhga ulanmagan. «Guruhga qoʻshish» havolasidan foydalaning.",
        Lang.ru: "Бот ещё не подключён к группе. Воспользуйтесь ссылкой «Добавить в группу».",
        Lang.en: "The bot is not linked to a group yet. Use the “add to group” link.",
    },
    Msg.TELEGRAM_UNAVAILABLE: {
        Lang.uz: "Telegram hozir javob bermayapti. Birozdan keyin qayta urinib koʻring.",
        Lang.ru: "Telegram сейчас не отвечает. Попробуйте чуть позже.",
        Lang.en: "Telegram is not answering right now. Please try again shortly.",
    },
    Msg.SUBSCRIPTION_EXPIRED: {
        Lang.uz: "Obuna muddati tugagan: doʻkon faqat koʻrish rejimida. Toʻlovdan keyin hammasi qayta ishlaydi.",
        Lang.ru: "Подписка закончилась: магазин доступен только для просмотра. После оплаты всё снова заработает.",
        Lang.en: "The subscription has ended: the store is read-only. Everything works again after payment.",
    },
    Msg.PLAN_FEATURE_UNAVAILABLE: {
        Lang.uz: "Bu imkoniyat joriy tarifingizda yoʻq. Tarifni oʻzgartiring.",
        Lang.ru: "Эта возможность недоступна на вашем тарифе. Смените тариф.",
        Lang.en: "Your plan does not include this feature. Change the plan.",
    },
    Msg.PAYMENT_NOT_FOUND: {
        Lang.uz: "Toʻlov topilmadi.",
        Lang.ru: "Платёж не найден.",
        Lang.en: "Payment not found.",
    },
    Msg.STAFF_LIMIT_REACHED: {
        Lang.uz: "Tarifingizda xodimlar soni {} tagacha. Tarifni oʻzgartiring yoki kimnidir olib tashlang.",
        Lang.ru: "На вашем тарифе до {} сотрудников. Смените тариф или удалите кого-нибудь.",
        Lang.en: "Your plan allows up to {} staff. Change the plan or remove someone.",
    },
    Msg.TOO_MANY_INVITES: {
        Lang.uz: "Ochiq takliflar {} tadan oshmasligi kerak. Eskilarini bekor qiling.",
        Lang.ru: "Открытых приглашений может быть не больше {}. Отмените старые.",
        Lang.en: "At most {} open invites. Revoke old ones first.",
    },
    Msg.INVITE_INVALID: {
        Lang.uz: "Taklif havolasi notoʻgʻri, muddati oʻtgan yoki allaqachon ishlatilgan.",
        Lang.ru: "Ссылка-приглашение неверна, просрочена или уже использована.",
        Lang.en: "The invite link is wrong, expired or already used.",
    },
    Msg.ALREADY_MEMBER: {
        Lang.uz: "Siz bu doʻkonda allaqachon ishlaysiz.",
        Lang.ru: "Вы уже работаете в этом магазине.",
        Lang.en: "You already work in this store.",
    },
    Msg.MEMBER_NOT_FOUND: {
        Lang.uz: "Bu odam doʻkonda ishlamaydi.",
        Lang.ru: "Этот человек не работает в магазине.",
        Lang.en: "This person does not work in the store.",
    },
    Msg.OWNER_CANNOT_LEAVE: {
        Lang.uz: "Doʻkon egasini olib tashlab boʻlmaydi.",
        Lang.ru: "Владельца магазина нельзя удалить.",
        Lang.en: "The store's owner cannot be removed.",
    },
    Msg.LABEL_ITEMS_INVALID: {
        Lang.uz: "Kitoblar roʻyxati notoʻgʻri yoki boʻsh (koʻpi bilan {} ta yorliq).",
        Lang.ru: "Список книг неверен или пуст (не больше {} наклеек).",
        Lang.en: "The book list is wrong or empty (at most {} labels).",
    },
    Msg.JOB_NOT_RETRYABLE: {
        Lang.uz: "Faqat muvaffaqiyatsiz tugagan vazifani qayta ishga tushirish mumkin.",
        Lang.ru: "Повторить можно только задачу, завершившуюся ошибкой.",
        Lang.en: "Only a failed job can be retried.",
    },
    Msg.FIELD_REQUIRED: {
        Lang.uz: "Toʻldirilishi shart.",
        Lang.ru: "Обязательное поле.",
        Lang.en: "This field is required.",
    },
    Msg.TOO_SHORT: {
        Lang.uz: "Kamida {} ta belgi boʻlsin.",
        Lang.ru: "Не короче {} символов.",
        Lang.en: "At least {} characters.",
    },
    Msg.TOO_LONG: {
        Lang.uz: "Koʻpi bilan {} ta belgi boʻlsin.",
        Lang.ru: "Не длиннее {} символов.",
        Lang.en: "At most {} characters.",
    },
    Msg.LIST_TOO_SHORT: {
        Lang.uz: "Kamida {} ta boʻlsin.",
        Lang.ru: "Нужно не меньше {}.",
        Lang.en: "At least {} needed.",
    },
    Msg.LIST_TOO_LONG: {
        Lang.uz: "Koʻpi bilan {} ta boʻlsin.",
        Lang.ru: "Не больше {}.",
        Lang.en: "At most {} allowed.",
    },
    Msg.WRONG_FORMAT: {
        Lang.uz: "Koʻrinishi notoʻgʻri.",
        Lang.ru: "Неверный формат.",
        Lang.en: "Wrong format.",
    },
    Msg.NOT_A_NUMBER: {
        Lang.uz: "Son kiriting.",
        Lang.ru: "Введите число.",
        Lang.en: "Enter a number.",
    },
    Msg.NUMBER_ABOVE: {
        Lang.uz: "{} dan katta boʻlsin.",
        Lang.ru: "Должно быть больше {}.",
        Lang.en: "Must be greater than {}.",
    },
    Msg.NUMBER_MIN: {
        Lang.uz: "Kamida {} boʻlsin.",
        Lang.ru: "Не меньше {}.",
        Lang.en: "At least {}.",
    },
    Msg.NUMBER_MAX: {
        Lang.uz: "Koʻpi bilan {} boʻlsin.",
        Lang.ru: "Не больше {}.",
        Lang.en: "At most {}.",
    },
    Msg.NOT_ALLOWED_VALUE: {
        Lang.uz: "Roʻyxatdagi qiymatlardan birini tanlang.",
        Lang.ru: "Выберите одно из допустимых значений.",
        Lang.en: "Choose one of the allowed values.",
    },
    Msg.UNKNOWN_FIELD: {
        Lang.uz: "Bu maydonni yuborib boʻlmaydi.",
        Lang.ru: "Это поле нельзя передавать.",
        Lang.en: "This field cannot be sent.",
    },
    Msg.BAD_REQUEST_BODY: {
        Lang.uz: "Soʻrov maʼlumotlari buzilgan.",
        Lang.ru: "Данные запроса повреждены.",
        Lang.en: "The request body is malformed.",
    },
    Msg.NOT_BOOL: {
        Lang.uz: "Ha yoki yoʻq boʻlsin.",
        Lang.ru: "Должно быть «да» или «нет».",
        Lang.en: "Must be yes or no.",
    },
    Msg.BAD_DATE: {
        Lang.uz: "Sana yoki vaqt notoʻgʻri.",
        Lang.ru: "Неверная дата или время.",
        Lang.en: "Invalid date or time.",
    },
    Msg.INVALID_VALUE: {
        Lang.uz: "Qiymat notoʻgʻri.",
        Lang.ru: "Неверное значение.",
        Lang.en: "Invalid value.",
    },
    Msg.PHONE_INVALID: {
        Lang.uz: "Telefon raqam notoʻgʻri. Masalan: 90 123 45 67 yoki +998 90 123 45 67.",
        Lang.ru: "Неверный номер телефона. Например: 90 123 45 67 или +998 90 123 45 67.",
        Lang.en: "Invalid phone number. For example: 90 123 45 67 or +998 90 123 45 67.",
    },
    Msg.CARD_NUMBER_INVALID: {
        Lang.uz: "Karta raqami 16 ta raqamdan iborat boʻlsin.",
        Lang.ru: "Номер карты должен состоять из 16 цифр.",
        Lang.en: "The card number must have 16 digits.",
    },
    Msg.ISBN_INVALID: {
        Lang.uz: "ISBN notoʻgʻri: 10 yoki 13 ta raqam boʻlishi kerak (978... yoki 979...). Kitobda ISBN boʻlmasa, maydonni boʻsh qoldiring.",
        Lang.ru: "Неверный ISBN: нужно 10 или 13 цифр (978... или 979...). Если у книги нет ISBN, оставьте поле пустым.",
        Lang.en: "Invalid ISBN: it needs 10 or 13 digits (978... or 979...). If the book has no ISBN, leave the field empty.",
    },
    Msg.ISBN_CHECK_DIGIT: {
        Lang.uz: "ISBNʼning oxirgi (nazorat) raqami mos kelmaydi: bu raqamlar uchun oxirgisi {} boʻlishi kerak. Kitobdagi ISBNʼni qayta tekshiring yoki ISBNʼni boʻsh qoldiring.",
        Lang.ru: "Не совпадает последняя (контрольная) цифра ISBN: для этих цифр она должна быть {}. Проверьте ISBN на книге или оставьте поле пустым.",
        Lang.en: "The ISBN's last (check) digit does not match: for these digits it should be {}. Check the ISBN on the book or leave it empty.",
    },
    Msg.COLOR_INVALID: {
        Lang.uz: "Rang #RRGGBB koʻrinishida boʻlsin, masalan #2B3BD1.",
        Lang.ru: "Цвет в формате #RRGGBB, например #2B3BD1.",
        Lang.en: "Use a #RRGGBB color, e.g. #2B3BD1.",
    },
    Msg.SLUG_INVALID: {
        Lang.uz: "Manzil faqat kichik lotin harflari, raqamlar va chiziqchadan iborat boʻlsin (3–40 belgi).",
        Lang.ru: "Адрес: только строчные латинские буквы, цифры и дефис (3–40 символов).",
        Lang.en: "The address may contain only lowercase Latin letters, digits and hyphens (3–40 characters).",
    },
    Msg.USERNAME_INVALID: {
        Lang.uz: "Username notoʻgʻri: faqat lotin harflari, raqamlar va _.",
        Lang.ru: "Неверный username: только латинские буквы, цифры и _.",
        Lang.en: "Invalid username: Latin letters, digits and _ only.",
    },
    Msg.PRICE_POSITIVE: {
        Lang.uz: "Narx 0 dan katta boʻlsin.",
        Lang.ru: "Цена должна быть больше 0.",
        Lang.en: "The price must be greater than 0.",
    },
    Msg.DUPLICATE_ORDER_LINES: {
        Lang.uz: "Bir kitob savatda bir marta boʻlsin: sonini oʻzgartiring.",
        Lang.ru: "Одна книга — одна строка: измените количество.",
        Lang.en: "List each book once and change its quantity.",
    },
    Msg.ADDRESS_REQUIRED: {
        Lang.uz: "Yetkazib berish uchun manzilni yozing.",
        Lang.ru: "Для доставки укажите адрес.",
        Lang.en: "Enter an address for delivery.",
    },
    Msg.LOCATION_PAIR: {
        Lang.uz: "Kenglik va uzunlik birga kiritiladi.",
        Lang.ru: "Широта и долгота указываются вместе.",
        Lang.en: "Latitude and longitude go together.",
    },
    Msg.REFUSAL_NOTE_REQUIRED: {
        Lang.uz: "Chekni rad etish sababini yozing.",
        Lang.ru: "Напишите причину отказа.",
        Lang.en: "Write why the receipt is refused.",
    },
    Msg.NOT_NULL: {
        Lang.uz: "Boʻsh qoldirib boʻlmaydi.",
        Lang.ru: "Не может быть пустым.",
        Lang.en: "Cannot be empty.",
    },
    Msg.HOURS_ORDER: {
        Lang.uz: "Ochilish vaqti yopilishdan oldin boʻlsin.",
        Lang.ru: "Время открытия должно быть раньше закрытия.",
        Lang.en: "Opening time must be before closing time.",
    },
    Msg.LANGUAGES_REPEAT: {
        Lang.uz: "Tillar takrorlanmasin.",
        Lang.ru: "Языки не должны повторяться.",
        Lang.en: "Languages must not repeat.",
    },
    Msg.TEXT_NEEDS_LETTERS: {
        Lang.uz: "Harf yoki raqam boʻlsin.",
        Lang.ru: "Нужны буквы или цифры.",
        Lang.en: "Must contain letters or digits.",
    },
    Msg.AUTHOR_REPEAT: {
        Lang.uz: "Bir muallif ikki marta yozilgan.",
        Lang.ru: "Один автор указан дважды.",
        Lang.en: "The same author is listed twice.",
    },
    Msg.BOOK_LANGUAGE_INVALID: {
        Lang.uz: "Til notoʻgʻri: oʻzbek (uz), rus (ru), ingliz (en) yoki boshqa (other) deb yozing.",
        Lang.ru: "Неверный язык: напишите узбекский (uz), русский (ru), английский (en) или другой (other).",
        Lang.en: "Unknown language: write Uzbek (uz), Russian (ru), English (en) or other.",
    },
    Msg.BOOK_SCRIPT_INVALID: {
        Lang.uz: "Yozuv notoʻgʻri: lotin (latn) yoki kirill (cyrl) deb yozing, yoki boʻsh qoldiring.",
        Lang.ru: "Неверный алфавит: напишите латиница (latn) или кириллица (cyrl) или оставьте пустым.",
        Lang.en: "Unknown script: write Latin (latn) or Cyrillic (cyrl), or leave it empty.",
    },
    Msg.STORE_HAS_OPEN_ORDERS: {
        Lang.uz: "Doʻkonda {} ta yakunlanmagan buyurtma bor. Avval ularni yakunlang yoki bekor qiling.",
        Lang.ru: "В магазине {} незавершённых заказов. Сначала завершите или отмените их.",
        Lang.en: "The store has {} unfinished orders. Complete or cancel them first.",
    },
    Msg.STORE_DELETE_CONFIRM: {
        Lang.uz: "Tasdiqlash uchun doʻkon manzilini ({}) aynan yozing.",
        Lang.ru: "Для подтверждения введите адрес магазина ({}) точно.",
        Lang.en: "To confirm, type the store address ({}) exactly.",
    },
}


# Field names in validation messages (errors.py): «Telefon: ...».
FIELD_LABELS: dict[str, dict[Lang, str]] = {
    "name": {Lang.uz: "Nomi", Lang.ru: "Название", Lang.en: "Name"},
    "slug": {Lang.uz: "Manzil", Lang.ru: "Адрес", Lang.en: "Address"},
    "phone": {Lang.uz: "Telefon", Lang.ru: "Телефон", Lang.en: "Phone"},
    "address": {Lang.uz: "Manzil", Lang.ru: "Адрес", Lang.en: "Address"},
    "latitude": {Lang.uz: "Kenglik", Lang.ru: "Широта", Lang.en: "Latitude"},
    "longitude": {Lang.uz: "Uzunlik", Lang.ru: "Долгота", Lang.en: "Longitude"},
    "working_hours": {Lang.uz: "Ish vaqti", Lang.ru: "Часы работы", Lang.en: "Working hours"},
    "telegram_username": {Lang.uz: "Telegram", Lang.ru: "Telegram", Lang.en: "Telegram"},
    "instagram_username": {Lang.uz: "Instagram", Lang.ru: "Instagram", Lang.en: "Instagram"},
    "languages": {Lang.uz: "Tillar", Lang.ru: "Языки", Lang.en: "Languages"},
    "theme": {Lang.uz: "Dizayn", Lang.ru: "Дизайн", Lang.en: "Design"},
    "accent_color": {Lang.uz: "Rang", Lang.ru: "Цвет", Lang.en: "Color"},
    "delivery_fee": {Lang.uz: "Yetkazish narxi", Lang.ru: "Стоимость доставки", Lang.en: "Delivery fee"},
    "free_delivery_from": {
        Lang.uz: "Bepul yetkazish chegarasi",
        Lang.ru: "Бесплатная доставка от",
        Lang.en: "Free delivery from",
    },
    "delivery_area": {Lang.uz: "Yetkazish hududi", Lang.ru: "Зона доставки", Lang.en: "Delivery area"},
    "card_number": {Lang.uz: "Karta raqami", Lang.ru: "Номер карты", Lang.en: "Card number"},
    "card_holder": {Lang.uz: "Karta egasi", Lang.ru: "Владелец карты", Lang.en: "Card holder"},
    "isbn": {Lang.uz: "ISBN", Lang.ru: "ISBN", Lang.en: "ISBN"},
    "title": {Lang.uz: "Kitob nomi", Lang.ru: "Название книги", Lang.en: "Title"},
    "subtitle": {Lang.uz: "Qoʻshimcha nom", Lang.ru: "Подзаголовок", Lang.en: "Subtitle"},
    "authors": {Lang.uz: "Mualliflar", Lang.ru: "Авторы", Lang.en: "Authors"},
    "publisher": {Lang.uz: "Nashriyot", Lang.ru: "Издательство", Lang.en: "Publisher"},
    "language": {Lang.uz: "Til", Lang.ru: "Язык", Lang.en: "Language"},
    "script": {Lang.uz: "Yozuv", Lang.ru: "Алфавит", Lang.en: "Script"},
    "published_year": {Lang.uz: "Nashr yili", Lang.ru: "Год издания", Lang.en: "Year"},
    "pages": {Lang.uz: "Sahifalar", Lang.ru: "Страницы", Lang.en: "Pages"},
    "description": {Lang.uz: "Tavsif", Lang.ru: "Описание", Lang.en: "Description"},
    "mxik_code": {Lang.uz: "MXIK", Lang.ru: "ИКПУ", Lang.en: "MXIK"},
    "price": {Lang.uz: "Narx", Lang.ru: "Цена", Lang.en: "Price"},
    "quantity": {Lang.uz: "Soni", Lang.ru: "Количество", Lang.en: "Quantity"},
    "delta": {Lang.uz: "Oʻzgarish", Lang.ru: "Изменение", Lang.en: "Change"},
    "customer_name": {Lang.uz: "Ism", Lang.ru: "Имя", Lang.en: "Name"},
    "comment": {Lang.uz: "Izoh", Lang.ru: "Комментарий", Lang.en: "Comment"},
    "items": {Lang.uz: "Kitoblar", Lang.ru: "Книги", Lang.en: "Books"},
    "note": {Lang.uz: "Izoh", Lang.ru: "Примечание", Lang.en: "Note"},
    "reason": {Lang.uz: "Sabab", Lang.ru: "Причина", Lang.en: "Reason"},
    "token": {Lang.uz: "Token", Lang.ru: "Токен", Lang.en: "Token"},
    "months": {Lang.uz: "Oylar", Lang.ru: "Месяцы", Lang.en: "Months"},
    "amount": {Lang.uz: "Summa", Lang.ru: "Сумма", Lang.en: "Amount"},
    "plan": {Lang.uz: "Tarif", Lang.ru: "Тариф", Lang.en: "Plan"},
    "first_name": {Lang.uz: "Ism", Lang.ru: "Имя", Lang.en: "Name"},
    "file": {Lang.uz: "Fayl", Lang.ru: "Файл", Lang.en: "File"},
    "q": {Lang.uz: "Qidiruv", Lang.ru: "Поиск", Lang.en: "Search"},
}


def translate(msg: Msg, lang: Lang) -> str:
    texts = MESSAGES.get(msg, {})
    return texts.get(lang) or texts.get(DEFAULT_LANG) or texts.get(Lang.en) or msg.value

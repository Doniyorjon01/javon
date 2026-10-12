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
}


def translate(msg: Msg, lang: Lang) -> str:
    texts = MESSAGES.get(msg, {})
    return texts.get(lang) or texts.get(DEFAULT_LANG) or texts.get(Lang.en) or msg.value

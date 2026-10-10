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

    # --- auth ---------------------------------------------------------------
    INVALID_CREDENTIALS = "invalid_credentials"
    FORBIDDEN = "forbidden"


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
}


def translate(msg: Msg, lang: Lang) -> str:
    texts = MESSAGES.get(msg, {})
    return texts.get(lang) or texts.get(DEFAULT_LANG) or texts.get(Lang.en) or msg.value

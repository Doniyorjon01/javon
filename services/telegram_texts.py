"""
Telegram message texts
======================
Messages sent by stores' bots, in uz / ru / en. Separate from translations.py,
which holds API error messages: these are longer, use HTML (parse_mode=HTML)
and are read in a chat.

    text("buyer_status_accepted", Lang.uz, number=12)

Values are HTML-escaped here, so a book title like "<Kitob>" cannot break the
markup or inject links. Every language must have the same {placeholders}
(tests/test_telegram_texts.py checks it).
"""

import html

from utils.i18n import Lang

TEXTS: dict[str, dict[Lang, str]] = {
    # --- the store's group ----------------------------------------------------------
    "group_new_order": {
        Lang.uz: "🆕 <b>Yangi buyurtma #{number}</b>\n{lines}\n\nJami: <b>{total}</b>\n{delivery}\nTo'lov: {payment}\nXaridor: {name}{contacts}",
        Lang.ru: "🆕 <b>Новый заказ #{number}</b>\n{lines}\n\nИтого: <b>{total}</b>\n{delivery}\nОплата: {payment}\nПокупатель: {name}{contacts}",
        Lang.en: "🆕 <b>New order #{number}</b>\n{lines}\n\nTotal: <b>{total}</b>\n{delivery}\nPayment: {payment}\nBuyer: {name}{contacts}",
    },
    "order_line": {
        Lang.uz: "• {title} × {quantity} — {amount}",
        Lang.ru: "• {title} × {quantity} — {amount}",
        Lang.en: "• {title} × {quantity} — {amount}",
    },
    "order_contacts": {
        Lang.uz: "\nTelefon: {phone}\nManzil: {address}",
        Lang.ru: "\nТелефон: {phone}\nАдрес: {address}",
        Lang.en: "\nPhone: {phone}\nAddress: {address}",
    },
    "delivery_pickup": {Lang.uz: "📍 Olib ketadi", Lang.ru: "📍 Самовывоз", Lang.en: "📍 Pickup"},
    "delivery_delivery": {Lang.uz: "🚚 Yetkazib berish", Lang.ru: "🚚 Доставка", Lang.en: "🚚 Delivery"},
    "payment_cash": {Lang.uz: "naqd", Lang.ru: "наличными", Lang.en: "cash"},
    "payment_card_transfer": {
        Lang.uz: "kartaga o'tkazma (chek kutilmoqda)",
        Lang.ru: "перевод на карту (ждём чек)",
        Lang.en: "card transfer (receipt expected)",
    },
    "group_receipt": {
        Lang.uz: "🧾 <b>#{number}</b> buyurtma uchun to'lov cheki keldi. Summa: <b>{total}</b>. Tekshirib, tasdiqlang.",
        Lang.ru: "🧾 Пришёл чек оплаты по заказу <b>#{number}</b>. Сумма: <b>{total}</b>. Проверьте и подтвердите.",
        Lang.en: "🧾 A payment receipt arrived for order <b>#{number}</b>. Amount: <b>{total}</b>. Please check it.",
    },
    "group_receipt_web": {
        Lang.uz: "🧾 <b>#{number}</b> buyurtma uchun saytdan chek yuklandi. Summa: <b>{total}</b>. Chekni panelda ko'ring.",
        Lang.ru: "🧾 Чек по заказу <b>#{number}</b> загружен на сайте. Сумма: <b>{total}</b>. Посмотрите его в панели.",
        Lang.en: "🧾 A receipt for order <b>#{number}</b> was uploaded on the website. Amount: <b>{total}</b>. See it in the panel.",
    },
    "group_payment_done": {
        Lang.uz: "✅ #{number}: to'lov tasdiqlandi ({who}).",
        Lang.ru: "✅ #{number}: оплата подтверждена ({who}).",
        Lang.en: "✅ #{number}: payment confirmed ({who}).",
    },
    "group_payment_refused": {
        Lang.uz: "⚠️ #{number}: chek qabul qilinmadi ({who}).",
        Lang.ru: "⚠️ #{number}: чек не принят ({who}).",
        Lang.en: "⚠️ #{number}: receipt refused ({who}).",
    },
    "group_order_accepted": {
        Lang.uz: "👍 #{number} qabul qilindi ({who}).",
        Lang.ru: "👍 #{number} принят ({who}).",
        Lang.en: "👍 #{number} accepted ({who}).",
    },
    "group_linked": {
        Lang.uz: "✅ Bu guruh <b>{store}</b> do'koniga ulandi. Yangi buyurtmalar va to'lov cheklari shu yerga keladi.",
        Lang.ru: "✅ Эта группа подключена к магазину <b>{store}</b>. Сюда будут приходить новые заказы и чеки.",
        Lang.en: "✅ This group is now connected to <b>{store}</b>. New orders and receipts will arrive here.",
    },
    "group_link_denied": {
        Lang.uz: "Guruhni faqat do'kon egasi yoki xodimi ulay oladi.",
        Lang.ru: "Подключить группу может только владелец или сотрудник магазина.",
        Lang.en: "Only the store's owner or staff can connect a group.",
    },
    "test_message": {
        Lang.uz: "✅ javon: bot va guruh to'g'ri ulangan.",
        Lang.ru: "✅ javon: бот и группа подключены правильно.",
        Lang.en: "✅ javon: the bot and the group are connected.",
    },
    "btn_accept": {Lang.uz: "✅ Qabul qilish", Lang.ru: "✅ Принять", Lang.en: "✅ Accept"},
    "btn_open": {Lang.uz: "Panelda ochish", Lang.ru: "Открыть в панели", Lang.en: "Open in the panel"},
    "btn_pay_ok": {Lang.uz: "✅ To'lov tushdi", Lang.ru: "✅ Оплата пришла", Lang.en: "✅ Payment received"},
    "btn_pay_no": {Lang.uz: "❌ Chek noto'g'ri", Lang.ru: "❌ Чек неверный", Lang.en: "❌ Wrong receipt"},
    "cb_not_member": {
        Lang.uz: "Siz bu do'konda ishlamaysiz.",
        Lang.ru: "Вы не работаете в этом магазине.",
        Lang.en: "You do not work in this store.",
    },
    "cb_done": {Lang.uz: "Bajarildi", Lang.ru: "Готово", Lang.en: "Done"},
    "cb_stale": {
        Lang.uz: "Bu buyurtma allaqachon o'zgargan.",
        Lang.ru: "Этот заказ уже изменён.",
        Lang.en: "This order has already changed.",
    },
    "receipt_refused_note": {
        Lang.uz: "Chek tasdiqlanmadi",
        Lang.ru: "Чек не подтверждён",
        Lang.en: "The receipt was not accepted",
    },
    # --- the buyer ------------------------------------------------------------------
    "buyer_welcome": {
        Lang.uz: "Assalomu alaykum! <b>{store}</b> do'koniga xush kelibsiz. Kitoblarni ko'rish va buyurtma berish uchun pastdagi tugmani bosing.",
        Lang.ru: "Здравствуйте! Добро пожаловать в <b>{store}</b>. Чтобы посмотреть книги и заказать, нажмите кнопку ниже.",
        Lang.en: "Hello! Welcome to <b>{store}</b>. Tap the button below to browse books and order.",
    },
    "btn_open_store": {
        Lang.uz: "📚 Do'konni ochish",
        Lang.ru: "📚 Открыть магазин",
        Lang.en: "📚 Open the store",
    },
    "menu_button": {Lang.uz: "Do'kon", Lang.ru: "Магазин", Lang.en: "Store"},
    "cmd_start": {Lang.uz: "Do'konni ochish", Lang.ru: "Открыть магазин", Lang.en: "Open the store"},
    "buyer_help": {
        Lang.uz: "Buyurtma berish uchun «Do'kon» tugmasini bosing. Karta orqali to'lagan bo'lsangiz, chekni (skrinshot) shu yerga yuboring.",
        Lang.ru: "Чтобы заказать, нажмите кнопку «Магазин». Если вы оплатили переводом, отправьте сюда чек (скриншот).",
        Lang.en: "Tap the «Store» button to order. If you paid by card transfer, send the receipt (screenshot) here.",
    },
    "buyer_order_linked": {
        Lang.uz: "🔔 #{number} buyurtmangiz holati shu yerga yuboriladi.",
        Lang.ru: "🔔 Статус заказа #{number} будет приходить сюда.",
        Lang.en: "🔔 Updates on your order #{number} will arrive here.",
    },
    "buyer_order_created": {
        Lang.uz: "🛒 #{number} buyurtmangiz qabul qilindi. Jami: <b>{total}</b>. Do'kon tez orada bog'lanadi.",
        Lang.ru: "🛒 Ваш заказ #{number} получен. Итого: <b>{total}</b>. Магазин скоро свяжется с вами.",
        Lang.en: "🛒 Your order #{number} was received. Total: <b>{total}</b>. The store will contact you soon.",
    },
    "buyer_pay_instructions": {
        Lang.uz: "💳 <b>{total}</b> ni <code>{card}</code> kartaga ({holder}) o'tkazing va chekni (skrinshot) shu yerga yuboring. {hours} soat ichida to'lanmagan buyurtma bekor qilinadi.",
        Lang.ru: "💳 Переведите <b>{total}</b> на карту <code>{card}</code> ({holder}) и отправьте сюда чек (скриншот). Неоплаченный за {hours} ч заказ отменяется.",
        Lang.en: "💳 Transfer <b>{total}</b> to card <code>{card}</code> ({holder}) and send the receipt (screenshot) here. Unpaid orders are cancelled after {hours} h.",
    },
    "buyer_receipt_received": {
        Lang.uz: "🧾 #{number} uchun chek qabul qilindi. Do'kon tekshirgach xabar beramiz.",
        Lang.ru: "🧾 Чек по заказу #{number} получен. Сообщим, когда магазин его проверит.",
        Lang.en: "🧾 Receipt for #{number} received. We will tell you once the store checks it.",
    },
    "buyer_no_unpaid_order": {
        Lang.uz: "To'lov kutilayotgan buyurtmangiz topilmadi.",
        Lang.ru: "Заказ, ожидающий оплаты, не найден.",
        Lang.en: "No order is waiting for payment.",
    },
    "buyer_bad_receipt_file": {
        Lang.uz: "Chekni rasm (skrinshot) qilib yuboring.",
        Lang.ru: "Отправьте чек картинкой (скриншотом).",
        Lang.en: "Please send the receipt as a picture (screenshot).",
    },
    "buyer_payment_confirmed": {
        Lang.uz: "✅ #{number} to'lovingiz tasdiqlandi. Rahmat!",
        Lang.ru: "✅ Оплата заказа #{number} подтверждена. Спасибо!",
        Lang.en: "✅ Payment for #{number} confirmed. Thank you!",
    },
    "buyer_payment_refused": {
        Lang.uz: "⚠️ #{number} to'lovi tasdiqlanmadi: {reason}. Iltimos, to'g'ri chekni yuboring.",
        Lang.ru: "⚠️ Оплата заказа #{number} не подтверждена: {reason}. Отправьте, пожалуйста, верный чек.",
        Lang.en: "⚠️ Payment for #{number} was not confirmed: {reason}. Please send the correct receipt.",
    },
    "buyer_status_accepted": {
        Lang.uz: "✅ #{number} buyurtmangiz qabul qilindi.",
        Lang.ru: "✅ Ваш заказ #{number} принят.",
        Lang.en: "✅ Your order #{number} was accepted.",
    },
    "buyer_status_shipping": {
        Lang.uz: "🚚 #{number} buyurtmangiz yo'lda.",
        Lang.ru: "🚚 Ваш заказ #{number} в пути.",
        Lang.en: "🚚 Your order #{number} is on its way.",
    },
    "buyer_status_completed": {
        Lang.uz: "📚 #{number} buyurtmangiz topshirildi. Xaridingiz uchun rahmat!",
        Lang.ru: "📚 Заказ #{number} выдан. Спасибо за покупку!",
        Lang.en: "📚 Order #{number} delivered. Thank you for your purchase!",
    },
    "buyer_status_cancelled": {
        Lang.uz: "❌ #{number} buyurtmangiz bekor qilindi. {reason}",
        Lang.ru: "❌ Заказ #{number} отменён. {reason}",
        Lang.en: "❌ Order #{number} was cancelled. {reason}",
    },
}


def text(key: str, lang: Lang, **values: object) -> str:
    """The message in `lang` with HTML-escaped values. Pre-built HTML goes through raw()."""
    template = TEXTS[key].get(lang) or TEXTS[key][Lang.uz]
    return template.format(
        **{name: value if isinstance(value, Raw) else _escape(value) for name, value in values.items()}
    )


class Raw(str):
    """Already-safe HTML (built from escaped parts), inserted as is."""


def raw(value: str) -> Raw:
    return Raw(value)


def _escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def pick_lang(code: str | None, fallback: Lang) -> Lang:
    """A Telegram user's language_code ("ru", "en-US") -> one of ours, else the store's."""
    if code:
        short = code.split("-")[0].lower()
        if short in Lang.__members__:
            return Lang(short)
    return fallback

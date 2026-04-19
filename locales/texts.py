"""
AutoHelp.uz - Internationalization (i18n)
Bilingual support for Uzbek and Russian languages.
"""

# All text strings used in the bot, organized by feature area
TEXTS = {
    # ── Start & Registration ──────────────────────────────────────
    "welcome": {
        "uz": (
            "🚗 <b>AutoHelp.uz</b> ga xush kelibsiz!\n\n"
            "Biz sizga yo'lda yordamga tayyormiz.\n"
            "Tilni tanlang / Выберите язык:"
        ),
        "ru": (
            "🚗 Добро пожаловать в <b>AutoHelp.uz</b>!\n\n"
            "Мы готовы помочь вам на дороге.\n"
            "Tilni tanlang / Выберите язык:"
        ),
    },
    "lang_selected": {
        "uz": "✅ Til tanlandi: O'zbek tili",
        "ru": "✅ Язык выбран: Русский",
    },
    "share_contact": {
        "uz": (
            "📱 Ro'yxatdan o'tish uchun telefon raqamingizni yuboring.\n\n"
            "Pastdagi tugmani bosing 👇"
        ),
        "ru": (
            "📱 Для регистрации отправьте свой номер телефона.\n\n"
            "Нажмите кнопку ниже 👇"
        ),
    },
    "share_contact_button": {
        "uz": "📞 Telefon raqamni yuborish",
        "ru": "📞 Отправить номер телефона",
    },
    "registration_success": {
        "uz": (
            "✅ Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n"
            "Ism: {name}\n"
            "Telefon: {phone}\n\n"
            "Endi buyurtma berishingiz mumkin 👇"
        ),
        "ru": (
            "✅ Регистрация прошла успешно!\n\n"
            "Имя: {name}\n"
            "Телефон: {phone}\n\n"
            "Теперь вы можете создать заявку 👇"
        ),
    },

    # ── Main Menu ─────────────────────────────────────────────────
    "main_menu": {
        "uz": (
            "🏠 <b>Asosiy menyu</b>\n\n"
            "Quyidagidan tanlang:"
        ),
        "ru": (
            "🏠 <b>Главное меню</b>\n\n"
            "Выберите действие:"
        ),
    },
    "btn_new_order": {
        "uz": "🆘 Yordam so'rash",
        "ru": "🆘 Запросить помощь",
    },
    "btn_my_orders": {
        "uz": "📋 Mening buyurtmalarim",
        "ru": "📋 Мои заявки",
    },
    "btn_settings": {
        "uz": "⚙️ Sozlamalar",
        "ru": "⚙️ Настройки",
    },

    # ── Order Creation ────────────────────────────────────────────
    "select_problem": {
        "uz": "❓ <b>Nima muammo?</b>\n\nMuammo turini tanlang:",
        "ru": "❓ <b>Какая проблема?</b>\n\nВыберите тип проблемы:",
    },
    "enter_description": {
        "uz": (
            "📝 Muammoni qisqacha tushuntiring.\n\n"
            "Yoki \"O'tkazib yuborish\" tugmasini bosing."
        ),
        "ru": (
            "📝 Кратко опишите проблему.\n\n"
            "Или нажмите кнопку \"Пропустить\"."
        ),
    },
    "btn_skip": {
        "uz": "⏭ O'tkazib yuborish",
        "ru": "⏭ Пропустить",
    },
    "share_location": {
        "uz": (
            "📍 <b>Joylashuvingizni yuboring</b>\n\n"
            "Pastdagi tugmani bosing 👇"
        ),
        "ru": (
            "📍 <b>Отправьте вашу геолокацию</b>\n\n"
            "Нажмите кнопку ниже 👇"
        ),
    },
    "btn_share_location": {
        "uz": "📍 Joylashuvni yuborish",
        "ru": "📍 Отправить геолокацию",
    },
    "confirm_order": {
        "uz": (
            "📋 <b>Buyurtmani tasdiqlang:</b>\n\n"
            "🔧 Muammo: {problem}\n"
            "📝 Izoh: {description}\n"
            "📍 Joylashuv: yuborildi\n\n"
            "Tasdiqlaysizmi?"
        ),
        "ru": (
            "📋 <b>Подтвердите заявку:</b>\n\n"
            "🔧 Проблема: {problem}\n"
            "📝 Описание: {description}\n"
            "📍 Геолокация: отправлена\n\n"
            "Подтвердить?"
        ),
    },
    "btn_confirm": {
        "uz": "✅ Tasdiqlash",
        "ru": "✅ Подтвердить",
    },
    "btn_cancel": {
        "uz": "❌ Bekor qilish",
        "ru": "❌ Отменить",
    },
    "order_created": {
        "uz": (
            "✅ <b>Buyurtma yaratildi!</b>\n\n"
            "📋 Buyurtma ID: <code>{order_uid}</code>\n"
            "⏳ Dispetcher tez orada javob beradi.\n\n"
            "Buyurtma holatini kuzatib boring 👇"
        ),
        "ru": (
            "✅ <b>Заявка создана!</b>\n\n"
            "📋 ID заявки: <code>{order_uid}</code>\n"
            "⏳ Диспетчер скоро ответит.\n\n"
            "Следите за статусом заявки 👇"
        ),
    },
    "order_cancelled_by_client": {
        "uz": "❌ Buyurtma bekor qilindi.",
        "ru": "❌ Заявка отменена.",
    },

    # ── Order Status Updates (to client) ──────────────────────────
    "status_assigned": {
        "uz": "👨‍🔧 Buyurtmangizga usta tayinlandi. Tez orada javob kutilmoqda.",
        "ru": "👨‍🔧 К вашей заявке назначен мастер. Ожидается ответ.",
    },
    "status_accepted": {
        "uz": "✅ Usta buyurtmangizni qabul qildi! Yo'lga chiqmoqda...",
        "ru": "✅ Мастер принял вашу заявку! Выезжает...",
    },
    "status_on_the_way": {
        "uz": "🚗 Usta yo'lda! Tez orada yetib keladi.",
        "ru": "🚗 Мастер в пути! Скоро будет на месте.",
    },
    "status_arrived": {
        "uz": "📍 Usta yetib keldi!",
        "ru": "📍 Мастер прибыл!",
    },
    "status_in_progress": {
        "uz": "🔧 Ish jarayonida...",
        "ru": "🔧 Работа в процессе...",
    },
    "status_completed": {
        "uz": (
            "✅ <b>Ish tugadi!</b>\n\n"
            "💰 Summa: {amount} so'm\n\n"
            "Iltimos, xizmatni baholang ⭐"
        ),
        "ru": (
            "✅ <b>Работа завершена!</b>\n\n"
            "💰 Сумма: {amount} сум\n\n"
            "Пожалуйста, оцените сервис ⭐"
        ),
    },

    # ── Rating ────────────────────────────────────────────────────
    "rate_service": {
        "uz": "⭐ Xizmatni baholang (1-5):",
        "ru": "⭐ Оцените сервис (1-5):",
    },
    "leave_comment": {
        "uz": "💬 Izoh qoldiring (yoki «O'tkazib yuborish» tugmasini bosing):",
        "ru": "💬 Оставьте комментарий (или нажмите «Пропустить»):",
    },
    "review_thanks": {
        "uz": "🙏 Izohingiz uchun rahmat! Xizmatimizdan foydalanganingizdan mamnunmiz.",
        "ru": "🙏 Спасибо за отзыв! Рады, что вы воспользовались нашим сервисом.",
    },

    # ── Dispatcher ────────────────────────────────────────────────
    "new_order_notification": {
        "uz": (
            "🆕 <b>YANGI BUYURTMA!</b>\n\n"
            "📋 ID: <code>{order_uid}</code>\n"
            "👤 Mijoz: {client_name}\n"
            "📞 Telefon: {client_phone}\n"
            "🔧 Muammo: {problem}\n"
            "📝 Izoh: {description}\n"
            "📍 Joylashuv: <a href=\"{maps_url}\">Xaritada ko'rish</a>\n"
            "🕐 Vaqt: {time}\n\n"
            "Ustani tanlang 👇"
        ),
        "ru": (
            "🆕 <b>НОВАЯ ЗАЯВКА!</b>\n\n"
            "📋 ID: <code>{order_uid}</code>\n"
            "👤 Клиент: {client_name}\n"
            "📞 Телефон: {client_phone}\n"
            "🔧 Проблема: {problem}\n"
            "📝 Описание: {description}\n"
            "📍 Локация: <a href=\"{maps_url}\">Открыть на карте</a>\n"
            "🕐 Время: {time}\n\n"
            "Выберите мастера 👇"
        ),
    },
    "dispatcher_video_prompt": {
        "uz": (
            "🎥 <b>Video xabar yuboring</b>\n\n"
            "Mijozga buyurtma qabul qilinganini tasdiqlash uchun "
            "qisqa dumaloq video yuboring.\n\n"
            "Masalan: «Sizning so'rovingiz qabul qilindi, "
            "ustalarimiz yo'lga chiqmoqda!»"
        ),
        "ru": (
            "🎥 <b>Отправьте видеосообщение</b>\n\n"
            "Отправьте короткое круглое видео для подтверждения "
            "клиенту что заявка принята.\n\n"
            "Например: «Ваш запрос принят, "
            "наши мастера уже выезжают!»"
        ),
    },
    "select_master": {
        "uz": "👨‍🔧 Usta tanlang:",
        "ru": "👨‍🔧 Выберите мастера:",
    },
    "order_assigned_success": {
        "uz": "✅ Buyurtma #{order_uid} ga usta tayinlandi: {master_name}",
        "ru": "✅ Заявке #{order_uid} назначен мастер: {master_name}",
    },
    "sla_alert_assign": {
        "uz": "⚠️ OGOHLANTIRISH: Buyurtma #{order_uid} 5 daqiqadan beri qabul qilinmadi!",
        "ru": "⚠️ ВНИМАНИЕ: Заявка #{order_uid} не принята более 5 минут!",
    },
    "sla_alert_on_the_way": {
        "uz": "⚠️ OGOHLANTIRISH: Buyurtma #{order_uid} — usta 60 daqiqadan beri yo'lda!",
        "ru": "⚠️ ВНИМАНИЕ: Заявка #{order_uid} — мастер в пути более 60 минут!",
    },
    "sla_alert_confirm": {
        "uz": "⚠️ OGOHLANTIRISH: Buyurtma #{order_uid} 15 daqiqadan beri tasdiqlanmagan!",
        "ru": "⚠️ ВНИМАНИЕ: Заявка #{order_uid} не подтверждена более 15 минут!",
    },

    # ── Master ────────────────────────────────────────────────────
    "master_new_order": {
        "uz": (
            "🔔 <b>Yangi buyurtma!</b>\n\n"
            "📋 ID: <code>{order_uid}</code>\n"
            "🔧 Muammo: {problem}\n"
            "📝 Izoh: {description}\n"
            "📍 <a href=\"{maps_url}\">Google Maps</a>\n"
            "📞 Mijoz telefoni: {client_phone}\n\n"
            "Qabul qilasizmi?"
        ),
        "ru": (
            "🔔 <b>Новая заявка!</b>\n\n"
            "📋 ID: <code>{order_uid}</code>\n"
            "🔧 Проблема: {problem}\n"
            "📝 Описание: {description}\n"
            "📍 <a href=\"{maps_url}\">Google Maps</a>\n"
            "📞 Телефон клиента: {client_phone}\n\n"
            "Принять?"
        ),
    },
    "btn_accept_order": {
        "uz": "✅ Qabul qilaman",
        "ru": "✅ Принять",
    },
    "btn_reject_order": {
        "uz": "❌ Rad etaman",
        "ru": "❌ Отклонить",
    },
    "master_status_buttons": {
        "uz": {
            "on_the_way": "🚗 Yo'ldaman",
            "arrived": "📍 Yetib keldim",
            "in_progress": "🔧 Ish boshladim",
            "completed": "✅ Tugatdim",
        },
        "ru": {
            "on_the_way": "🚗 В пути",
            "arrived": "📍 Прибыл",
            "in_progress": "🔧 Начал работу",
            "completed": "✅ Завершил",
        },
    },
    "master_enter_amount": {
        "uz": "💰 Olingan summani kiriting (so'mda):",
        "ru": "💰 Введите полученную сумму (в сумах):",
    },
    "master_video_prompt": {
        "uz": (
            "🎥 <b>Ish natijasi</b>\n\n"
            "Bajarilgan ishni ko'rsatadigan qisqa dumaloq video yuboring."
        ),
        "ru": (
            "🎥 <b>Результат работы</b>\n\n"
            "Отправьте короткое круглое видео с результатом работы."
        ),
    },
    "master_toggle_online": {
        "uz": "🟢 Siz hozir ONLINE holatdasiz",
        "ru": "🟢 Вы сейчас ОНЛАЙН",
    },
    "master_toggle_offline": {
        "uz": "🔴 Siz hozir OFFLINE holatdasiz",
        "ru": "🔴 Вы сейчас ОФФЛАЙН",
    },
    "master_stats": {
        "uz": (
            "📊 <b>Sizning statistikangiz</b>\n\n"
            "📋 Bugungi buyurtmalar: {today}\n"
            "📅 Haftalik: {weekly}\n"
            "📆 Oylik: {monthly}\n"
            "💰 Oylik summa: {monthly_sum} so'm\n"
            "⭐ Reyting: {rating}\n"
        ),
        "ru": (
            "📊 <b>Ваша статистика</b>\n\n"
            "📋 Заявки сегодня: {today}\n"
            "📅 За неделю: {weekly}\n"
            "📆 За месяц: {monthly}\n"
            "💰 Сумма за месяц: {monthly_sum} сум\n"
            "⭐ Рейтинг: {rating}\n"
        ),
    },

    # ── Admin ─────────────────────────────────────────────────────
    "admin_dashboard": {
        "uz": (
            "📊 <b>Admin Panel</b>\n\n"
            "📋 Bugungi buyurtmalar: {today_orders}\n"
            "📅 Oylik buyurtmalar: {monthly_orders}\n"
            "💰 Bugungi summa: {today_sum} so'm\n"
            "💰 Oylik summa: {monthly_sum} so'm\n"
            "⭐ O'rtacha reyting: {avg_rating}\n"
            "👨‍🔧 Online ustalar: {online_masters}\n"
        ),
        "ru": (
            "📊 <b>Панель администратора</b>\n\n"
            "📋 Заявки сегодня: {today_orders}\n"
            "📅 Заявки за месяц: {monthly_orders}\n"
            "💰 Сумма сегодня: {today_sum} сум\n"
            "💰 Сумма за месяц: {monthly_sum} сум\n"
            "⭐ Средний рейтинг: {avg_rating}\n"
            "👨‍🔧 Мастера онлайн: {online_masters}\n"
        ),
    },

    # ── Common ────────────────────────────────────────────────────
    "error": {
        "uz": "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
        "ru": "❌ Произошла ошибка. Пожалуйста, попробуйте снова.",
    },
    "no_permission": {
        "uz": "⛔️ Sizda bu amalni bajarish uchun ruxsat yo'q.",
        "ru": "⛔️ У вас нет разрешения для выполнения этого действия.",
    },
    "no_description": {
        "uz": "—",
        "ru": "—",
    },
}


def t(key: str, lang: str = "uz", **kwargs) -> str:
    """
    Get translated text by key and language.

    Args:
        key: Text key from TEXTS dictionary
        lang: Language code ('uz' or 'ru')
        **kwargs: Format parameters for the text

    Returns:
        Formatted translated string
    """
    text_entry = TEXTS.get(key, {})
    text = text_entry.get(lang, text_entry.get("uz", f"[Missing: {key}]"))

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass

    return text

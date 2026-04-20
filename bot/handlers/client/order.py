"""
AutoHelp.uz - Client Order Handler
Full order creation flow with crystal-clear UX.
Step 1: Problem type → Step 2: Description → Step 3: Location → Step 4: Confirm
"""
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.client_states import OrderCreationStates
from bot.keyboards.client_kb import (
    problem_type_keyboard, share_location_keyboard,
    confirm_order_keyboard, main_menu_keyboard, cancel_order_keyboard,
)
from locales.texts import t
from models.order import ProblemType, PROBLEM_LABELS
from models.user import User
from services.order_service import OrderService
from services.notification_service import NotificationService
from repositories.user_repo import UserRepo
from repositories.order_repo import OrderRepo
from repositories.order_draft_repo import OrderDraftRepo

router = Router(name="client_order")

# Problem types that REQUIRE description
REQUIRES_DESCRIPTION = {ProblemType.OTHER}


def _step_header(step: int, total: int = 4, lang: str = "uz") -> str:
    """Adds a clear step indicator."""
    steps_uz = ["🔧 Muammo turi", "📝 Tavsif", "📍 Joylashuv", "✅ Tasdiqlash"]
    steps_ru = ["🔧 Тип проблемы", "📝 Описание", "📍 Местоположение", "✅ Подтверждение"]
    steps = steps_uz if lang == "uz" else steps_ru
    progress = "●" * step + "○" * (total - step)
    return f"<code>{progress}</code>  {steps[step-1]}  [{step}/{total}]\n{'─'*28}\n"


async def _touch_order_draft(
    session: AsyncSession,
    telegram_id: int,
    user_data: User | None,
    user_lang: str,
    state_name: str | None,
):
    """Mark unfinished order-flow activity for reminder logic."""
    draft_repo = OrderDraftRepo(session)
    await draft_repo.touch(
        telegram_id=telegram_id,
        user_id=user_data.id if user_data else None,
        language=user_lang,
        fsm_state=state_name,
    )


async def _clear_order_draft(session: AsyncSession, telegram_id: int):
    """Clear unfinished order-flow reminder tracking."""
    draft_repo = OrderDraftRepo(session)
    await draft_repo.clear(telegram_id)


# ── Trigger ───────────────────────────────────────────────────────

@router.message(F.text.in_(["🆘 Yordam so'rash", "🆘 Запросить помощь"]))
async def start_order(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_lang: str = "uz",
    user_data: User | None = None,
):
    """Start the order creation flow."""
    if not user_data:
        await message.answer(t("not_registered", user_lang), parse_mode="HTML")
        return

    # Check if user already has an active order
    order_repo = OrderRepo(session)
    active_list = await order_repo.get_active_by_user(user_data.id)
    active = active_list[0] if active_list else None
    if active:
        await _clear_order_draft(session, message.from_user.id)
        already_uz = (
            f"⚠️ Sizda allaqachon faol buyurtma mavjud!\n\n"
            f"📋 Buyurtma: <code>{active.order_uid}</code>\n"
            f"📌 Holat: {active.status.value}\n\n"
            f"Yangi buyurtma berish uchun avvalgi buyurtmani yakunlang."
        )
        already_ru = (
            f"⚠️ У вас уже есть активная заявка!\n\n"
            f"📋 Заявка: <code>{active.order_uid}</code>\n"
            f"📌 Статус: {active.status.value}\n\n"
            f"Чтобы создать новую, дождитесь завершения текущей."
        )
        await message.answer(
            already_uz if user_lang == "uz" else already_ru,
            parse_mode="HTML",
            reply_markup=cancel_order_keyboard(active.order_uid, user_lang),
        )
        return

    text = _step_header(1, lang=user_lang)
    if user_lang == "uz":
        text += "Muammoingizni tanlang 👇"
    else:
        text += "Выберите тип проблемы 👇"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=problem_type_keyboard(user_lang),
    )
    await state.set_state(OrderCreationStates.selecting_problem)
    await _touch_order_draft(
        session=session,
        telegram_id=message.from_user.id,
        user_data=user_data,
        user_lang=user_lang,
        state_name=OrderCreationStates.selecting_problem.state,
    )


# ── Step 1: Problem type ──────────────────────────────────────────

@router.callback_query(
    OrderCreationStates.selecting_problem,
    F.data.startswith("problem:"),
)
async def process_problem_type(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Handle problem type selection."""
    problem_value = callback.data.split(":")[1]
    await callback.answer()
    await state.update_data(problem_type=problem_value)

    problem_type = ProblemType(problem_value)
    problem_label = PROBLEM_LABELS[problem_type][user_lang]

    # Step 2 header
    text = _step_header(2, lang=user_lang)

    if problem_type == ProblemType.OTHER:
        # "Boshqa muammo" → REQUIRED to type description
        if user_lang == "uz":
            text += (
                f"✅ Tanlandi: {problem_label}\n\n"
                "📝 <b>Muammoni batafsil yozing</b>\n\n"
                "Masalan: <i>«Dvigatel qizib ketdi», «Yoqilg'i tugadi», «Eshik ochildi»</i>\n\n"
                "Quyida xabar yuboring 👇"
            )
        else:
            text += (
                f"✅ Выбрано: {problem_label}\n\n"
                "📝 <b>Опишите проблему подробней</b>\n\n"
                "Например: <i>«Перегрелся двигатель», «Кончилось топливо»</i>\n\n"
                "Напишите сообщение ниже 👇"
            )
        await callback.message.edit_text(text, parse_mode="HTML")
        await state.set_state(OrderCreationStates.entering_description)
        await _touch_order_draft(
            session=session,
            telegram_id=callback.from_user.id,
            user_data=user_data,
            user_lang=user_lang,
            state_name=OrderCreationStates.entering_description.state,
        )
    else:
        # Known problem → description is optional
        if user_lang == "uz":
            text += (
                f"✅ Tanlandi: {problem_label}\n\n"
                "📝 Qo'shimcha izoh yozishingiz mumkin (ixtiyoriy)\n"
                "Yoki to'g'ridan-to'g'ri <b>joylashuvni yuboring</b>\n\n"
                "👉 Quyidagi «📍 Joylashuvni yuborish» tugmasini bosing"
            )
        else:
            text += (
                f"✅ Выбрано: {problem_label}\n\n"
                "📝 Можете добавить комментарий (необязательно)\n"
                "Или сразу <b>отправьте геолокацию</b>\n\n"
                "👉 Нажмите кнопку «📍 Отправить геолокацию» ниже"
            )
        await callback.message.edit_text(text, parse_mode="HTML")
        # For known problems go straight to location step
        await state.set_state(OrderCreationStates.sharing_location)
        await _touch_order_draft(
            session=session,
            telegram_id=callback.from_user.id,
            user_data=user_data,
            user_lang=user_lang,
            state_name=OrderCreationStates.sharing_location.state,
        )
        await callback.message.answer(
            t("share_location", user_lang),
            parse_mode="HTML",
            reply_markup=share_location_keyboard(user_lang),
        )


# ── Step 2: Description (REQUIRED for OTHER, collected then go to location) ─

@router.message(OrderCreationStates.entering_description, F.text)
async def process_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Handle typed description."""
    if len(message.text.strip()) < 3:
        too_short = (
            "❗️ Iltimos, muammoni batafsilroq yozing (kamida 3 ta harf)."
            if user_lang == "uz" else
            "❗️ Пожалуйста, опишите проблему подробнее (минимум 3 символа)."
        )
        await message.answer(too_short)
        return

    await state.update_data(description=message.text.strip())

    # Now go to location
    text = _step_header(3, lang=user_lang)
    if user_lang == "uz":
        text += (
            "📍 <b>Joylashuvingizni yuboring</b>\n\n"
            "Quyidagi tugmani bosing → telefon GPS lokatsiyangizni yuboradi.\n\n"
            "⚠️ <i>Aniq joy muhim — usta sizni tezroq topadi!</i>"
        )
    else:
        text += (
            "📍 <b>Отправьте вашу геолокацию</b>\n\n"
            "Нажмите кнопку ниже → телефон отправит GPS координаты.\n\n"
            "⚠️ <i>Точное место важно — мастер найдёт вас быстрее!</i>"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=share_location_keyboard(user_lang),
    )
    await state.set_state(OrderCreationStates.sharing_location)
    await _touch_order_draft(
        session=session,
        telegram_id=message.from_user.id,
        user_data=user_data,
        user_lang=user_lang,
        state_name=OrderCreationStates.sharing_location.state,
    )


# ── Step 3: Location ──────────────────────────────────────────────

@router.message(OrderCreationStates.sharing_location, F.location)
async def process_location(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Handle location sharing."""
    location = message.location
    await state.update_data(
        latitude=location.latitude,
        longitude=location.longitude,
    )

    data = await state.get_data()
    problem_type = ProblemType(data["problem_type"])
    problem_label = PROBLEM_LABELS[problem_type][user_lang]
    description = data.get("description")
    safe_description = escape(description) if description else None

    text = _step_header(4, lang=user_lang)
    if user_lang == "uz":
        text += (
            "📋 <b>Buyurtmani tasdiqlang:</b>\n\n"
            f"🔧 Muammo: {problem_label}\n"
        )
        if safe_description:
            text += f"📝 Izoh: {safe_description}\n"
        text += (
            f"📍 Joylashuv: qabul qilindi ✅\n\n"
            "Tasdiqlaysizmi? 👇"
        )
    else:
        text += (
            "📋 <b>Подтвердите заявку:</b>\n\n"
            f"🔧 Проблема: {problem_label}\n"
        )
        if safe_description:
            text += f"📝 Комментарий: {safe_description}\n"
        text += (
            f"📍 Геолокация: получена ✅\n\n"
            "Подтверждаете? 👇"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=confirm_order_keyboard(user_lang),
    )
    await state.set_state(OrderCreationStates.confirming_order)
    await _touch_order_draft(
        session=session,
        telegram_id=message.from_user.id,
        user_data=user_data,
        user_lang=user_lang,
        state_name=OrderCreationStates.confirming_order.state,
    )


@router.message(OrderCreationStates.sharing_location)
async def location_wrong_input(
    message: Message,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """User sent text instead of location."""
    hint = (
        "📍 Joylashuvni yuborish uchun <b>pastdagi tugmani bosing</b>.\n\n"
        "Matn yubormang — tugmadan foydalaning! 👇"
        if user_lang == "uz" else
        "📍 Для отправки геолокации <b>нажмите кнопку ниже</b>.\n\n"
        "Не пишите текст — используйте кнопку! 👇"
    )
    await message.answer(hint, parse_mode="HTML", reply_markup=share_location_keyboard(user_lang))
    await _touch_order_draft(
        session=session,
        telegram_id=message.from_user.id,
        user_data=user_data,
        user_lang=user_lang,
        state_name=OrderCreationStates.sharing_location.state,
    )


# ── Step 4: Confirm ───────────────────────────────────────────────

@router.callback_query(
    OrderCreationStates.confirming_order,
    F.data == "order:confirm",
)
async def confirm_order(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Confirm and create the order."""
    if not user_data:
        await callback.answer(t("error", user_lang), show_alert=True)
        return

    data = await state.get_data()
    order_service = OrderService(session)

    await callback.message.edit_text(
        "⏳ Buyurtma yuborilmoqda..." if user_lang == "uz" else "⏳ Отправляем заявку...",
    )

    try:
        order = await order_service.create_order(
            user_id=user_data.id,
            problem_type=ProblemType(data["problem_type"]),
            latitude=data["latitude"],
            longitude=data["longitude"],
            description=data.get("description"),
        )
    except Exception as e:
        await callback.message.edit_text(
            "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring /start"
            if user_lang == "uz" else
            "❌ Произошла ошибка. Попробуйте снова /start"
        )
        await callback.answer()
        await state.clear()
        await _clear_order_draft(session, callback.from_user.id)
        return

    await state.clear()
    await _clear_order_draft(session, callback.from_user.id)

    success = (
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
        f"📋 Raqam: <code>{order.order_uid}</code>\n\n"
        f"⏳ Dispetcher tez orada usta tayinlaydi.\n"
        f"📞 Siz bilan bog'lanishadi.\n\n"
        f"<i>O'rtacha kutish vaqti: 5-10 daqiqa</i>"
        if user_lang == "uz" else
        f"✅ <b>Ваша заявка принята!</b>\n\n"
        f"📋 Номер: <code>{order.order_uid}</code>\n\n"
        f"⏳ Диспетчер скоро назначит мастера.\n"
        f"📞 С вами свяжутся.\n\n"
        f"<i>Среднее время ожидания: 5-10 минут</i>"
    )

    await callback.message.edit_text(success, parse_mode="HTML")
    await callback.message.answer(
        t("main_menu", user_lang),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_lang),
    )

    # Notify dispatchers
    notification = NotificationService(bot, session)
    await notification.notify_dispatchers_new_order(order, user_data)
    await callback.answer()


@router.callback_query(
    OrderCreationStates.confirming_order,
    F.data == "order:cancel",
)
async def cancel_order_creation(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_lang: str = "uz",
):
    """Cancel order creation."""
    await state.clear()
    await _clear_order_draft(session, callback.from_user.id)
    cancelled = (
        "❌ Buyurtma bekor qilindi.\n\nQaytadan boshlash uchun tugmani bosing 👇"
        if user_lang == "uz" else
        "❌ Заявка отменена.\n\nНажмите кнопку ниже чтобы начать снова 👇"
    )
    await callback.message.edit_text(cancelled)
    await callback.message.answer(
        t("main_menu", user_lang),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_lang),
    )
    await callback.answer()


# ── Cancel active order ───────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_active_order(
    callback: CallbackQuery,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Cancel an active order."""
    if not user_data:
        await callback.answer(t("error", user_lang), show_alert=True)
        return

    order_uid = callback.data.split(":")[1]
    order_service = OrderService(session)

    try:
        await order_service.cancel_order(
            order_uid=order_uid,
            cancelled_by_telegram_id=callback.from_user.id,
            cancelled_by_role="client",
        )
        cancelled = (
            f"❌ Buyurtma <code>{order_uid}</code> bekor qilindi."
            if user_lang == "uz" else
            f"❌ Заявка <code>{order_uid}</code> отменена."
        )
        await callback.message.edit_text(cancelled, parse_mode="HTML")
        await _clear_order_draft(session, callback.from_user.id)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.answer()


# ── My Orders ─────────────────────────────────────────────────────

@router.message(F.text.in_(["📋 Mening buyurtmalarim", "📋 Мои заявки"]))
async def my_orders(
    message: Message,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Show client's order history."""
    if not user_data:
        await message.answer(t("not_registered", user_lang))
        return

    order_repo = OrderRepo(session)
    orders = await order_repo.get_user_history(user_data.id, limit=10)

    if not orders:
        no_orders = (
            "📋 Sizda hali buyurtmalar yo'q.\n\n«🆘 Yordam so'rash» tugmasini bosing!"
            if user_lang == "uz" else
            "📋 У вас пока нет заявок.\n\nНажмите «🆘 Запросить помощь»!"
        )
        await message.answer(no_orders)
        return

    status_emoji = {
        "new": "🆕", "assigned": "👨‍🔧", "accepted": "✅",
        "on_the_way": "🚗", "arrived": "📍", "in_progress": "🔧",
        "awaiting_confirm": "⏳", "completed": "✅", "cancelled": "❌", "rejected": "🔄",
    }
    status_labels_uz = {
        "new": "Yangi", "assigned": "Usta tayinlandi", "accepted": "Qabul qilindi",
        "on_the_way": "Yo'lda kelmoqda", "arrived": "Yetib keldi",
        "in_progress": "Jarayonda", "awaiting_confirm": "Tasdiqlanmoqda",
        "completed": "Tugallandi", "cancelled": "Bekor", "rejected": "Rad etildi",
    }
    status_labels_ru = {
        "new": "Новая", "assigned": "Мастер назначен", "accepted": "Принята",
        "on_the_way": "Едет к вам", "arrived": "Прибыл",
        "in_progress": "В процессе", "awaiting_confirm": "Ожидает подтверждения",
        "completed": "Завершена", "cancelled": "Отменена", "rejected": "Отклонена",
    }
    labels = status_labels_uz if user_lang == "uz" else status_labels_ru

    header = "📋 <b>Mening buyurtmalarim:</b>\n\n" if user_lang == "uz" else "📋 <b>Мои заявки:</b>\n\n"
    lines = [header]
    for order in orders:
        st = order.status.value
        icon = status_emoji.get(st, "•")
        label = labels.get(st, st)
        problem = PROBLEM_LABELS[order.problem_type][user_lang]
        date = order.created_at.strftime("%d.%m.%Y %H:%M")
        amount = f" • 💰{order.payment_amount:,.0f} so'm" if order.payment_amount else ""
        lines.append(
            f"{icon} <code>{order.order_uid}</code> — {label}\n"
            f"   📌 {problem}{amount}\n"
            f"   🕐 {date}\n"
        )

    await message.answer("".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "draft_continue")
async def continue_order_draft(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Continue previously abandoned order flow."""
    current_state = await state.get_state()

    if not current_state or not current_state.startswith("OrderCreationStates:"):
        await _clear_order_draft(session, callback.from_user.id)
        text = (
            "ℹ️ Oldingi jarayon topilmadi. Yangidan boshlash uchun <b>«🆘 Yordam so'rash»</b> ni bosing."
            if user_lang == "uz"
            else "ℹ️ Предыдущий процесс не найден. Для нового запроса нажмите <b>«🆘 Запросить помощь»</b>."
        )
        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()
        return

    await _touch_order_draft(
        session=session,
        telegram_id=callback.from_user.id,
        user_data=user_data,
        user_lang=user_lang,
        state_name=current_state,
    )

    text = (
        "✅ Zo'r, davom etamiz. Siz qolgan bosqichda turibsiz, keyingi amalni yuboring."
        if user_lang == "uz"
        else "✅ Отлично, продолжаем. Вы на том же шаге, отправьте следующее действие."
    )
    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "draft_cancel")
async def cancel_order_draft(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_lang: str = "uz",
):
    """Cancel abandoned order flow from reminder prompt."""
    await state.clear()
    await _clear_order_draft(session, callback.from_user.id)

    text = (
        "❌ Mayli, bekor qilindi. Kerak bo'lsa istalgan payt qayta yuborishingiz mumkin."
        if user_lang == "uz"
        else "❌ Хорошо, отменено. При необходимости можете отправить новую заявку в любое время."
    )
    await callback.message.answer(text)
    await callback.answer()

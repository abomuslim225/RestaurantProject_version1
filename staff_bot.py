# apps/staff_bot.py
# ─────────────────────────────────────────────────────────────────────
# Xodimlar uchun Telegram bot handler
# Webhook orqali ishlaydi (polling emas)
#
# Funksiyalar:
#   /start        — telefon raqam so'rash
#   📱 Contact    — login (telefon + parol) yuborish
#   /shift        — bugungi shift statistikasi
#   /salary       — maosh holati
#   /help         — buyruqlar ro'yxati
# ─────────────────────────────────────────────────────────────────────

import logging
import os

import django
from redis import Redis

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "root.settings")
django.setup()

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, Update,
)
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)
redis = Redis()
_RESET_TTL = 300

# ── FSM STATES ────────────────────────────────────────────────────────
class StaffState(StatesGroup):
    # Kelajakda kerak bo'lsa yangi state lar qo'shiladi
    waiting_for_contact = State()


# ── KEYBOARDS ─────────────────────────────────────────────────────────
def _contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="📱 Telefon raqam ulashish",
            request_contact=True,
        )]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _main_menu_keyboard():
    """Login olgandan keyingi asosiy menyu."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Bugungi shift")],
            [KeyboardButton(text="💰 Maosh holati")],
            [KeyboardButton(text="🔑 Parolni unutdim")],
            [KeyboardButton(text="❓ Yordam")],
        ],
        resize_keyboard=True,
    )


# ── DB HELPERS ────────────────────────────────────────────────────────

@sync_to_async
def _db_get_staff_by_phone(raw_phone: str):
    """
    Telefon raqam bo'yicha xodimni topadi.
    +998... va 998... variantlarini tekshiradi.
    customer rolini chiqarib tashlaydi.
    """
    from apps.models import User

    variants = {raw_phone}
    if raw_phone.startswith("+"):
        variants.add(raw_phone[1:])
    else:
        variants.add("+" + raw_phone)

    for phone in variants:
        user = User.objects.filter(
            phone_number=phone
        ).exclude(role="customer").first()
        if user:
            return user
    return None


@sync_to_async
def _db_get_staff_by_tg_id(tg_id: int):
    """
    Telegram ID bilan bog'langan xodimni topadi.
    StaffTelegram modelidan foydalanadi.
    """
    from apps.models import StaffTelegram
    try:
        link = StaffTelegram.objects.select_related("user").get(
            telegram_id=str(tg_id)
        )
        return link.user
    except StaffTelegram.DoesNotExist:
        return None


@sync_to_async
def _db_link_staff_tg(user, tg_user) -> bool:
    """
    Xodimni Telegram ID bilan bog'laydi.
    StaffTelegram modeliga yozadi.
    """
    from apps.models import StaffTelegram
    obj, created = StaffTelegram.objects.update_or_create(
        user=user,
        defaults={
            "telegram_id": str(tg_user.id),
            "telegram_username": tg_user.username or "",
            "telegram_name": tg_user.full_name or "",
        },
    )
    return created


@sync_to_async
def _db_get_shift_info(user) -> dict:
    """
    Xodimning bugungi shift statistikasi.
    Role ga qarab turli ma'lumot qaytaradi.
    """
    from apps.models import Order, OrderItem
    from django.utils import timezone

    today = timezone.now().date()
    role = user.role

    base = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.get_role_display() if hasattr(user, "get_role_display") else role,
        "shift": user.shift,
        "is_at_work": user.is_at_work,
    }

    if role == "waiter":
        orders = Order.objects.filter(waiter=user, created_at__date=today)
        base["today_orders"] = orders.count()
        base["paid_orders"] = orders.filter(
            status=Order.OrderStatusType.PAID
        ).count()
        base["active_orders"] = orders.exclude(
            status__in=[
                Order.OrderStatusType.PAID,
                Order.OrderStatusType.CANCELED,
            ]
        ).count()

    elif role == "chef":
        items = OrderItem.objects.filter(
            chef=user,
            order__created_at__date=today,
        )
        base["total_items"] = items.count()
        base["ready_items"] = items.filter(
            status=OrderItem.ItemStatus.READY
        ).count()
        base["cooking_items"] = items.filter(
            status=OrderItem.ItemStatus.COOKING
        ).count()

    elif role == "cashier":
        from apps.models import Payment
        from django.db.models import Sum
        payments = Payment.objects.filter(
            paid_at__date=today,
            status=Payment.PaymentStatus.COMPLETED,
        )
        base["today_payments"] = payments.count()
        base["today_revenue"] = str(
            payments.aggregate(total=Sum("amount"))["total"] or 0
        )

    return base


@sync_to_async
def _db_reset_password(user_id: int, new_password: str):
    from apps.models import User
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None

    user.set_password(new_password)
    user.temporary_password = None
    user.save(update_fields=["password", "temporary_password"])
    return f"{user.first_name} {user.last_name}"


@sync_to_async
def _db_get_salary_info(user) -> dict:
    """Xodimning maosh holati."""
    from apps.models import SalaryPayment

    last_payment = SalaryPayment.objects.filter(
        employee=user,
        status=SalaryPayment.StatusChoice.PAID,
    ).order_by("-paid_at").first()

    pending = SalaryPayment.objects.filter(
        employee=user,
        status=SalaryPayment.StatusChoice.PENDING,
    ).order_by("-created_at").first()

    return {
        "base_salary": str(user.base_salary),
        "fine_balance": str(user.fine_balance),
        "last_paid_at": (
            last_payment.paid_at.strftime("%d.%m.%Y")
            if last_payment else "Hali to'lanmagan"
        ),
        "last_amount": str(last_payment.amount) if last_payment else "—",
        "pending": str(pending.amount) if pending else None,
    }


# ── FORGET PASSWORD: REDIS FILTER ─────────────────────────────────────
def _is_awaiting_new_password(message: Message) -> bool:
    """Foydalanuvchi hozir yangi parol kiritishi kutilayotgan holatda bo'lsa True."""
    raw = redis.get(f"staffbot:reset:{message.from_user.id}")
    if not raw:
        return False
    return raw.decode().startswith("wait_password:")


# ── ROLE DISPLAY ──────────────────────────────────────────────────────
ROLE_EMOJI = {
    "owner": "👑",
    "manager": "🏢",
    "chef": "👨‍🍳",
    "waiter": "🍽",
    "cashier": "💳",
    "accountant": "📊",
}


def _role_emoji(role: str) -> str:
    return ROLE_EMOJI.get(role, "👤")


# ── SHIFT TEXT BUILDER ────────────────────────────────────────────────
def _build_shift_text(info: dict) -> str:
    role_raw = info.get("role", "")
    emoji = _role_emoji(role_raw)
    at_work = "✅ Ish joyida" if info.get("is_at_work") else "❌ Ish joyida emas"
    shift = "☀️ Kunduzgi" if info.get("shift") == "day" else "🌙 Tungi"

    lines = [
        f"{emoji} <b>{info.get('first_name')} {info.get('last_name')}</b>",
        f"📋 Lavozim: {role_raw}",
        f"🕐 Shift: {shift}",
        f"📍 Holat: {at_work}",
        "",
        "📊 <b>Bugungi statistika:</b>",
    ]

    # Waiter
    if "today_orders" in info:
        lines += [
            f"  📝 Jami buyurtmalar: {info['today_orders']}",
            f"  ✅ To'langan: {info['paid_orders']}",
            f"  🔄 Aktiv: {info['active_orders']}",
        ]
    # Chef
    elif "total_items" in info:
        lines += [
            f"  🍳 Jami taomlar: {info['total_items']}",
            f"  ✅ Tayyor: {info['ready_items']}",
            f"  🔥 Pishirilmoqda: {info['cooking_items']}",
        ]
    # Cashier
    elif "today_payments" in info:
        lines += [
            f"  💳 To'lovlar soni: {info['today_payments']}",
            f"  💰 Jami summa: {info['today_revenue']} so'm",
        ]
    else:
        lines.append("  — Ma'lumot yo'q")

    return "\n".join(lines)


def _build_salary_text(info: dict, first_name: str) -> str:
    lines = [
        f"💰 <b>{first_name} — Maosh holati</b>",
        "",
        f"📌 Asosiy maosh: <b>{info['base_salary']} so'm</b>",
        f"⚠️ Jarima balansi: <b>{info['fine_balance']} so'm</b>",
        "",
        f"🕐 Oxirgi to'lov: {info['last_paid_at']}",
        f"💵 Miqdor: {info['last_amount']} so'm",
    ]
    if info.get("pending"):
        lines += [
            "",
            f"⏳ Kutilayotgan to'lov: <b>{info['pending']} so'm</b>",
        ]
    return "\n".join(lines)


# ── BOT FACTORY ───────────────────────────────────────────────────────
def _build_bot(bot_obj) -> tuple:
    token = bot_obj.get_token()
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    router = Router()
    dp.include_router(router)
    return bot, dp, router


# ── MAIN HANDLER ─────────────────────────────────────────────────────
async def handle_staff_update(bot_obj, update_dict: dict):
    """
    TelegramWebhookView tomonidan chaqiriladi.
    Har update uchun chaqiriladi.
    """
    bot, dp, router = _build_bot(bot_obj)

    # ── /start ────────────────────────────────────────────────────────
    @router.message(F.text.startswith("/start"))
    async def start_handler(message: Message, state: FSMContext):
        # Eski "parol tiklash" holati bo'lsa — tozalab tashlaymiz
        redis.delete(f"staffbot:reset:{message.from_user.id}")

        # Avval Telegram ID bilan bog'langan bo'lsa — to'g'ridan menyu
        user = await _db_get_staff_by_tg_id(message.from_user.id)
        if user:
            await message.answer(
                f"👋 Xush kelibsiz, <b>{user.first_name}</b>!\n\n"
                f"Quyidagi tugmalardan foydalaning:",
                reply_markup=_main_menu_keyboard(),
            )
            return

        # Yangi foydalanuvchi — telefon raqam so'raymiz
        await message.answer(
            "👋 <b>Xodimlar boti</b>\n\n"
            "Telefon raqamingizni yuboring — login ma'lumotlarini oling.\n\n"
            "📱 Quyidagi tugmani bosing:",
            reply_markup=_contact_keyboard(),
        )

        # ── Telefon raqam (Contact) ───────────────────────────────────────

    @router.message(F.contact)
    async def contact_handler(message: Message, state: FSMContext):
        raw = message.contact.phone_number
        user = await _db_get_staff_by_phone(raw)
        tg_id = message.from_user.id

        if not user:
            redis.delete(f"staffbot:reset:{tg_id}")
            await message.answer(
                f"❌ Bu raqam tizimda topilmadi.\n\n"
                f"<code>{raw}</code>\n\n"
                f"Manager bilan bog'laning.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

            # Telegram ID ni xodim bilan bog'laymiz (keyingi kirishlarda telefon shart emas)
        await _db_link_staff_tg(user, message.from_user)

        # ── Agar "Parolni unutdim" oqimida bo'lsak — yangi parol so'raymiz ──
        reset_flag = redis.get(f"staffbot:reset:{tg_id}")
        if reset_flag and reset_flag.decode() == "wait_contact":
            redis.setex(f"staffbot:reset:{tg_id}", _RESET_TTL, f"wait_password:{user.id}")
            await message.answer(
                f"✅ Aniqlandingiz: <b>{user.first_name} {user.last_name}</b>\n\n"
                f"🔑 Endi yangi parolingizni yuboring (kamida 6 belgi):",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

            # Login ma'lumotlarini yuboramiz — ASOSIY FUNKSIYA
        await message.answer(
            f"✅ <b>Sizning login ma'lumotlaringiz:</b>\n\n"
            f"📱 Telefon: <code>{user.phone_number}</code>\n"
            f"🔑 Parol: <code>{user.temporary_password}</code>\n\n"
            f"⚠️ Saytga kirgandan so'ng parolingizni o'zgartiring!\n\n"
            f"🌐 Panel: /panel_url",
            reply_markup=_main_menu_keyboard(),
        )

    # ── Bugungi shift (tugma + buyruq) ───────────────────────────────
    @router.message(F.text.in_({"📊 Bugungi shift", "/shift"}))
    async def shift_handler(message: Message):
        user = await _db_get_staff_by_tg_id(message.from_user.id)
        if not user:
            await message.answer(
                "⚠️ Avval ro'yxatdan o'ting.\n"
                "Telefon raqamingizni yuboring: /start",
                reply_markup=_contact_keyboard(),
            )
            return

        info = await _db_get_shift_info(user)
        await message.answer(_build_shift_text(info))

    # ── Maosh holati (tugma + buyruq) ────────────────────────────────
    @router.message(F.text.in_({"💰 Maosh holati", "/salary"}))
    async def salary_handler(message: Message):
        user = await _db_get_staff_by_tg_id(message.from_user.id)
        if not user:
            await message.answer(
                "⚠️ Avval ro'yxatdan o'ting.\n"
                "Telefon raqamingizni yuboring: /start",
                reply_markup=_contact_keyboard(),
            )
            return

        info = await _db_get_salary_info(user)
        await message.answer(
            _build_salary_text(info, user.first_name)
        )

    # ── Parolni unutdim (tugma + buyruq) ──────────────────────────────
    @router.message(F.text.in_({"🔑 Parolni unutdim", "/forgot"}))
    async def forgot_password_handler(message: Message):
        redis.setex(f"staffbot:reset:{message.from_user.id}", _RESET_TTL, "wait_contact")
        await message.answer(
            "🔑 <b>Parolni tiklash</b>\n\n"
            "Identifikatsiya uchun telefon raqamingizni yuboring:",
            reply_markup=_contact_keyboard(),
        )

    # ── Yangi parolni qabul qilish (faqat "wait_password" holatida) ───
    @router.message(_is_awaiting_new_password)
    async def new_password_handler(message: Message):
        tg_id = message.from_user.id
        raw = redis.get(f"staffbot:reset:{tg_id}")
        user_id = int(raw.decode().split(":", 1)[1])

        new_password = (message.text or "").strip()
        if len(new_password) < 6:
            await message.answer(
                "⚠️ Parol kamida 6 belgidan iborat bo'lishi kerak.\n"
                "Qaytadan kiriting:"
            )
            return

        full_name = await _db_reset_password(user_id, new_password)
        redis.delete(f"staffbot:reset:{tg_id}")

        if not full_name:
            await message.answer(
                "❌ Xatolik yuz berdi. /start orqali qaytadan urinib ko'ring."
            )
            return

        await message.answer(
            f"✅ <b>{full_name}</b>, parolingiz muvaffaqiyatli yangilandi!\n\n"
            f"Endi yangi parolingiz bilan tizimga kiring.",
            reply_markup=_main_menu_keyboard(),
        )

    # ── Yordam (tugma + buyruq) ───────────────────────────────────────
    @router.message(F.text.in_({"❓ Yordam", "/help"}))
    async def help_handler(message: Message):
        await message.answer(
            "🤖 <b>Xodimlar boti buyruqlari:</b>\n\n"
            "/start        — Boshlash / qayta kirish\n"
            "/shift        — Bugungi shift statistikasi\n"
            "/salary       — Maosh holati\n"
            "/forgot       — Parolni unutdim\n"
            "/help         — Yordam\n\n"
            "📞 Muammo bo'lsa manager bilan bog'laning."
        )

    # ── Noma'lum xabar ───────────────────────────────────────────────
    @router.message()
    async def unknown_handler(message: Message):
        await message.answer(
            "❓ Tushunmadim.\n"
            "/help — buyruqlar ro'yxati"
        )

    # ── Update ni process qilish ──────────────────────────────────────
    update_obj = Update(**update_dict)
    await dp.feed_update(bot, update_obj)
    await bot.session.close()

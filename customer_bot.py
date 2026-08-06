# customer_bot.py
import logging
import os

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "root.settings")
django.setup()

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardRemove,
    PreCheckoutQuery, Update,
)
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── FSM STATES ────────────────────────────────────────────────────────
class PaymentProofState(StatesGroup):
    waiting_for_photo = State()


# ── BOT INSTANCE CACHE ────────────────────────────────────────────────
_instances: dict = {}


# ── DB HELPERS ────────────────────────────────────────────────────────

@sync_to_async
def _db_get_order(order_id):
    from apps.models import Order
    try:
        return Order.objects.select_related("table", "waiter").get(id=order_id)
    except Order.DoesNotExist:
        return None


@sync_to_async
def _db_get_order_items(order_id: int):
    from apps.models import OrderItem
    return list(
        OrderItem.objects
        .filter(order_id=order_id)
        .select_related("product")
    )


@sync_to_async
def _db_get_restaurant_card():
    from apps.models import RestaurantInfo
    info = RestaurantInfo.objects.first()
    return getattr(info, 'card_number', None) or 'Karta raqami kiritilmagan'


@sync_to_async
def _db_save_customer_tg_id(order_id: int, tg_id: int):
    from apps.models import Order
    Order.objects.filter(id=order_id).update(
        customer_telegram_id=str(tg_id)
    )


@sync_to_async
def _db_save_proof(order_id: int, file_id: str, tg_user_id: int, photo_bytes: bytes) -> tuple:
    import uuid
    from django.core.files.base import ContentFile
    from apps.models import Order, OrderPaymentProof

    ACTIVE = {
        Order.OrderStatusType.PENDING,
        Order.OrderStatusType.CONFIRMED,
        Order.OrderStatusType.COOKING,
        Order.OrderStatusType.READY,
    }

    try:
        order = Order.objects.select_related("table", "waiter").get(id=order_id)
    except Order.DoesNotExist:
        return False, "order_not_found"

    if order.status not in ACTIVE:
        return False, f"wrong_status:{order.status}"

    fname      = f"proof_{order_id}_{uuid.uuid4().hex[:8]}.jpg"
    image_file = ContentFile(photo_bytes, name=fname)

    proof, _ = OrderPaymentProof.objects.update_or_create(
        order=order,
        defaults={
            "photo_file_id":    file_id,
            "telegram_user_id": str(tg_user_id),
            "is_confirmed":     False,
            "submitted_at":     timezone.now(),
        },
    )
    proof.photo.save(fname, image_file, save=True)
    return True, "saved"


@sync_to_async
def _db_mark_paid(order_id: int, charge_id: str):
    from apps.models import Order, Payment
    order = Order.objects.select_related("table").get(id=order_id)
    order.status = Order.OrderStatusType.PAID
    order.save(update_fields=["status"])
    Payment.objects.create(
        order=order,
        method=Payment.PaymentMethod.ONLINE,
        status=Payment.PaymentStatus.COMPLETED,
        amount=order.total_price,
        paid_at=timezone.now(),
        telegram_payment_charge_id=charge_id,
    )
    try:
        from apps.consumers import broadcast_order_status
        broadcast_order_status(order.id, 'paid')
    except Exception as e:
        logger.warning(f"broadcast_order_status error: {e}")
    return order


@sync_to_async
def _db_get_telegram_id_for_order(order_id: int):
    from apps.models import Order, OrderPaymentProof
    try:
        order = Order.objects.get(id=order_id)
        if order.customer_telegram_id:
            return order.customer_telegram_id
    except Order.DoesNotExist:
        return None

    proof = (
        OrderPaymentProof.objects
        .filter(order_id=order_id)
        .order_by("-submitted_at")
        .first()
    )
    if proof and proof.telegram_user_id:
        return proof.telegram_user_id
    return None


@sync_to_async
def _ws_notify_waiter(order):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync as a2s
        layer = get_channel_layer()
        if order.waiter_id and layer:
            a2s(layer.group_send)(
                f"waiter_{order.waiter_id}",
                {
                    "type":         "proof_submitted",
                    "order_id":     order.id,
                    "table_number": order.table.number,
                    "message":      f"#{order.id} buyurtma uchun to'lov cheki yuborildi",
                },
            )
    except Exception as e:
        logger.warning(f"ws_notify_waiter error: {e}")


@sync_to_async
def _ws_notify_waiter_paid(order):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync as a2s
        layer = get_channel_layer()
        if order.waiter_id and layer:
            a2s(layer.group_send)(
                f"waiter_{order.waiter_id}",
                {
                    "type":         "payment_received",
                    "order_id":     order.id,
                    "table_number": order.table.number,
                    "amount":       str(order.total_price),
                },
            )
    except Exception as e:
        logger.warning(f"ws_notify_waiter_paid error: {e}")


# ── BOT FACTORY (cache bilan) ─────────────────────────────────────────
async def _get_or_create_app(bot_obj):
    bot_id = bot_obj.id
    if bot_id in _instances:
        return _instances[bot_id]

    token   = bot_obj.get_token()
    bot     = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp      = Dispatcher(storage=storage)
    router  = Router()
    dp.include_router(router)

    # ── /start handler ────────────────────────────────────────────────
    @router.message(F.text.startswith("/start"))
    async def start_handler(message: Message, state: FSMContext):
        args = message.text.split()

        # /start pay_<order_id> — to'lov (karta orqali)
        if len(args) > 1 and args[1].startswith("pay_"):
            order_id_str = args[1].replace("pay_", "")
            try:
                oid = int(order_id_str)
            except ValueError:
                await message.answer("❌ Noto'g'ri havola.")
                return

            order = await _db_get_order(oid)
            if not order:
                await message.answer("❌ Buyurtma topilmadi.")
                return

            await _db_save_customer_tg_id(oid, message.from_user.id)

            items       = await _db_get_order_items(oid)
            card_number = await _db_get_restaurant_card()

            lines = [
                f"🧾 <b>Buyurtma #{order.id}</b>",
                f"🪑 Stol: {order.table.number}",
                "",
                "<b>Taomlar:</b>",
            ]
            for item in items:
                line_total = float(item.product.price) * item.quantity
                lines.append(
                    f"  • {item.product.name} x{item.quantity} — {int(line_total):,} so'm"
                )
            lines += [
                "",
                f"💰 <b>Jami: {int(order.total_price):,} so'm</b>",
                "",
                "━━━━━━━━━━━━━━━━━━━━",
                "💳 <b>To'lov uchun quyidagi kartaga o'tkazing:</b>",
                f"<code>{card_number}</code>",
                "",
                "✅ To'lovdan so'ng chek rasmini (skrinshot) yuboring.",
            ]
            await message.answer("\n".join(lines))

            await state.update_data(order_id=oid)
            await state.set_state(PaymentProofState.waiting_for_photo)
            return

        # /start proof_<order_id> — naqd/karta uchun chek yuborish
        if len(args) > 1 and args[1].startswith("proof_"):
            order_id_str = args[1].replace("proof_", "")
            try:
                oid = int(order_id_str)
            except ValueError:
                await message.answer("❌ Noto'g'ri havola.")
                return

            order = await _db_get_order(oid)
            if not order:
                await message.answer("❌ Buyurtma topilmadi.")
                return

            await _db_save_customer_tg_id(oid, message.from_user.id)
            await state.update_data(order_id=oid)
            await state.set_state(PaymentProofState.waiting_for_photo)
            await message.answer(
                f"📸 <b>#{oid} buyurtma</b> uchun to'lov chekini yuboring.\n\n"
                f"Bank ilovasidan skrinshot yoki rasm yuboring.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        await message.answer(
            "👋 Assalomu alaykum!\n"
            "Bu bot restoran buyurtmalarini boshqarish uchun.\n\n"
            "Menyu orqali buyurtma bering va to'lov linkini oling."
        )

    # ── Chek rasmi handler ────────────────────────────────────────────
    @router.message(PaymentProofState.waiting_for_photo, F.photo)
    async def proof_photo_handler(message: Message, state: FSMContext):
        data     = await state.get_data()
        order_id = data.get("order_id")
        if not order_id:
            await state.clear()
            return

        photo          = message.photo[-1]
        file_id        = photo.file_id
        tg_user_id     = message.from_user.id

        file           = await bot.get_file(file_id)
        photo_bytes_io = await bot.download_file(file.file_path)
        photo_bytes    = photo_bytes_io.read()

        saved, reason = await _db_save_proof(
            order_id, file_id, tg_user_id, photo_bytes
        )
        await state.clear()

        if not saved:
            if reason == "order_not_found":
                await message.answer("❌ Buyurtma topilmadi.")
            else:
                await message.answer(
                    "ℹ️ Bu buyurtma allaqachon yakunlangan yoki bekor qilingan.\n"
                    "Chek qabul qilinmadi."
                )
            return

        order = await _db_get_order(order_id)
        await message.answer(
            "✅ Chekingiz qabul qilindi!\n\n"
            "Ofitsiant tekshirmoqda. Tasdiqlanishi bilanoq\n"
            "buyurtmangiz yakunlanadi. 🔔",
            reply_markup=ReplyKeyboardRemove(),
        )
        if order:
            await _ws_notify_waiter(order)

    # ── Noto'g'ri holatda rasm yuborilsa ─────────────────────────────
    @router.message(F.photo)
    async def unexpected_photo(message: Message, state: FSMContext):
        current = await state.get_state()
        if current is None:
            await message.answer(
                "📸 Rasm qabul qilinmadi.\n"
                "Chek yuborish uchun avval buyurtma linkidan foydalaning."
            )

    # ── Pre-checkout (hozircha ishlatilmaydi) ────────────────────────
    @dp.pre_checkout_query()
    async def pre_checkout(pcq: PreCheckoutQuery):
        order_id = pcq.invoice_payload.replace("order_", "")
        order    = await _db_get_order(order_id)
        if order:
            await pcq.answer(ok=True)
        else:
            await pcq.answer(ok=False, error_message="Buyurtma topilmadi.")

    # Cache ga saqlaymiz
    _instances[bot_id] = (bot, dp, router)
    return bot, dp, router


# ── MAIN HANDLER ─────────────────────────────────────────────────────
async def handle_customer_update(bot_obj, update_dict: dict):
    bot, dp, router = await _get_or_create_app(bot_obj)
    update_obj = Update(**update_dict)
    await dp.feed_update(bot, update_obj)
    # session.close() CHAQIRMANG — bot qayta ishlatiladi


# ── CHEK YUBORISH (kassir tasdiqlagan keyin) ─────────────────────────

def _build_receipt_text(order, items) -> str:
    lines = [
        f"🧾 <b>Chek — Buyurtma #{order.id}</b>",
        f"🪑 Stol: {order.table.number}",
        "",
        "<b>Taomlar:</b>",
    ]
    subtotal = 0
    for item in items:
        line_total = float(item.product.price) * item.quantity
        subtotal  += line_total
        lines.append(
            f"  • {item.product.name} x{item.quantity} — {int(line_total):,} so'm"
        )
    lines += [
        "",
        f"💰 Taomlar narxi: <b>{int(subtotal):,} so'm</b>",
    ]
    total = float(order.total_price)
    if total != subtotal:
        diff  = total - subtotal
        label = "Xizmat haqi" if diff > 0 else "Chegirma"
        lines.append(f"➕ {label}: {int(abs(diff)):,} so'm")
    lines += [
        f"✅ <b>JAMI TO'LOV: {int(total):,} so'm</b>",
        "",
        "Tashrif buyurganingiz uchun rahmat! 🙏",
    ]
    return "\n".join(lines)


async def send_receipt_to_customer(bot_obj, order_id: int) -> tuple:
    order = await _db_get_order(order_id)
    if not order:
        return False, "order_not_found"

    telegram_id = await _db_get_telegram_id_for_order(order_id)
    if not telegram_id:
        return False, "telegram_id_not_found"

    items = await _db_get_order_items(order_id)
    if not items:
        return False, "no_items"

    bot, dp, router = await _get_or_create_app(bot_obj)
    text = _build_receipt_text(order, items)

    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except Exception as e:
        logger.warning(f"send_receipt_to_customer error: {e}")
        return False, "send_failed"

    return True, "sent"

# @sync_to_async
# def _db_get_restaurant_card():
#     from apps.models import RestaurantInfo
#     info = RestaurantInfo.objects.first()
#     return getattr(info, 'card_number', '') or 'Karta raqami kiritilmagan'
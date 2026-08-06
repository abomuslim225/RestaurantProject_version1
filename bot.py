import asyncio
import logging
import os
import sys
from os import getenv

import django
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery,
    ReplyKeyboardMarkup, KeyboardButton
)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'root.settings')
django.setup()
from apps.models import Order, Payment, User, OrderItem
from django.utils import timezone
from asgiref.sync import sync_to_async
from dotenv import load_dotenv



load_dotenv()
TOKEN = getenv("BOT_TOKEN")
PAYMENT_PROVIDER_TOKEN = getenv("PAYMENT_PROVIDER_TOKEN")

dp = Dispatcher()
router = Router()


def get_contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqam ulashish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


@sync_to_async
def get_user_by_phone(phone_number):
    return User.objects.filter(phone_number=phone_number).first()

@sync_to_async
def get_order(order_id):
    try:
        return Order.objects.select_related('table', 'waiter').get(id=order_id)
    except Order.DoesNotExist:
        return None


@sync_to_async
def get_items_count(order_id):
    return OrderItem.objects.filter(order_id=order_id).count()


@sync_to_async
def mark_order_paid(order_id, charge_id):

    order = Order.objects.select_related('table').get(id=order_id)
    order.status = Order.OrderStatusType.PAID
    order.save(update_fields=['status'])
    Payment.objects.create(
        order=order,
        method=Payment.PaymentMethod.ONLINE,
        status=Payment.PaymentStatus.COMPLETED,
        amount=order.total_price,
        paid_at=timezone.now(),
        telegram_payment_charge_id=charge_id
    )
    return order


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    args = message.text.split()

    if len(args) > 1 and args[1].startswith('pay_'):
        order_id = args[1].replace('pay_', '')
        await send_invoice(message, order_id)
        return

    await message.answer(
        "👋 Assalomu alaykum!\n\n"
        "Telefon raqamingizni yuboring.",
        reply_markup=get_contact_keyboard()
    )


async def send_invoice(message: Message, order_id: str):
    order = await get_order(order_id)

    if not order:
        await message.answer("❌ Buyurtma topilmadi.")
        return

    count = await get_items_count(order_id)
    amount_in_tiyin = int(order.total_price * 100)

    await message.answer_invoice(
        title=f"Buyurtma #{order.id}",
        description=(
            f"🪑 {order.table.number}-stol\n"
            f"🍽 Taomlar soni: {count} ta\n"
            f"💰 Jami: {int(order.total_price):,} so'm"
        ),
        payload=f"order_{order.id}",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="UZS",
        prices=[
            LabeledPrice(
                label=f"Buyurtma #{order.id}",
                amount=amount_in_tiyin
            )
        ],
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False,
    )


@router.message(F.contact)
async def contact_handler(message: Message):
    raw = message.contact.phone_number
    phone_variants = set()
    phone_variants.add(raw)
    if raw.startswith('+'):
        phone_variants.add(raw[1:])
    else:
        phone_variants.add('+' + raw)

    user = None
    for phone in phone_variants:
        user = await get_user_by_phone(phone)
        if user:
            break

    if user and user.role != 'customer':
        await message.answer(
            f"✅ Sizning login ma'lumotlaringiz:\n\n"
            f"📱 Telefon: <code>{user.phone_number}</code>\n"
            f"🔑 Parol: <code>{user.temporary_password}</code>",
            parse_mode='HTML'
        )
    elif user and user.role == 'customer':
        await message.answer("❌ Bu xizmat faqat xodimlar uchun.")
    else:
        await message.answer(
            f"❌ Bu raqam tizimda topilmadi.\n"
            f"<code>{raw}</code>",
            parse_mode='HTML'
        )


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload
    order_id = payload.replace('order_', '')
    order = await get_order(order_id)

    if order:
        await pre_checkout_query.answer(ok=True)
    else:
        await pre_checkout_query.answer(
            ok=False,
            error_message="Buyurtma topilmadi."
        )


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment = message.successful_payment
    order_id = payment.invoice_payload.replace('order_', '')
    charge_id = payment.telegram_payment_charge_id

    order = await mark_order_paid(order_id, charge_id)

    await message.answer(
        f"✅ <b>To'lov qabul qilindi!</b>\n\n"
        f"📋 Buyurtma: <b>#{order.id}</b>\n"
        f"🪑 Stol: <b>{order.table.number}</b>\n"
        f"💰 To'langan: <b>{int(order.total_price):,} so'm</b>\n\n"
        f"Taomlaringiz tayyorlanmoqda. Rahmat! 🙏",
        parse_mode='HTML'
    )

    await notify_waiter(order)


async def notify_waiter(order):
    try:
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        if order.waiter_id and channel_layer:
            await channel_layer.group_send(
                f"waiter_{order.waiter_id}",
                {
                    'type': 'payment_received',
                    'order_id': order.id,
                    'table_number': order.table.number,
                    'amount': str(order.total_price),
                }
            )
    except Exception:
        pass


async def main() -> None:
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
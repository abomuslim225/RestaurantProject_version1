import asyncio

from celery import shared_task
from django.db.models import F
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from customer_bot import send_receipt_to_customer, handle_customer_update
from staff_bot import handle_staff_update
# Barcha kerakli modellar bitta joyda
from apps.models import Ingredient, DailyIngredient, OrderItem, Recipe, OrderReadyNotification, RestaurantBot


# ── KUN BOSHI — DailyIngredient yaratish ──────────────────────────────
@shared_task
def create_daily_ingredients():
    today = timezone.now().date()
    ingredients = Ingredient.objects.all()

    created_count = 0
    for ingredient in ingredients:
        daily, created = DailyIngredient.objects.get_or_create(
            ingredient=ingredient,
            date=today,
            defaults={
                'opening_amount': ingredient.stack_amount,
                'used_amount': 0,
                'closing_amount': ingredient.stack_amount,
            }
        )
        if created:
            created_count += 1

    return f"{today} — {created_count} ta ingredient hisobi yaratildi"


# ── KUN OXIRI — Hisobot ───────────────────────────────────────────────
@shared_task
def close_daily_ingredients():

    today = timezone.now().date()
    channel_layer = get_channel_layer()

    report = []
    low_stock = []

    daily_records = DailyIngredient.objects.filter(
        date=today
    ).select_related('ingredient')

    for record in daily_records:
        record.closing_amount = record.ingredient.stack_amount
        record.used_amount = record.opening_amount - record.closing_amount
        record.save(update_fields=['closing_amount', 'used_amount'])

        report.append({
            'name': record.ingredient.name,
            'unit': record.ingredient.stack_type,
            'opening': record.opening_amount,
            'used': record.used_amount,
            'closing': record.closing_amount,
        })

        if record.closing_amount <= record.ingredient.min_amount:
            low_stock.append({
                'name': record.ingredient.name,
                'amount': record.closing_amount,
                'unit': record.ingredient.stack_type,
                'min_amount': record.ingredient.min_amount,
            })

    async_to_sync(channel_layer.group_send)(
        "managers",
        {
            'type': 'daily_report',
            'date': str(today),
            'report': report,
            'low_stock': low_stock,
        }
    )

    return f"{today} — kunlik hisobot yuborildi"


# ── INGREDIENT AYIRISH ────────────────────────────────────────────────
@shared_task
def deduct_ingredients(order_item_id):
    today = timezone.now().date()

    try:
        item = OrderItem.objects.select_related('product').get(id=order_item_id)
    except OrderItem.DoesNotExist:
        return

    recipes = Recipe.objects.filter(
        product=item.product
    ).select_related('ingredient')

    low_stock_alerts = []

    for recipe in recipes:
        ingredient = recipe.ingredient
        used = recipe.amount * item.quantity

        ingredient.stack_amount = max(0, ingredient.stack_amount - used)
        ingredient.save(update_fields=['stack_amount'])

        DailyIngredient.objects.filter(
            ingredient=ingredient,
            date=today
        ).update(
            used_amount=F('used_amount') + used,
            closing_amount=ingredient.stack_amount
        )

        if ingredient.stack_amount <= ingredient.min_amount:
            low_stock_alerts.append({
                'ingredient_id': ingredient.id,
                'name': ingredient.name,
                'amount': ingredient.stack_amount,
                'unit': ingredient.stack_type,
                'message': (
                    f"'{ingredient.name}' kam qoldi: "
                    f"{ingredient.stack_amount} {ingredient.stack_type}"
                ),
            })

    if low_stock_alerts:
        channel_layer = get_channel_layer()
        for alert in low_stock_alerts:
            async_to_sync(channel_layer.group_send)(
                "managers",
                {
                    'type': 'low_ingredient',
                    **alert,
                }
            )


# ── 3 DAQIQADA QABUL QILINMASA ───────────────────────────────────────
@shared_task
def check_item_acceptance(order_item_id):
    try:
        item = OrderItem.objects.select_related(
            'order__table', 'product'
        ).get(id=order_item_id)
    except OrderItem.DoesNotExist:
        return

    if item.status != OrderItem.ItemStatus.WAITING:
        return

    item.is_urgent = True
    item.save(update_fields=['is_urgent'])

    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        "managers",
        {
            'type': 'item_not_accepted',
            'order_item_id': item.id,
            'order_id': item.order_id,
            'table_number': item.order.table.number,
            'product_name': item.product.name,
            'quantity': item.quantity,
            'message': f"'{item.product.name}' 3 daqiqada qabul qilinmadi!",
        }
    )

    async_to_sync(channel_layer.group_send)(
        "chefs",
        {
            'type': 'urgent_item',
            'order_item_id': item.id,
            'order_id': item.order_id,
            'table_number': item.order.table.number,
            'product_name': item.product.name,
            'quantity': item.quantity,
        }
    )


# ── 5 DAQIQADA OLIB KETILMASA ─────────────────────────────────────────
@shared_task
def check_pickup_timeout(notification_id):
    """Waiter 5 daqiqada olib ketmasa manager ga alert"""
    try:
        notif = OrderReadyNotification.objects.select_related(
            'chef', 'waiter',
            'order_item__order__table'
        ).get(id=notification_id)
    except OrderReadyNotification.DoesNotExist:
        return

    if notif.picked_up_at:
        return

    notif.manager_alerted = True
    notif.save(update_fields=['manager_alerted'])

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "managers",
        {
            'type': 'pickup_alert',
            'order_id': notif.order_item.order_id,
            'table_id': notif.order_item.order.table_id,
            'waiter_id': notif.waiter_id,
            'chef_id': notif.chef_id,
            'ready_at': str(notif.ready_at),
            'message': "Waiter taomni 5 daqiqada olib ketmadi!",
        }
    )

@shared_task
def process_telegram_update(bot_id, update_dict):
    # update_id yo'q bo'lsa skip
    if not update_dict or 'update_id' not in update_dict:
        return "update_id yo'q — skip"

    try:
        bot = RestaurantBot.objects.get(id=bot_id, is_active=True)
    except RestaurantBot.DoesNotExist:
        return f"Bot topilmadi: {bot_id}"

    # dict ga o'tkazish (QueryDict muammo bo'lmasin)
    if hasattr(update_dict, 'dict'):
        update_dict = update_dict.dict()
    update_dict = dict(update_dict)

    try:
        if bot.bot_type == RestaurantBot.BotType.CUSTOMER:
            async_to_sync(handle_customer_update)(bot, update_dict)
        elif bot.bot_type == RestaurantBot.BotType.STAFF:
            async_to_sync(handle_staff_update)(bot, update_dict)
    except Exception as e:
        print(f"[BOT XATO] {e}")
        return f"Xato: {e}"

    return f"Bot #{bot_id} update qayta ishlandi"
@shared_task
def send_paid_receipt_to_customer_task(order_id: int):


    bot_obj = RestaurantBot.get_active(
        restaurant_id=1,  # bitta restoranli tizim
        bot_type=RestaurantBot.BotType.CUSTOMER,
    )
    if not bot_obj:
        return

    sent, reason = asyncio.run(
        send_receipt_to_customer(bot_obj, order_id)
    )
    if not sent:
        # log qilish uchun joy — masalan reason == "telegram_id_not_found"
        # bo'lsa, mijoz botga umuman murojaat qilmagan, demak yuborish
        # shart emas — bu xato emas, oddiy holat.
        pass

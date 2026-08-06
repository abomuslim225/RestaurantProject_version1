from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum, F

from apps.models import (
    Reservation, User, Notification,
    OrderItem, Order, Fine,
    Ingredient, IngredientTransaction, ManagerAlert, OrderPaymentProof
)


@receiver(post_save, sender=Reservation)
def notification_reserve(sender, instance, created, **kwargs):
    if not created:
        return
    user_found = User.objects.filter(email=instance.email).first()
    if user_found:
        message = (
            f"{instance.full_name} -- {instance.capacity} kishilik stol band qildi | \n"
            f"bu mijoz tizimda {user_found.first_name} - {user_found.last_name} "
            f"shu nom bilan ro'yxatdan o'tgan"
        )
    else:
        message = f"{instance.full_name} -- {instance.capacity} kishilik stol band qildi"

    send_to = User.objects.filter(role__in=[User.RoleChoice.OWNER, User.RoleChoice.MANAGER])
    Notification.objects.bulk_create([
        Notification(user=user, message=message) for user in send_to
    ])


@receiver(post_save, sender=OrderItem)
def update_order_status_on_item_change(sender, instance, **kwargs):
    # ── 1. Order status yangilash ──
    order = instance.order
    all_items = list(order.order_items.all())
    if not all_items:
        return

    statuses = [i.status for i in all_items]

    if all(s == OrderItem.ItemStatus.READY for s in statuses):
        if order.status != Order.OrderStatusType.READY:
            order.status = Order.OrderStatusType.READY
            order.save(update_fields=['status'])

    elif all(s in [OrderItem.ItemStatus.COOKING, OrderItem.ItemStatus.READY] for s in statuses):
        if order.status == Order.OrderStatusType.CONFIRMED:
            order.status = Order.OrderStatusType.COOKING
            order.save(update_fields=['status'])

    # ── 2. Ingredient deduction — faqat READY bo'lganda ──
    if instance.status == OrderItem.ItemStatus.READY:
        _deduct_ingredients(instance)

    # ── 3. Dashboard yangilash ──
    _send_dashboard_update()


def _deduct_ingredients(order_item):
    from django.utils import timezone
    recipes = order_item.product.recipes.select_related('ingredient').all()

    for recipe in recipes:
        if not recipe.ingredient:
            continue

        total = recipe.amount_in_stock_unit * order_item.quantity
        ing = recipe.ingredient
        before = ing.stack_amount

        Ingredient.objects.filter(pk=ing.pk).update(stack_amount=F('stack_amount') - total)
        ing.refresh_from_db()

        IngredientTransaction.objects.create(
            ingredient=ing,
            tx_type=IngredientTransaction.TxType.RECIPE_USE,
            delta=-total,
            before=before,
            after=ing.stack_amount,
            order_item=order_item,
            performed_by=order_item.chef,
        )

        # Min amount alert — kuniga bir marta
        if ing.stack_amount <= ing.min_amount:
            today = timezone.now().date()
            already = ManagerAlert.objects.filter(
                ingredient=ing,
                alert_type=ManagerAlert.AlertType.LOW_INGREDIENT,
                created_at__date=today,
            ).exists()
            if not already:
                ManagerAlert.objects.create(
                    alert_type=ManagerAlert.AlertType.LOW_INGREDIENT,
                    title=f"⚠️ {ing.name} kam qoldi",
                    message=(
                        f"{ing.name}: {round(ing.stack_amount, 2)} {ing.stack_type} qoldi "
                        f"(minimal chegara: {ing.min_amount} {ing.stack_type})"
                    ),
                    ingredient=ing,
                )


@receiver(post_save, sender=Order)
def order_status_changed(sender, instance, **kwargs):
    _send_dashboard_update()


def _send_dashboard_update():
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    from django.utils import timezone
    from apps.models import Table

    today = timezone.now().date()
    today_orders = Order.objects.filter(created_at__date=today).count()
    today_revenue = Order.objects.filter(
        created_at__date=today,
        status=Order.OrderStatusType.PAID
    ).aggregate(total=Sum('total_price'))['total'] or 0
    occupied_tables = Table.objects.filter(is_occupied=True).count()
    waiting_items = OrderItem.objects.filter(status=OrderItem.ItemStatus.WAITING).count()
    staff_at_work = User.objects.filter(is_at_work=True).exclude(role='customer').count()

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "owner_dashboard",
        {
            'type': 'dashboard_update',
            'today_orders': today_orders,
            'today_revenue': str(today_revenue),
            'occupied_tables': occupied_tables,
            'waiting_items': waiting_items,
            'staff_at_work': staff_at_work,
        }
    )


@receiver(post_save, sender=Fine)
def update_fine_balance(sender, instance, **kwargs):
    total = Fine.objects.filter(
        employee=instance.employee,
        is_active=True
    ).aggregate(total=Sum('amount'))['total'] or 0
    instance.employee.fine_balance = total
    instance.employee.save(update_fields=['fine_balance'])

@receiver(post_save, sender=OrderPaymentProof)
def notify_waiter_on_proof(sender, instance, created, **kwargs):
    if not instance.order.waiter_id:
        return
    if not instance.photo:
        return
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        f"waiter_{instance.order.waiter_id}",
        {
            'type':         'proof_submitted',
            'order_id':     instance.order.id,
            'table_number': instance.order.table.number,
            'image_url':    instance.photo.url,
            'proof_id':     instance.id,
        }
    )
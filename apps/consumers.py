import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from datetime import timedelta
from rest_framework_simplejwt.tokens import AccessToken
from apps.models import User, OrderReadyNotification, OrderItem, Order

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


# ── TOKEN DAN USER OLISH ──────────────────────────────────────────────
async def get_user_from_token(scope):
    query_string = scope.get('query_string', b'').decode()
    params = dict(
        p.split('=') for p in query_string.split('&') if '=' in p
    )
    token = params.get('token')
    if not token:
        return None
    try:
        access_token = AccessToken(token)
        user = await database_sync_to_async(
            User.objects.get
        )(id=access_token['user_id'])
        return user
    except Exception:
        return None


# ── WAITER CONSUMER ───────────────────────────────────────────────────
class WaiterConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = await get_user_from_token(self.scope)
        if not user or user.role != 'waiter':
            await self.close()
            return

        self.user = user
        self.group_name = f"waiter_{user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get('action')
        order_id = data.get('order_id')

        # ── Waiter orderni tasdiqlaydi ──
        if action == 'confirm' and order_id:
            order = await self.confirm_order(order_id)
            if order:
                items = await self.get_order_items(order_id)

                await self.channel_layer.group_send(
                    "chefs",
                    {
                        'type': 'new_order',
                        'order_id': order_id,
                        'table_id': order['table_id'],
                        'table_number': order['table_number'],
                        'total_price': str(order['total_price']),
                        'comment': order['comment'],
                        'items': items,
                    }
                )

                await self.start_acceptance_timers(items)

                await self.send(text_data=json.dumps({
                    'type': 'order_confirmed',
                    'order_id': order_id,
                }))
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Order topilmadi yoki allaqachon tasdiqlangan',
                }))

        # ── Waiter orderni rad etadi ──
        elif action == 'cancel' and order_id:
            await self.cancel_order(order_id)
            await self.send(text_data=json.dumps({
                'type': 'order_canceled',
                'order_id': order_id,
            }))

        # ── Waiter taomni olib ketdi ──
        elif action == 'picked_up':
            order_item_id = data.get('order_item_id')
            if order_item_id:
                await self.mark_picked_up(order_item_id)
                await self.send(text_data=json.dumps({
                    'type': 'picked_up_confirmed',
                    'order_item_id': order_item_id,
                }))

    # ── Waiter ga kelgan eventlar ─────────────────────────────────────

    async def new_order(self, event):
        """Mijoz yangi order berdi"""
        await self.send(text_data=json.dumps({
            'type': 'new_order',
            'order_id': event['order_id'],
            'table_id': event['table_id'],
            'table_number': event['table_number'],
            'total_price': event['total_price'],
            'comment': event.get('comment', ''),
            'items': event['items'],
        }))

    async def item_status_changed(self, event):
        """Chef item statusini o'zgartirdi (masalan waiting→cooking)"""
        await self.send(text_data=json.dumps({
            'type': 'item_status_changed',
            'order_item_id': event['order_item_id'],
            'order_id': event['order_id'],
            'status': event['status'],
        }))

    async def order_ready(self, event):
        """Chef taomni tayyor qildi"""
        await self.send(text_data=json.dumps({
            'type': 'order_ready',
            'order_item_id': event['order_item_id'],
            'order_id': event['order_id'],
            'table_id': event['table_id'],
            'table_number': event['table_number'],
            'product_name': event['product_name'],
            'chef_name': event['chef_name'],
            'deadline': event['deadline'],
        }))

    async def payment_received(self, event):
        """Telegram orqali to'lov amalga oshirildi"""
        await self.send(text_data=json.dumps({
            'type': 'payment_received',
            'order_id': event['order_id'],
            'table_number': event['table_number'],
            'amount': event['amount'],
        }))

    # ── DB operatsiyalar ──────────────────────────────────────────────

    @database_sync_to_async
    def confirm_order(self, order_id):
        from apps.models import Order
        try:
            order = Order.objects.select_related('table').get(
                id=order_id,
                status=Order.OrderStatusType.PENDING
            )
            order.status = Order.OrderStatusType.CONFIRMED
            order.save(update_fields=['status'])
            return {
                'table_id': order.table_id,
                'table_number': order.table.number,
                'total_price': order.total_price,
                'comment': order.comment,
            }
        except Order.DoesNotExist:
            return None

    @database_sync_to_async
    def cancel_order(self, order_id):
        from apps.models import Order
        Order.objects.filter(
            id=order_id,
            status=Order.OrderStatusType.PENDING
        ).update(status=Order.OrderStatusType.CANCELED)

    @database_sync_to_async
    def get_order_items(self, order_id):
        from apps.models import OrderItem
        items = OrderItem.objects.filter(
            order_id=order_id
        ).select_related('product')
        return [
            {
                'order_item_id': item.id,
                'product_id': item.product_id,
                'product_name': item.product.name,
                'quantity': item.quantity,
            }
            for item in items
        ]

    @database_sync_to_async
    def start_acceptance_timers(self, items):
        from apps.tasks import check_item_acceptance
        from apps.models import OrderItem

        for item_data in items:
            task = check_item_acceptance.apply_async(
                args=[item_data['order_item_id']],
                countdown=3 * 60
            )
            OrderItem.objects.filter(
                id=item_data['order_item_id']
            ).update(celery_task_id=task.id)

    @database_sync_to_async
    def mark_picked_up(self, order_item_id):


        # Notification yangilash
        OrderReadyNotification.objects.filter(
            order_item_id=order_item_id,
            picked_up_at__isnull=True
        ).update(picked_up_at=timezone.now())

        # OrderItem statusini DELIVERED ga o'tkazish
        try:
            item = OrderItem.objects.select_related('order').get(id=order_item_id)
            item.status = OrderItem.ItemStatus.DELIVERED
            item.save(update_fields=['status'])

            # Barcha itemlar DELIVERED bo'lsa — Order SERVED
            order = item.order
            all_items = list(order.order_items.all())
            if all(i.status == OrderItem.ItemStatus.DELIVERED for i in all_items):
                order.status = Order.OrderStatusType.SERVED
                order.save(update_fields=['status'])

                # Kassirga xabar
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                layer = get_channel_layer()
                async_to_sync(layer.group_send)(
                    "cashiers",
                    {
                        'type': 'order_ready_for_cashier',
                        'order_id': order.id,
                        'table_number': order.table.number,
                        'total_price': str(order.total_price),
                        'waiter_name': self.user.first_name,
                        'items_count': len(all_items),
                        'ready_at': timezone.now().isoformat(),
                    }
                )

        except OrderItem.DoesNotExist:
            pass

    async def proof_submitted(self, event):
        """Mijoz to'lov cheki yubordi"""
        await self.send(text_data=json.dumps({
            'type': 'proof_submitted',
            'order_id': event['order_id'],
            'table_number': event['table_number'],
            'image_url': event['image_url'],
            'proof_id': event['proof_id'],
        }))

    async def urgent_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'urgent_message',
            'message': event['message'],
            'from': event.get('from', 'Manager'),
        }))

# ── CHEF CONSUMER ─────────────────────────────────────────────────────
class ChefConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = await get_user_from_token(self.scope)
        if not user or user.role != 'chef':
            await self.close()
            return

        self.user = user
        self.group_name = "chefs"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        pending_orders = await self.get_waiting_items()
        await self.send(text_data=json.dumps({
            'type': 'initial_orders',
            'orders': pending_orders,
        }))

        my_orders = await self.get_my_active_items()
        await self.send(text_data=json.dumps({
            'type': 'my_active_orders',
            'orders': my_orders,
        }))

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get('action')
        order_item_id = data.get('order_item_id')

        if not action or not order_item_id:
            return

        # ── Chef item ni qabul qildi ──
        if action == 'accept':
            success = await self.accept_order_item(order_item_id)
            if success:
                await self.channel_layer.group_send(
                    "chefs",
                    {
                        'type': 'item_accepted',
                        'order_item_id': order_item_id,
                        'chef_id': self.user.id,
                        'chef_name': f"{self.user.first_name} {self.user.last_name}",
                    }
                )

                # ── Waiterga ham xabar (faqat status yangilash uchun) ──
                item_info = await self.get_item_waiter_info(order_item_id)
                if item_info and item_info.get('waiter_id'):
                    await self.channel_layer.group_send(
                        f"waiter_{item_info['waiter_id']}",
                        {
                            'type': 'item_status_changed',
                            'order_item_id': order_item_id,
                            'order_id': item_info['order_id'],
                            'status': 'cooking',
                        }
                    )
            else:
                await self.send(text_data=json.dumps({
                    'type': 'accept_failed',
                    'order_item_id': order_item_id,
                    'message': "Bu taom allaqachon qabul qilingan",
                }))

            # ── Chef taomni tayyor qildi ──
        elif action == 'ready':
            result = await self.mark_item_ready(order_item_id)
            if result:
                # Waiter ga xabar
                await self.channel_layer.group_send(
                    f"waiter_{result['waiter_id']}",
                    {
                        'type': 'order_ready',
                        'order_item_id': order_item_id,
                        'order_id': result['order_id'],
                        'table_id': result['table_id'],
                        'table_number': result['table_number'],
                        'product_name': result['product_name'],
                        'chef_name': f"{self.user.first_name}",
                        'deadline': result['deadline'],
                    }
                )

                # 5 daqiqa Celery task
                check_pickup_timeout.apply_async(
                    args=[result['notification_id']],
                    countdown=5 * 60
                )

                # ── YANGI: order to'liq READY bo'lsa kassirlarga xabar ──
                order_is_ready = await self.check_order_fully_ready(result['order_id'])
                if order_is_ready:
                    await self.channel_layer.group_send(
                        "cashiers",
                        {
                            'type': 'order_ready_for_cashier',
                            'order_id': result['order_id'],
                            'table_number': result['table_number'],
                            'total_price': result['total_price'],
                            'waiter_name': result['waiter_name'],
                            'items_count': result['items_count'],
                            'ready_at': result['deadline'],
                        }
                    )

                await self.send(text_data=json.dumps({
                    'type': 'marked_ready',
                    'order_item_id': order_item_id,
                }))
            else:
                await self.send(text_data=json.dumps({
                    'type': 'ready_failed',
                    'order_item_id': order_item_id,
                    'message': "Taom holati noto'g'ri yoki sizga tegishli emas",
                }))

        # ── Chef taomni tayyor qildi ──
        elif action == 'ready':
            result = await self.mark_item_ready(order_item_id)
            if result:
                # Waiter ga xabar
                await self.channel_layer.group_send(
                    f"waiter_{result['waiter_id']}",
                    {
                        'type': 'order_ready',
                        'order_item_id': order_item_id,
                        'order_id': result['order_id'],
                        'table_id': result['table_id'],
                        'table_number': result['table_number'],
                        'product_name': result['product_name'],
                        'chef_name': f"{self.user.first_name}",
                        'deadline': result['deadline'],
                    }
                )

                # 5 daqiqa Celery task
                from apps.tasks import check_pickup_timeout
                check_pickup_timeout.apply_async(
                    args=[result['notification_id']],
                    countdown=5 * 60
                )

                # ── YANGI: order to'liq READY bo'lsa kassirlarga xabar ──
                order_is_ready = await self.check_order_fully_ready(result['order_id'])
                if order_is_ready:
                    await self.channel_layer.group_send(
                        "cashiers",
                        {
                            'type':         'order_ready_for_cashier',
                            'order_id':     result['order_id'],
                            'table_number': result['table_number'],
                            'total_price':  result['total_price'],
                            'waiter_name':  result['waiter_name'],
                            'items_count':  result['items_count'],
                            'ready_at':     result['deadline'],
                        }
                    )

                await self.send(text_data=json.dumps({
                    'type': 'marked_ready',
                    'order_item_id': order_item_id,
                }))

    # ── Chef ga kelgan eventlar ───────────────────────────────────────

    async def new_order(self, event):
        await self.send(text_data=json.dumps({
            'type': 'new_order',
            'order_id': event['order_id'],
            'table_id': event['table_id'],
            'table_number': event['table_number'],
            'comment': event.get('comment', ''),
            'items': event['items'],
        }))

    async def item_accepted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'item_accepted',
            'order_item_id': event['order_item_id'],
            'chef_id': event['chef_id'],
            'chef_name': event['chef_name'],
        }))

    async def urgent_item(self, event):
        await self.send(text_data=json.dumps({
            'type': 'urgent_item',
            'order_item_id': event['order_item_id'],
            'order_id': event['order_id'],
            'table_number': event['table_number'],
            'product_name': event['product_name'],
            'quantity': event['quantity'],
        }))

    # ── DB operatsiyalar ──────────────────────────────────────────────

    @database_sync_to_async
    def get_waiting_items(self):
        from apps.models import OrderItem, Order
        items = OrderItem.objects.filter(
            status=OrderItem.ItemStatus.WAITING,
            order__status=Order.OrderStatusType.CONFIRMED,
            chef__isnull=True
        ).select_related('product', 'order__table')

        return [
            {
                'order_item_id': item.id,
                'order_id': item.order_id,
                'table_id': item.order.table_id,
                'table_number': item.order.table.number,
                'product_name': item.product.name,
                'quantity': item.quantity,
                'comment': item.order.comment,
                'is_urgent': item.is_urgent,
            }
            for item in items
        ]

    @database_sync_to_async
    def get_my_active_items(self):
        from apps.models import OrderItem
        items = OrderItem.objects.filter(
            chef=self.user,
            status=OrderItem.ItemStatus.COOKING
        ).select_related('product', 'order__table')

        return [
            {
                'order_item_id': item.id,
                'order_id': item.order_id,
                'table_id': item.order.table_id,
                'table_number': item.order.table.number,
                'product_name': item.product.name,
                'quantity': item.quantity,
                'comment': item.order.comment,
            }
            for item in items
        ]

    @database_sync_to_async
    def get_item_waiter_info(self, order_item_id):
        from apps.models import OrderItem
        try:
            item = OrderItem.objects.select_related('order').get(id=order_item_id)
            return {
                'order_id': item.order_id,
                'waiter_id': item.order.waiter_id,
            }
        except OrderItem.DoesNotExist:
            return None

    @database_sync_to_async
    def accept_order_item(self, order_item_id):
        from django.db import transaction
        from apps.models import OrderItem

        with transaction.atomic():
            try:
                item = OrderItem.objects.select_for_update().get(
                    id=order_item_id,
                    status=OrderItem.ItemStatus.WAITING,
                    chef__isnull=True
                )
                item.chef = self.user
                item.status = OrderItem.ItemStatus.COOKING
                item.is_urgent = False

                if item.celery_task_id:
                    from root.celery import app as celery_app
                    celery_app.control.revoke(
                        item.celery_task_id,
                        terminate=True
                    )
                    item.celery_task_id = None

                item.save(update_fields=[
                    'chef', 'status', 'is_urgent', 'celery_task_id'
                ])
                return True
            except OrderItem.DoesNotExist:
                return False

    @database_sync_to_async
    def mark_item_ready(self, order_item_id):
        """Chef ready dedi — notification yaratish"""
        from apps.models import OrderItem, OrderReadyNotification

        try:
            item = OrderItem.objects.select_related(
                'order__table', 'order__waiter', 'product'
            ).get(
                id=order_item_id,
                chef=self.user,
                status=OrderItem.ItemStatus.COOKING
            )
            item.status = OrderItem.ItemStatus.READY
            item.save(update_fields=['status'])

            from apps.tasks import deduct_ingredients
            deduct_ingredients.delay(order_item_id)

            deadline = timezone.now() + timedelta(minutes=5)

            notif = OrderReadyNotification.objects.create(
                order_item=item,
                chef=self.user,
                waiter=item.order.waiter,
                deadline=deadline,
            )

            return {
                'notification_id': notif.id,
                'order_id':        item.order_id,
                'table_id':        item.order.table_id,
                'table_number':    item.order.table.number,
                'waiter_id':       item.order.waiter_id,
                'product_name':    item.product.name,
                'deadline':        deadline.isoformat(),
                # ── Kassir uchun qo'shimcha fieldlar ──
                'total_price':     str(item.order.total_price),
                'waiter_name':     item.order.waiter.first_name if item.order.waiter else '',
                'items_count':     item.order.order_items.count(),
            }
        except OrderItem.DoesNotExist:
            return None

    @database_sync_to_async
    def check_order_fully_ready(self, order_id):
        """Barcha order itemlar READY bo'lsa True qaytaradi"""
        from apps.models import OrderItem
        items = list(OrderItem.objects.filter(order_id=order_id))
        if not items:
            return False
        return all(item.status == OrderItem.ItemStatus.READY for item in items)


# ── MANAGER CONSUMER ──────────────────────────────────────────────────
class ManagerConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = await get_user_from_token(self.scope)
        if not user or user.role not in ['manager', 'owner']:
            await self.close()
            return

        self.user = user
        self.group_name = "managers"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        dashboard = await self.get_dashboard_data()
        await self.send(text_data=json.dumps({
            'type': 'dashboard',
            **dashboard,
        }))

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get('action')

        if action == 'assign_chef':
            order_item_id = data.get('order_item_id')
            chef_id = data.get('chef_id')
            success = await self.assign_to_chef(order_item_id, chef_id)
            if success:
                await self.channel_layer.group_send(
                    "chefs",
                    {
                        'type': 'item_accepted',
                        'order_item_id': order_item_id,
                        'chef_id': chef_id,
                        'chef_name': 'Manager tayinladi',
                    }
                )

        elif action == 'urgent_message':
            message = data.get('message', '')
            target_role = data.get('target_role')
            target_user_id = data.get('target_user_id')

            # DB ga saqlash
            await self.save_urgent_notification(
                message=message,
                target_user_id=target_user_id,
                target_role=target_role,
            )

            # WebSocket orqali yuborish
            if target_user_id:
                user = await self.get_user_by_id(target_user_id)
                if user:
                    if user.role == 'waiter':
                        group = f"waiter_{user.id}"
                    elif user.role == 'chef':
                        group = "chefs"
                    elif user.role == 'cashier':
                        group = "cashiers"
                    else:
                        group = "managers"
                    await self.channel_layer.group_send(group, {
                        'type': 'urgent_message',
                        'message': message,
                        'from': f"{self.user.first_name} (Manager)",
                    })
            elif target_role:
                if target_role == 'all':
                    for g in ['chefs', 'cashiers']:
                        await self.channel_layer.group_send(g, {
                            'type': 'urgent_message',
                            'message': message,
                            'from': f"{self.user.first_name} (Manager)",
                        })
                    waiter_ids = await self.get_all_waiter_ids()
                    for wid in waiter_ids:
                        await self.channel_layer.group_send(f"waiter_{wid}", {
                            'type': 'urgent_message',
                            'message': message,
                            'from': f"{self.user.first_name} (Manager)",
                        })
                elif target_role == 'waiter':
                    waiter_ids = await self.get_all_waiter_ids()
                    for wid in waiter_ids:
                        await self.channel_layer.group_send(f"waiter_{wid}", {
                            'type': 'urgent_message',
                            'message': message,
                            'from': f"{self.user.first_name} (Manager)",
                        })
                elif target_role == 'chef':
                    await self.channel_layer.group_send("chefs", {
                        'type': 'urgent_message',
                        'message': message,
                        'from': f"{self.user.first_name} (Manager)",
                    })
                elif target_role == 'cashier':
                    await self.channel_layer.group_send("cashiers", {
                        'type': 'urgent_message',
                        'message': message,
                        'from': f"{self.user.first_name} (Manager)",
                    })

    # ── Manager ga kelgan eventlar ────────────────────────────────────

    async def pickup_alert(self, event):
        await self.send(text_data=json.dumps({
            'type': 'pickup_alert',
            'order_id': event['order_id'],
            'table_id': event['table_id'],
            'waiter_id': event['waiter_id'],
            'chef_id': event['chef_id'],
            'ready_at': event['ready_at'],
            'message': "Waiter taomni 5 daqiqada olib ketmadi!",
        }))

    async def item_not_accepted(self, event):
        await self.send(text_data=json.dumps({
            'type': 'item_not_accepted',
            'order_item_id': event['order_item_id'],
            'order_id': event['order_id'],
            'table_number': event['table_number'],
            'product_name': event['product_name'],
            'message': event['message'],
        }))

    async def low_ingredient(self, event):
        await self.send(text_data=json.dumps({
            'type': 'low_ingredient',
            'ingredient_id': event['ingredient_id'],
            'name': event['name'],
            'amount': event['amount'],
            'unit': event['unit'],
            'message': event['message'],
        }))

    async def order_paid(self, event):
        """Kassir to'lovni tasdiqladi — manager panelida ko'rsatish"""
        await self.send(text_data=json.dumps({
            'type': 'order_paid',
            'order_id':     event['order_id'],
            'table_number': event['table_number'],
            'amount':       event['amount'],
            'method':       event['method'],
        }))

    # ── DB operatsiyalar ──────────────────────────────────────────────

    @database_sync_to_async
    def get_dashboard_data(self):
        from apps.models import Order, OrderItem, Table, User
        from django.utils import timezone

        today = timezone.now().date()

        orders = Order.objects.filter(created_at__date=today).count()
        occupied_tables = Table.objects.filter(is_occupied=True).count()
        waiting_items = OrderItem.objects.filter(
            status=OrderItem.ItemStatus.WAITING
        ).count()
        at_work = User.objects.filter(
            is_at_work=True
        ).exclude(role='customer').count()

        return {
            'today_orders': orders,
            'occupied_tables': occupied_tables,
            'waiting_items': waiting_items,
            'staff_at_work': at_work,
        }

    @database_sync_to_async
    def assign_to_chef(self, order_item_id, chef_id):
        from django.db import transaction
        from apps.models import OrderItem, User

        with transaction.atomic():
            try:
                item = OrderItem.objects.select_for_update().get(
                    id=order_item_id,
                    status=OrderItem.ItemStatus.WAITING
                )
                chef = User.objects.get(
                    id=chef_id,
                    role=User.RoleChoice.CHEF
                )
                item.chef = chef
                item.status = OrderItem.ItemStatus.COOKING
                item.is_urgent = False

                if item.celery_task_id:
                    from root.celery import app as celery_app
                    celery_app.control.revoke(
                        item.celery_task_id,
                        terminate=True
                    )
                    item.celery_task_id = None

                item.save(update_fields=[
                    'chef', 'status', 'is_urgent', 'celery_task_id'
                ])
                return True
            except (OrderItem.DoesNotExist, User.DoesNotExist):
                return False

    @database_sync_to_async
    def get_user_by_id(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def get_all_waiter_ids(self):
        return list(
            User.objects.filter(
                role=User.RoleChoice.WAITER,
                is_at_work=True
            ).values_list('id', flat=True)
        )

    @database_sync_to_async
    def save_urgent_notification(self, message, target_user_id=None, target_role=None):
        from apps.models import ManagerAlert

        target_user = None
        if target_user_id:
            try:
                target_user = User.objects.get(id=target_user_id)
            except User.DoesNotExist:
                pass

        title = "Shoshilinch xabar"
        if target_user:
            title += f" → {target_user.first_name} {target_user.last_name}"
        elif target_role:
            role_names = {
                'waiter': 'Ofitsiantlar',
                'chef': 'Oshpazlar',
                'cashier': 'Kassirlar',
                'all': 'Barcha xodimlar'
            }
            title += f" → {role_names.get(target_role, target_role)}"

        ManagerAlert.objects.create(
            alert_type=ManagerAlert.AlertType.DAILY_REPORT,
            title=title,
            message=message,
            related_user=target_user,
        )


# ── DASHBOARD CONSUMER ────────────────────────────────────────────────
class DashboardConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = await get_user_from_token(self.scope)
        if not user or user.role != 'owner':
            await self.close()
            return

        self.user = user
        self.group_name = "owner_dashboard"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        data = await self.get_dashboard_data()
        await self.send(text_data=json.dumps({
            'type': 'dashboard_update',
            **data,
        }))

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive(self, text_data):
        pass

    async def dashboard_update(self, event):
        await self.send(text_data=json.dumps({
            'type':            'dashboard_update',
            'today_orders':    event['today_orders'],
            'today_revenue':   event['today_revenue'],
            'occupied_tables': event['occupied_tables'],
            'waiting_items':   event['waiting_items'],
            'staff_at_work':   event['staff_at_work'],
        }))

    @database_sync_to_async
    def get_dashboard_data(self):
        from apps.models import Order, OrderItem, Table, User
        from django.db.models import Sum
        from django.utils import timezone

        today = timezone.now().date()

        today_orders = Order.objects.filter(
            created_at__date=today
        ).count()

        today_revenue = Order.objects.filter(
            created_at__date=today,
            status=Order.OrderStatusType.PAID
        ).aggregate(total=Sum('total_price'))['total'] or 0

        occupied_tables = Table.objects.filter(
            is_occupied=True
        ).count()

        waiting_items = OrderItem.objects.filter(
            status=OrderItem.ItemStatus.WAITING
        ).count()

        staff_at_work = User.objects.filter(
            is_at_work=True
        ).exclude(role='customer').count()

        return {
            'today_orders':    today_orders,
            'today_revenue':   str(today_revenue),
            'occupied_tables': occupied_tables,
            'waiting_items':   waiting_items,
            'staff_at_work':   staff_at_work,
        }


# ── CASHIER CONSUMER ──────────────────────────────────────────────────
class CashierConsumer(AsyncWebsocketConsumer):
    """
    Kassir real-time panel.

    Guruhlar:
        cashiers            — barcha kassirlar (broadcast)
        cashier_{user.id}   — shaxsiy xabarlar uchun

    Kassir faqat TINGLAYDI — to'lov REST API orqali:
        POST /api/v1/payments/

    Qabul qilinadigan eventlar:
        order_ready_for_cashier  — ChefConsumer dan (barcha items READY)
        order_paid               — PaymentCreateAPIView dan (to'lov tasdiqlandi)
        telegram_payment_received — Telegram bot dan (online to'lov)
    """

    async def connect(self):
        user = await get_user_from_token(self.scope)
        if not user or user.role not in ('cashier', 'manager', 'owner'):
            await self.close()
            return

        self.user = user
        self.personal_group = f"cashier_{user.id}"

        await self.channel_layer.group_add("cashiers", self.channel_name)
        await self.channel_layer.group_add(self.personal_group, self.channel_name)
        await self.accept()

        # Ulanishda hozirgi READY orderlarni yuborish
        ready_orders = await self.get_ready_orders()
        await self.send(text_data=json.dumps({
            'type':   'initial_ready_orders',
            'orders': ready_orders,
        }))

    async def disconnect(self, code):
        if hasattr(self, 'personal_group'):
            await self.channel_layer.group_discard("cashiers", self.channel_name)
            await self.channel_layer.group_discard(self.personal_group, self.channel_name)

    async def receive(self, text_data):
        # Kassir faqat tinglaydi — to'lov REST API orqali
        pass

    # ── Kassirga kelgan eventlar ──────────────────────────────────────

    async def order_ready_for_cashier(self, event):
        """
        Barcha order itemlar READY bo'ldi.
        ChefConsumer.receive() → 'ready' action dan keladi.
        """
        await self.send(text_data=json.dumps({
            'type':         'order_ready',
            'order_id':     event['order_id'],
            'table_number': event['table_number'],
            'total_price':  event['total_price'],
            'waiter_name':  event.get('waiter_name', ''),
            'items_count':  event.get('items_count', 0),
            'ready_at':     event.get('ready_at', ''),
        }))

    async def order_paid(self, event):
        """
        To'lov yakunlandi.
        PaymentCreateAPIView dan keladi.
        Boshqa kassir panellarini yangilash uchun.
        """
        await self.send(text_data=json.dumps({
            'type':         'order_paid',
            'order_id':     event['order_id'],
            'table_number': event['table_number'],
            'amount':       event['amount'],
            'method':       event['method'],
            'paid_by':      event.get('paid_by', ''),
        }))

    async def telegram_payment_received(self, event):
        """
        Telegram orqali online to'lov keldi.
        Telegram bot webhook dan keladi.
        """
        await self.send(text_data=json.dumps({
            'type':         'telegram_payment',
            'order_id':     event['order_id'],
            'table_number': event['table_number'],
            'amount':       event['amount'],
        }))

    # ── DB ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def get_ready_orders(self):
        """Ulanishda hozirgi barcha READY orderlarni qaytaradi"""
        from apps.models import Order
        orders = (
            Order.objects
            .filter(status=Order.OrderStatusType.READY)
            .select_related('table', 'waiter')
            .prefetch_related('order_items__product', 'order_items__chef')
            .order_by('created_at')
        )
        result = []
        for o in orders:
            items = list(o.order_items.all())
            result.append({
                'order_id':     o.id,
                'table_number': o.table.number,
                'total_price':  str(o.total_price),
                'waiter_name':  o.waiter.first_name if o.waiter else '',
                'items_count':  len(items),
                'items': [
                    {
                        'name':     item.product.name,
                        'quantity': item.quantity,
                        'price':    str(item.product.price),
                        'chef':     item.chef.first_name if item.chef else '',
                    }
                    for item in items
                ],
                'created_at': o.created_at.isoformat(),
            })
        return result

class OrderTrackingConsumer(AsyncWebsocketConsumer):
    """
    Mijoz uchun — order statusini real-time kuzatish.
    Auth talab qilinmaydi.
    URL: ws/order-tracking/<order_id>/
    """

    async def connect(self):
        self.order_id = self.scope['url_route']['kwargs']['order_id']
        self.group_name = f"order_{self.order_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        status = await self.get_order_status()
        if status:
            await self.send(text_data=json.dumps({
                'type': 'order_status_update',
                'order_id': int(self.order_id),
                'status': status,
            }))

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def order_status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'order_status_update',
            'order_id': event['order_id'],
            'status': event['status'],
        }))

    @database_sync_to_async
    def get_order_status(self):
        from apps.models import Order
        try:
            return Order.objects.get(id=self.order_id).status
        except Order.DoesNotExist:
            return None

def broadcast_order_status(order_id, status):
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        f"order_{order_id}",
        {'type': 'order_status_update', 'order_id': order_id, 'status': status}
    )
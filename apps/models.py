import io
from datetime import timedelta
from decimal import Decimal

import qrcode
from django.contrib.auth.models import AbstractUser
from django.core.files.base import ContentFile
from django.db.models.enums import TextChoices
from django.db.models import F
from django.db.models import (
    CharField, BooleanField, PositiveIntegerField, FloatField,
    DecimalField, Model, ForeignKey, CASCADE, ImageField, SET_NULL, TextField, Avg, PROTECT, OneToOneField
)
from django.db.models.fields import DateTimeField, DateField, EmailField, GenericIPAddressField, SmallIntegerField, \
    TimeField, URLField
from django.db.models.signals import post_save
from django.dispatch import receiver

from root import settings


def compute_payment_days(frequency: int, start_day: int) -> list:
    start_day = max(1, min(28, int(start_day or 1)))
    frequency = int(frequency or 1)

    if frequency <= 1:
        return [start_day]
    elif frequency == 2:
        second = start_day + 15
        if second > 28:
            second -= 28
        return sorted(set([start_day, second]))
    elif frequency >= 3:
        days = []
        for i in range(4):
            d = start_day + (i * 7)
            while d > 28:
                d -= 28
            days.append(d)
        return sorted(set(days))
    return [start_day]

# ── RESTAURANT BOT ────────────────────────────────────────────────────
class RestaurantBot(Model):
    class BotType(TextChoices):
        CUSTOMER = 'customer', 'Mijozlar boti'
        STAFF = 'staff', 'Xodimlar boti'

    restaurant = ForeignKey("apps.RestaurantInfo", on_delete=CASCADE, related_name="bots", null=True, blank=True)
    bot_type = CharField(max_length=10, choices=BotType, default=BotType.CUSTOMER)
    token_encrypted = CharField(max_length=512)
    bot_username = CharField(max_length=100, blank=True)
    bot_name = CharField(max_length=255, blank=True)
    is_active = BooleanField(default=False)
    webhook_set = BooleanField(default=False)
    added_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True, related_name="added_bots")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Restaurant Bot"
        verbose_name_plural = "Restaurant Bots"

    def __str__(self):
        status = "✅ active" if self.is_active else "❌ inactive"
        return f"@{self.bot_username} [{self.bot_type}] — {status}"

    def set_token(self, raw_token: str):
        from cryptography.fernet import Fernet
        f = Fernet(settings.BOT_ENCRYPTION_KEY.encode())
        self.token_encrypted = f.encrypt(raw_token.encode()).decode()

    def get_token(self) -> str:
        from cryptography.fernet import Fernet
        f = Fernet(settings.BOT_ENCRYPTION_KEY.encode())
        return f.decrypt(self.token_encrypted.encode()).decode()

    @classmethod
    def activate(cls, bot_instance: "RestaurantBot"):
        cls.objects.filter(
            restaurant=bot_instance.restaurant,
            bot_type=bot_instance.bot_type,
        ).exclude(pk=bot_instance.pk).update(is_active=False, webhook_set=False)
        bot_instance.is_active = True
        bot_instance.save(update_fields=['is_active'])

    @classmethod
    def get_active(cls, restaurant_id: int, bot_type: str) -> "RestaurantBot | None":
        return cls.objects.filter(
            restaurant_id=restaurant_id,
            bot_type=bot_type,
            is_active=True,
        ).order_by('-created_at').first()


# ── STAFF TELEGRAM ────────────────────────────────────────────────────
class StaffTelegram(Model):
    user = OneToOneField("apps.User", on_delete=CASCADE, related_name="telegram_link")
    telegram_id = CharField(max_length=20, unique=True)
    telegram_username = CharField(max_length=100, blank=True)
    telegram_name = CharField(max_length=255, blank=True)
    linked_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff Telegram"
        verbose_name_plural = "Staff Telegrams"

    def __str__(self):
        return f"{self.user} → @{self.telegram_username or self.telegram_id}"


# ── RESTAURANT INFO ───────────────────────────────────────────────────
class RestaurantInfo(Model):
    name = CharField(max_length=255)
    slogan = CharField(max_length=255)
    description = TextField()
    address = CharField(max_length=255)
    phone = CharField(max_length=20)
    email = EmailField()
    instagram = CharField(max_length=255, blank=True)
    telegram = CharField(max_length=255, blank=True)
    open_time = TimeField()
    close_time = TimeField()
    hero_image = ImageField(upload_to='restaurant/', null=True, blank=True)
    logo = ImageField(upload_to='restaurant/', null=True, blank=True)
    bot_username = CharField(max_length=100, blank=True)
    card_number = CharField(max_length=20, blank=True, verbose_name="Karta raqami")
    # ── MAOSH SCHEDULE DEFAULT ──
    default_salary_frequency = PositiveIntegerField(
        default=1, verbose_name="Oyiga necha marta maosh (default)",
        help_text="1 = oyiga 1 marta, 2 = ikki haftada bir, 4 = haftalik"
    )
    default_salary_start_day = PositiveIntegerField(
        default=1, verbose_name="Boshlanish kuni (default)",
        help_text="Oyning qaysi kunidan boshlab to'lanadi (1-28)"
    )

class Gallery(Model):
    image = ImageField(upload_to='gallery/')
    caption = CharField(max_length=255, blank=True)
    order = PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Gallery #{self.order}"


# ── USER ──────────────────────────────────────────────────────────────
class User(AbstractUser):
    class RoleChoice(TextChoices):
        OWNER = 'owner', 'Owner'
        MANAGER = 'manager', 'Manager'
        CHEF = 'chef', 'Oshpaz'
        WAITER = 'waiter', 'Oficiant'
        CASHIER = 'cashier', 'Kassir'
        CUSTOMER = 'customer', 'Mijoz'
        ACCOUNTANT = 'accountant', 'Hisobchi'

    class ShiftChoices(TextChoices):
        DAY = 'day', 'Kunduzgi'
        NIGHT = 'night', 'Tungi'

    photo = ImageField(upload_to='user_photo/', null=True, blank=True)
    role = CharField(max_length=255, choices=RoleChoice, default=RoleChoice.CUSTOMER)
    is_at_work = BooleanField(default=False)
    phone_number = CharField(max_length=15, unique=True, null=True, blank=True)
    date_of_hire = DateField(auto_now_add=True)
    shift = CharField(max_length=10, choices=ShiftChoices, default=ShiftChoices.DAY)
    base_salary = DecimalField(max_digits=10, decimal_places=2, default=0)
    fine_balance = DecimalField(max_digits=10, decimal_places=2, default=0)
    bank_card = CharField(max_length=16, null=True, blank=True)
    emergency_contact = CharField(max_length=15, null=True, blank=True)
    temporary_password = CharField(max_length=255, null=True, blank=True)
    email = EmailField(unique=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


# ── FINE ──────────────────────────────────────────────────────────────
class Fine(Model):
    employee = ForeignKey("apps.User", on_delete=CASCADE, related_name="fines")
    issued_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True, related_name="issued_fines")
    amount = DecimalField(max_digits=10, decimal_places=2)
    reason = TextField()
    created_at = DateTimeField(auto_now_add=True)
    is_active = BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} — {self.amount} — {self.created_at}"


class EmployeeLoginSession(Model):
    user = ForeignKey("apps.User", on_delete=CASCADE, related_name="login_sessions")
    device_name = CharField(max_length=255, blank=True)
    os = CharField(max_length=100, blank=True)
    browser = CharField(max_length=100, blank=True)
    ip_address = GenericIPAddressField(null=True, blank=True)
    refresh_token_jti = CharField(max_length=255, blank=True)
    logged_in_at = DateTimeField(auto_now_add=True)
    last_active = DateTimeField(auto_now=True)
    is_active = BooleanField(default=True)

    class Meta:
        ordering = ['-logged_in_at']


class DeviceRemovalRequest(Model):
    session = ForeignKey(EmployeeLoginSession, on_delete=CASCADE, related_name="removal_requests")
    requested_by = ForeignKey("apps.User", on_delete=CASCADE)
    code = CharField(max_length=6)
    is_used = BooleanField(default=False)
    expires_at = DateTimeField()
    created_at = DateTimeField(auto_now_add=True)


# ── MANAGER ALERT ─────────────────────────────────────────────────────
class ManagerAlert(Model):
    class AlertType(TextChoices):
        ITEM_NOT_ACCEPTED = 'item_not_accepted', 'Taom qabul qilinmadi'
        PICKUP_ALERT = 'pickup_alert', 'Taom olib ketilmadi'
        LOW_INGREDIENT = 'low_ingredient', 'Ingredient kam qoldi'
        ORDER_PAID = 'order_paid', "Order to'landi"
        DAILY_REPORT = 'daily_report', 'Kunlik hisobot'
        SESSION_LONG_OPEN = 'session_long_open', 'Sessiya uzoq ochiq'
        QR_CODE_ACTION = 'qr_code_action', 'QR Code o\'zgartirildi'

    alert_type = CharField(max_length=30, choices=AlertType)
    title = CharField(max_length=255)
    message = TextField()
    order_item = ForeignKey("apps.OrderItem", on_delete=SET_NULL, null=True, blank=True, related_name="alerts")
    order = ForeignKey("apps.Order", on_delete=SET_NULL, null=True, blank=True, related_name="alerts")
    table = ForeignKey("apps.Table", on_delete=SET_NULL, null=True, blank=True, related_name="alerts")
    ingredient = ForeignKey("apps.Ingredient", on_delete=SET_NULL, null=True, blank=True, related_name="alerts")
    related_user = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True, related_name="related_alerts")
    created_at = DateTimeField(auto_now_add=True)
    is_resolved = BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_alert_type_display()} — {self.created_at}"


# ── TABLE ─────────────────────────────────────────────────────────────
class Table(Model):
    number = PositiveIntegerField(unique=True)
    capacity = PositiveIntegerField(default=2)
    is_active = BooleanField(default=True)
    is_occupied = BooleanField(default=False)

    def __str__(self):
        return f"Stol #{self.number} — {self.capacity} kishilik"


# ── TABLE SESSION ─────────────────────────────────────────────────────
class TableSession(Model):
    table = ForeignKey("apps.Table", on_delete=CASCADE, related_name="table_sessions")
    waiter = ForeignKey("apps.User", on_delete=SET_NULL, null=True,
                        limit_choices_to={"role": User.RoleChoice.WAITER}, related_name="table_sessions")
    started_at = DateTimeField(auto_now_add=True)
    ended_at = DateTimeField(null=True, blank=True)
    is_active = BooleanField(default=True)

    def __str__(self):
        return f"Stol #{self.table.number} — {self.waiter}"


# ── CATEGORY ──────────────────────────────────────────────────────────
class Category(Model):
    title = CharField(max_length=255)

    def __str__(self):
        return self.title


# ── PRODUCT ───────────────────────────────────────────────────────────
class Product(Model):
    category = ForeignKey("apps.Category", on_delete=CASCADE)
    name = CharField(max_length=255)
    description = TextField(blank=True)
    price = DecimalField(max_digits=12, decimal_places=2)
    photo = ImageField(upload_to="product_photo/", null=True, blank=True)
    is_featured = BooleanField(default=False)

    @property
    def average_rating(self):
        result = self.comments.filter(is_blocked=False).aggregate(avg=Avg('rating'))
        return round(result['avg'] or 0, 1)

    @property
    def rating_count(self):
        return self.comments.filter(is_blocked=False).count()

    def __str__(self):
        return self.name


class Comment(Model):
    product = ForeignKey("apps.Product", on_delete=CASCADE, related_name="comments")
    user = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True, related_name="comments")
    display_name = CharField(max_length=50, default="Anonim")
    ip_address = GenericIPAddressField(null=True, blank=True)
    user_agent = CharField(max_length=500, null=True, blank=True)
    session_key = CharField(max_length=100, null=True, blank=True)
    text = TextField()
    rating = SmallIntegerField(default=5)
    is_blocked = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ── INGREDIENT ────────────────────────────────────────────────────────
class Ingredient(Model):
    class StackTypeChoice(TextChoices):
        KG = "kg", "Kilogram"
        GR = "gr", "Gram"
        ML = "ml", "Millilitr"
        L = "l", "Litr"

    name = CharField(max_length=255)
    stack_type = CharField(max_length=10, choices=StackTypeChoice, default=StackTypeChoice.GR)
    stack_amount = FloatField(help_text="Mavjud miqdor")
    min_amount = FloatField(default=0, help_text="Minimal chegara — kam qolsa alert")

    def __str__(self):
        return f"{self.name} — {self.stack_amount} {self.stack_type}"


# ── INGREDIENT TRANSACTION ────────────────────────────────────────────
class IngredientTransaction(Model):
    class TxType(TextChoices):
        PURCHASE = 'purchase', 'Xarid'
        RECIPE_USE = 'recipe_use', 'Taom pishirishda sarflandi'
        TAKEOUT = 'takeout', 'Chef oldi (qo\'lda)'
        SPOILAGE = 'spoilage', 'Chiqindi/Yo\'q bo\'ldi'
        ADJUSTMENT = 'adjustment', 'Qo\'lda tuzatish'

    ingredient = ForeignKey("apps.Ingredient", on_delete=CASCADE, related_name='transactions')
    tx_type = CharField(max_length=20, choices=TxType)
    delta = FloatField()
    before = FloatField()
    after = FloatField()
    order_item = ForeignKey("apps.OrderItem", null=True, blank=True, on_delete=SET_NULL,
                            related_name='ingredient_transactions')
    purchase = ForeignKey("apps.IngredientPurchase", null=True, blank=True, on_delete=SET_NULL,
                          related_name='transactions')
    performed_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True)
    note = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.delta > 0 else ''
        return f"{self.ingredient.name} {sign}{self.delta} ({self.tx_type})"


# ── INGREDIENT PURCHASE ───────────────────────────────────────────────
class IngredientPurchase(Model):
    ingredient = ForeignKey('apps.Ingredient', on_delete=CASCADE, related_name="purchases")
    quantity = FloatField()
    unit_price = DecimalField(max_digits=12, decimal_places=2)
    total_price = DecimalField(max_digits=12, decimal_places=2)
    supplier = CharField(max_length=255)
    purchased_by = ForeignKey('apps.User', on_delete=PROTECT, related_name="purchases")
    purchased_at = DateTimeField(auto_now_add=True)
    note = TextField(blank=True)

    class Meta:
        ordering = ['-purchased_at']
        verbose_name = "Masalliq xaridi"
        verbose_name_plural = "Masalliqlar xaridi"

    def __str__(self):
        return f"{self.ingredient.name} — {self.quantity} ta xarid (#{self.id})"

    def save(self, *args, **kwargs):
        if self.quantity and self.unit_price:
            self.total_price = Decimal(str(self.quantity)) * self.unit_price

        is_new = self.pk is None
        old_qty = 0.0
        if not is_new:
            old_qty = IngredientPurchase.objects.get(pk=self.pk).quantity

        super().save(*args, **kwargs)

        delta = self.quantity - old_qty
        if delta != 0:
            ing = self.ingredient
            before = ing.stack_amount
            Ingredient.objects.filter(pk=ing.pk).update(stack_amount=F('stack_amount') + delta)
            ing.refresh_from_db()
            IngredientTransaction.objects.create(
                ingredient=ing,
                tx_type=IngredientTransaction.TxType.PURCHASE,
                delta=delta,
                before=before,
                after=ing.stack_amount,
                purchase=self,
                performed_by=self.purchased_by,
            )


# ── RECIPE ────────────────────────────────────────────────────────────
class Recipe(Model):
    class UnitChoice(TextChoices):
        GR = 'gr', 'Gram'
        ML = 'ml', 'Millilitr'
        KG = 'kg', 'Kilogram'
        L = 'l', 'Litr'
        PCS = 'pcs', 'Dona'

    CONVERSION = {
        ('gr', 'kg'): 0.001, ('kg', 'gr'): 1000,
        ('ml', 'l'): 0.001, ('l', 'ml'): 1000,
        ('gr', 'gr'): 1.0, ('kg', 'kg'): 1.0,
        ('ml', 'ml'): 1.0, ('l', 'l'): 1.0,
        ('pcs', 'pcs'): 1.0,
    }

    product = ForeignKey("apps.Product", on_delete=CASCADE, related_name="recipes")
    ingredient = ForeignKey("apps.Ingredient", on_delete=SET_NULL, null=True, blank=True)
    amount = FloatField(help_text="Bir porsiya uchun miqdor")
    unit = CharField(max_length=5, choices=UnitChoice, default=UnitChoice.GR)

    @property
    def amount_in_stock_unit(self) -> float:
        if not self.ingredient:
            return self.amount
        key = (self.unit, self.ingredient.stack_type)
        return self.amount * self.CONVERSION.get(key, 1.0)

    def __str__(self):
        ing_name = self.ingredient.name if self.ingredient else '?'
        return f"{self.product.name} — {ing_name} x{self.amount}{self.unit}"


# ── ORDER ─────────────────────────────────────────────────────────────
class Order(Model):
    class OrderStatusType(TextChoices):
        PENDING = "pending", "Kutilmoqda"
        CONFIRMED = "confirmed", "Tasdiqlangan"
        COOKING = "cooking", "Pishirilmoqda"
        READY = "ready", "Tayyor"
        SERVED = "served", "Mijozga berildi"
        PAID = "paid", "To'landi"
        CANCELED = "canceled", "Bekor qilindi"

    class PaymentType(TextChoices):
        CASH = 'cash', 'Naqd'
        CARD = 'card', 'Karta'
        ONLINE = 'online', 'Online'

    payment_type = CharField(max_length=20, choices=PaymentType)
    table = ForeignKey("apps.Table", on_delete=CASCADE, related_name="orders")
    waiter = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True,
                        limit_choices_to={"role": User.RoleChoice.WAITER}, related_name="orders")
    status = CharField(max_length=20, choices=OrderStatusType, default=OrderStatusType.PENDING)
    total_price = DecimalField(max_digits=12, decimal_places=2, default=0)
    comment = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)
    customer_username = CharField(max_length=100, blank=True)
    customer_phone = CharField(max_length=20, blank=True)
    # Bot /start bosganda saqlanadi
    customer_telegram_id = CharField(max_length=20, blank=True)

    def __str__(self):
        return f"Order #{self.id} — Stol #{self.table.number}"


# ── ORDER ITEM ────────────────────────────────────────────────────────
class OrderItem(Model):
    class ItemStatus(TextChoices):
        WAITING = "waiting", "Kutilmoqda"
        COOKING = "cooking", "Pishirilmoqda"
        READY = "ready", "Tayyor"
        DELIVERED = "delivered", "Mijozga berildi"

    order = ForeignKey("apps.Order", on_delete=CASCADE, related_name="order_items")
    product = ForeignKey("apps.Product", on_delete=CASCADE)
    quantity = PositiveIntegerField(default=1)
    chef = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True,
                      limit_choices_to={"role": User.RoleChoice.CHEF}, related_name="order_items")
    status = CharField(max_length=20, choices=ItemStatus, default=ItemStatus.WAITING)
    is_urgent = BooleanField(default=False)
    celery_task_id = CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Order #{self.order.id} — {self.product.name} x{self.quantity}"


# ── ORDER READY NOTIFICATION ──────────────────────────────────────────
class OrderReadyNotification(Model):
    order_item = ForeignKey("apps.OrderItem", on_delete=CASCADE, related_name="ready_notifications")
    chef = ForeignKey("apps.User", on_delete=SET_NULL, null=True, related_name="ready_notifications")
    waiter = ForeignKey("apps.User", on_delete=SET_NULL, null=True, related_name="pickup_notifications")
    ready_at = DateTimeField(auto_now_add=True)
    deadline = DateTimeField()
    picked_up_at = DateTimeField(null=True, blank=True)
    manager_alerted = BooleanField(default=False)

    def __str__(self):
        return f"Order #{self.order_item.order.id} — ready {self.ready_at}"


# ── ORDER PAYMENT PROOF ───────────────────────────────────────────────
class OrderPaymentProof(Model):
    order = ForeignKey("apps.Order", on_delete=CASCADE, related_name="payment_proofs")
    photo = ImageField(upload_to="payment_proofs/", null=True, blank=True)  # ← QO'SHISH
    photo_file_id = CharField(max_length=255)
    telegram_user_id = CharField(max_length=20, blank=True)
    submitted_at = DateTimeField(auto_now_add=True)
    is_confirmed = BooleanField(default=False)


# ── PAYMENT ───────────────────────────────────────────────────────────
class Payment(Model):
    class PaymentMethod(TextChoices):
        CASH = 'cash', 'Naqd'
        CARD = 'card', 'Karta'
        ONLINE = 'online', 'Online (Telegram)'

    class PaymentStatus(TextChoices):
        WAITING = 'waiting', 'Kutilmoqda'
        HOLD = 'hold', 'Muzlatilgan'
        COMPLETED = 'completed', 'Yakunlandi'
        FAILED = 'failed', 'Xato'

    order = ForeignKey("apps.Order", on_delete=CASCADE, related_name="payments")
    method = CharField(max_length=10, choices=PaymentMethod)
    status = CharField(max_length=20, choices=PaymentStatus, default=PaymentStatus.WAITING)
    amount = DecimalField(max_digits=12, decimal_places=2)
    telegram_payment_charge_id = CharField(max_length=255, null=True, blank=True)
    stripe_charge_id = CharField(max_length=255, null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    paid_at = DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Order #{self.order.id} — {self.method} — {self.status}"


# ── DAILY INGREDIENT ──────────────────────────────────────────────────
class DailyIngredient(Model):
    ingredient = ForeignKey("apps.Ingredient", on_delete=CASCADE, related_name="daily_records")
    date = DateField(auto_now_add=True)
    opening_amount = FloatField()
    used_amount = FloatField(default=0)
    closing_amount = FloatField(default=0)

    class Meta:
        unique_together = ['ingredient', 'date']

    def __str__(self):
        return f"{self.ingredient.name} — {self.date}"


# ── DAILY INGREDIENT REPORT ───────────────────────────────────────────
class DailyIngredientReport(Model):
    class StatusChoice(TextChoices):
        PENDING = 'pending', 'Tasdiqlanmagan'
        CONFIRMED = 'confirmed', 'Tasdiqlangan'

    ingredient = ForeignKey("apps.Ingredient", on_delete=CASCADE, related_name="daily_reports")
    date = DateField()
    opening_amount = FloatField()
    estimated_used = FloatField()
    estimated_closing = FloatField()
    actual_used = FloatField(null=True, blank=True)
    actual_closing = FloatField(null=True, blank=True)
    status = CharField(max_length=20, choices=StatusChoice, default=StatusChoice.PENDING)
    confirmed_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True,
                              related_name="confirmed_reports")
    confirmed_at = DateTimeField(null=True, blank=True)
    note = TextField(blank=True)

    class Meta:
        unique_together = ['ingredient', 'date']

    def __str__(self):
        return f"{self.ingredient.name} — {self.date} — {self.status}"


# ── CHEF DAILY TAKEOUT ────────────────────────────────────────────────
class ChefDailyTakeout(Model):
    chef = ForeignKey(User, on_delete=CASCADE, limit_choices_to={'role': 'chef'})
    ingredient = ForeignKey(Ingredient, on_delete=CASCADE)
    amount = FloatField()
    date = DateField(auto_now_add=True)
    note = CharField(max_length=255, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            ing = self.ingredient
            if ing.stack_amount < self.amount:
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    f"Omborda yetarli {ing.name} yo'q. Mavjud: {ing.stack_amount} {ing.stack_type}"
                )
        super().save(*args, **kwargs)
        if is_new:
            ing = self.ingredient
            before = ing.stack_amount
            Ingredient.objects.filter(pk=ing.pk).update(stack_amount=F('stack_amount') - self.amount)
            ing.refresh_from_db()
            IngredientTransaction.objects.create(
                ingredient=ing,
                tx_type=IngredientTransaction.TxType.TAKEOUT,
                delta=-self.amount,
                before=before,
                after=ing.stack_amount,
                performed_by=self.chef,
                note=self.note,
            )


# ── SALARY PAYMENT ────────────────────────────────────────────────────
class SalaryPayment(Model):
    class PaymentType(TextChoices):
        CASH = 'cash', 'Naqd'
        CARD = 'card', 'Karta'

    class StatusChoice(TextChoices):
        PENDING = 'pending', 'Kutilmoqda'
        APPROVED = 'approved', 'Tasdiqlandi'
        PAID = 'paid', "To'landi"
        REJECTED = 'rejected', 'Rad etildi'

    employee = ForeignKey("apps.User", on_delete=CASCADE, related_name="salary_payments")
    paid_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True,
                         related_name="issued_payments", limit_choices_to={"role": "accountant"})
    amount = DecimalField(max_digits=12, decimal_places=2)
    month = DateField()
    payment_date = DateField(null=True, blank=True, help_text="Aniq to'lov sanasi (kun darajasida)")
    payment_type = CharField(max_length=10, choices=PaymentType, default=PaymentType.CASH)
    status = CharField(max_length=30, choices=StatusChoice, default=StatusChoice.PENDING)
    paid_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee} — {self.month} — {self.status}"

class Expense(Model):
    class ExpenseType(TextChoices):
        RENT = 'rent', 'Ijara'
        UTILITY = 'utility', 'Kommunal'
        EQUIPMENT = 'equipment', 'Jihozlar ta\'miri'
        MARKETING = 'marketing', 'Reklama'
        TRANSPORT = 'transport', 'Transport'
        OTHER = 'other', 'Boshqa'

    expense_type = CharField(max_length=20, choices=ExpenseType)
    amount = DecimalField(max_digits=12, decimal_places=2)
    description = TextField(blank=True)
    date = DateField()
    added_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True,
                          related_name="expenses")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.get_expense_type_display()} — {self.amount} ({self.date})"


# ── SALARY SCHEDULE (xodim uchun override) ───────────────────────────
class SalarySchedule(Model):
    employee = OneToOneField("apps.User", on_delete=CASCADE, related_name="salary_schedule")
    frequency = PositiveIntegerField(
        default=1, verbose_name="Oyiga necha marta",
        help_text="1, 2 yoki 4"
    )
    start_day = PositiveIntegerField(
        default=1, verbose_name="Boshlanish kuni",
        help_text="1 dan 28 gacha"
    )
    set_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True,
                        related_name="set_salary_schedules")
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Maosh jadvali (xodim)"
        verbose_name_plural = "Maosh jadvallari (xodimlar)"

    def __str__(self):
        return f"{self.employee} — {self.frequency}x/oy, kun {self.start_day}"

    def get_payment_days(self):
        return compute_payment_days(self.frequency, self.start_day)


# ── RESERVATION ───────────────────────────────────────────────────────
class Reservation(Model):
    table = ForeignKey("apps.Table", on_delete=CASCADE, related_name="reservations")
    full_name = CharField(max_length=255)
    email = CharField(max_length=255)
    capacity = PositiveIntegerField(default=1)
    date_of_reserve = DateTimeField()
    ended_date = DateTimeField(editable=False)

    def save(self, *args, **kwargs):
        self.ended_date = self.date_of_reserve + timedelta(minutes=120)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} — Stol #{self.table.number}"


# ── NOTIFICATION ──────────────────────────────────────────────────────
class Notification(Model):
    user = ForeignKey(User, on_delete=CASCADE, related_name="notifications")
    message = TextField()
    is_read = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} — {self.message[:50]}"


# ── TABLE QR CODE ─────────────────────────────────────────────────────
class TableQRCode(Model):
    table = ForeignKey("apps.Table", on_delete=CASCADE, related_name="qr_codes")
    label = CharField(max_length=255, blank=True, null=True)
    image = ImageField(upload_to="qr_codes/", blank=True, null=True)
    created_at = DateTimeField(auto_now_add=True)
    is_deleted = BooleanField(default=False)
    deleted_at = DateTimeField(null=True, blank=True)
    deleted_by = ForeignKey("apps.User", on_delete=SET_NULL, null=True, blank=True,
                            related_name="deleted_qr_codes")
    deleted_reason = CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Stol #{self.table.number} — QR Code"

    def get_redirect_url(self):
        return f"{settings.MENU_BASE_URL}?table_id={self.table.id}"

    def generate_qr(self):
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4
        )
        qr.add_data(self.get_redirect_url())
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        self.image.save(
            f"table_{self.table.number}_qr.png",
            ContentFile(buffer.read()),
            save=False
        )

    def save(self, *args, **kwargs):
        if self.pk is None:
            super().save(*args, **kwargs)
            self.generate_qr()
        super().save(*args, **kwargs)


# ── SIGNALS ───────────────────────────────────────────────────────────
@receiver(post_save, sender=OrderItem)
def update_order_status_on_item_change(sender, instance, **kwargs):
    order = instance.order
    all_items = list(order.order_items.all())
    if not all_items:
        return

    statuses = [i.status for i in all_items]

    # Hammasi DELIVERED → SERVED
    if all(s == OrderItem.ItemStatus.DELIVERED for s in statuses):
        if order.status not in [Order.OrderStatusType.SERVED, Order.OrderStatusType.PAID]:
            order.status = Order.OrderStatusType.SERVED
            order.save(update_fields=['status'])

    # Hammasi READY → READY
    elif all(s == OrderItem.ItemStatus.READY for s in statuses):
        if order.status != Order.OrderStatusType.READY:
            order.status = Order.OrderStatusType.READY
            order.save(update_fields=['status'])

    # Aralash COOKING/READY → COOKING
    elif all(s in [OrderItem.ItemStatus.COOKING, OrderItem.ItemStatus.READY,
                   OrderItem.ItemStatus.DELIVERED] for s in statuses):
        if order.status == Order.OrderStatusType.CONFIRMED:
            order.status = Order.OrderStatusType.COOKING
            order.save(update_fields=['status'])


@receiver(post_save, sender=TableSession)
def update_table_occupation(sender, instance, **kwargs):
    table = instance.table
    table.is_occupied = instance.is_active
    table.save(update_fields=['is_occupied'])

    # models.py da signal qo'shing


@receiver(post_save, sender=SalaryPayment)
def update_fine_on_payment(sender, instance, created, **kwargs):
    if created and instance.status == 'paid':
        instance.employee.fine_balance = 0
        instance.employee.save(update_fields=['fine_balance'])



class Profile(Model):
    name = CharField("Ism", max_length=100)
    bio = CharField("Tavsif", max_length=255, blank=True)
    photo = ImageField("Profil rasmi", upload_to='linktree/profile/')
    is_active = BooleanField("Faol profil", default=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profil"


class Link(Model):
    profile = ForeignKey(Profile, on_delete=CASCADE, related_name='links')
    title = CharField("Nomi", max_length=100)
    url = URLField("Havola")
    icon = CharField(
        "Icon (ixtiyoriy, masalan: bi-bag)", max_length=50, blank=True,
        help_text="Bootstrap icon nomi, masalan: bi-bag, bi-newspaper"
    )
    order = PositiveIntegerField("Tartib raqami", default=0)
    is_active = BooleanField("Faol", default=True)

    class Meta:
        ordering = ['order']
        verbose_name = "Havola"
        verbose_name_plural = "Havolalar"

    def __str__(self):
        return self.title


class SocialLink(Model):
    PLATFORM_CHOICES = [
        ('twitter', 'Twitter / X'),
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('spotify', 'Spotify'),
        ('telegram', 'Telegram'),
        ('youtube', 'YouTube'),
        ('tiktok', 'TikTok'),
        ('whatsapp', 'WhatsApp'),
        ('other', 'Boshqa'),
    ]
    profile = ForeignKey(Profile, on_delete=CASCADE, related_name='socials')
    platform = CharField("Platforma", max_length=20, choices=PLATFORM_CHOICES)
    url = URLField("Havola")
    order = PositiveIntegerField("Tartib raqami", default=0)

    class Meta:
        ordering = ['order']
        verbose_name = "Ijtimoiy tarmoq"
        verbose_name_plural = "Ijtimoiy tarmoqlar"

    def __str__(self):
        return self.get_platform_display()
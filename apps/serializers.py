import random
import re
import secrets
import string
from decimal import Decimal

from django.db.models import IntegerField, Sum, Count, Q
from django.template.defaultfilters import first
from django.utils import timezone
from jsonschema import ValidationError
from redis import Redis
from rest_framework import serializers
from rest_framework.fields import CharField, SerializerMethodField, ChoiceField, DecimalField
from rest_framework.generics import CreateAPIView
from rest_framework.relations import StringRelatedField
from rest_framework.serializers import ModelSerializer, Serializer
from django.contrib.auth import authenticate
from apps.models import Product, Category, Table, Order, OrderItem, Recipe, Ingredient, User, TableSession, \
    SalaryPayment, Notification, Reservation, TableQRCode, DailyIngredientReport, Comment, RestaurantInfo, Gallery, \
    IngredientPurchase, Payment, ChefDailyTakeout, OrderPaymentProof, RestaurantBot, ManagerAlert, EmployeeLoginSession, \
    Fine, IngredientTransaction, compute_payment_days, SalarySchedule, Expense, Link, SocialLink, Profile
from apps.utils import set_webhook


class RestaurantInfoSerializer(ModelSerializer):
    class Meta:
        model = RestaurantInfo
        fields = (
            'id', 'name', 'slogan', 'description',
            'address', 'phone', 'email',
            'instagram', 'telegram',
            'open_time', 'close_time',
            'hero_image', 'logo', "bot_username", "card_number",
            "default_salary_frequency", "default_salary_start_day",
        )

class GallerySerializer(ModelSerializer):
    class Meta:
        model = Gallery
        fields = ('id', 'image', 'caption', 'order')


class MenuCategoryModelSerializer(ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "title")


class MenuProductModelSerializer(ModelSerializer):
    category = MenuCategoryModelSerializer(read_only=True)

    class Meta:
        model = Product
        fields = ("id", "name", "price", "category", "photo")


class OrderItemCreateSerializer(Serializer):
    product = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(Serializer):
    table_id = serializers.IntegerField()
    items = OrderItemCreateSerializer(many=True)
    comment = serializers.CharField(required=False, allow_blank=True, default='')
    payment_type = serializers.ChoiceField(
        choices=['cash', 'card', 'online'],
        default='cash'
    )

    def validate_table_id(self, value):
        if not Table.objects.filter(id=value).exists():
            raise ValidationError("Bunday stol mavjud emas")

        # ── YANGI: stol uchun aktiv session (ofitsiant tomonidan ochilgan) bo'lishi shart ──
        if not TableSession.objects.filter(table_id=value, is_active=True).exists():
            raise ValidationError(
                "Bu stol hali ofitsiant tomonidan ochilmagan. "
                "Iltimos, ofitsiantni chaqiring."
            )
        return value

    def validate_items(self, value):
        if not value:
            raise ValidationError("Kamida bitta product bo'lishi kerak")

        product_ids = [item["product"] for item in value]
        products = Product.objects.filter(id__in=product_ids)
        found_ids = set(products.values_list("id", flat=True))

        for item in value:
            if item["product"] not in found_ids:
                raise ValidationError(f"Product id={item['product']} topilmadi")
        return value

    def create(self, validated_data):
        table = Table.objects.get(id=validated_data["table_id"])
        items_data = validated_data["items"]
        comment = validated_data.get("comment", "")
        payment_type = validated_data.get('payment_type')

        products = {p.id: p for p in Product.objects.filter(id__in=[i["product"] for i in items_data])}
        total_price = sum(products[item["product"]].price * item["quantity"] for item in items_data)

        # Bu yerga endi ValidationError 'validate_table_id' bosqichida tutiladi,
        # shuning uchun session har doim mavjud bo'ladi
        session = TableSession.objects.filter(table=table, is_active=True).select_related("waiter").first()

        order = Order.objects.create(
            table=table, total_price=total_price, comment=comment,
            payment_type=payment_type,
            waiter=session.waiter if session else None,
        )

        OrderItem.objects.bulk_create(
            [OrderItem(order=order, product=products[item["product"]], quantity=item["quantity"])
             for item in items_data]
        )

        return order


class CategoryModelSerializer(ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "title",)





class RecipeModelSerializer(ModelSerializer):
    ingredient_name = CharField(source='ingredient.name', read_only=True)
    unit = CharField(source='ingredient.stack_type', read_only=True)

    class Meta:
        model = Recipe
        fields = ("id", "product", "ingredient", "ingredient_name", "amount", "unit")

class ProductModelSerializer(ModelSerializer):
    category_name = CharField(source='category.title', read_only=True)
    recipes = RecipeModelSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = ("id", "photo", "name", "price", "category", "category_name", "recipes")

class IngredientModelSerializer(ModelSerializer):
    class Meta:
        model = Ingredient
        fields = ("id", "name", "stack_type", "stack_amount", 'min_amount')
        read_only_fields = ("id",)

class IngredientPurchaseSerializer(ModelSerializer):
    ingredient_name = CharField(source='ingredient.name', read_only=True)
    purchased_by_name = CharField(source='purchased_by.get_full_name', read_only=True)
    unit = CharField(source='ingredient.stack_type', read_only=True)

    class Meta:
        model = IngredientPurchase
        fields = (
            'id', 'ingredient', 'ingredient_name', 'unit',
            'quantity', 'unit_price', 'total_price',
            'supplier', 'note',
            'purchased_by', 'purchased_by_name',
            'purchased_at',
        )
        read_only_fields = ('id', 'purchased_by', 'purchased_at', 'total_price')

    def validate(self, data):
        data['total_price'] = Decimal(str(data['quantity'])) * data['unit_price']
        return data

    def create(self, validated_data):
        validated_data['purchased_by'] = self.context['request'].user
        return super().create(validated_data)

class DailyIngredientReportSerializer(ModelSerializer):
    ingredient_name = serializers.CharField(source='ingredient.name', read_only=True)
    ingredient_unit = serializers.CharField(source='ingredient.stack_type', read_only=True)
    confirmed_by_name = serializers.CharField(source='confirmed_by.get_full_name', read_only=True)

    class Meta:
        model = DailyIngredientReport
        fields = ('id', 'date', 'ingredient', 'ingredient_name', 'ingredient_unit', 'opening_amount', 'estimated_used',
                  'estimated_closing', 'actual_used', 'actual_closing', 'status', 'confirmed_by', 'confirmed_by_name',
                  'confirmed_at', 'note',)
        read_only_fields = (
            'id', 'date', 'ingredient',
            'opening_amount', 'estimated_used', 'estimated_closing',
            'confirmed_by', 'confirmed_at',
        )

class IngredientTransactionSerializer(ModelSerializer):
    ingredient_name = CharField(source='ingredient.name', read_only=True)
    unit = CharField(source='ingredient.stack_type', read_only=True)

    class Meta:
        model = IngredientTransaction
        fields = ('id', 'ingredient', 'ingredient_name', 'unit',
                  'tx_type', 'delta', 'before', 'after', 'note', 'created_at')
        read_only_fields = fields

class CreateEmployeeModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id","first_name", "last_name", "phone_number", "role", "base_salary", "fine_balance")

    def generate_secure_password(self, length=8):
        characters = string.digits
        return ''.join(random.choices(characters, k=length))

    def create(self, validated_data):
        temporary_password = self.generate_secure_password()
        validated_data['temporary_password'] = temporary_password
        phone_number = validated_data['phone_number']
        first_name = validated_data['first_name']
        validated_data["username"] = f"{first_name}_{phone_number[-2:]}"
        validated_data["email"] = f"{first_name}.com"
        user = User(**validated_data)
        user.set_password(temporary_password)
        user.temporary_password = temporary_password
        user.save()
        return user


class UserModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone_number", "temporary_password", "password",)


class EmployeeLoginSerializer(Serializer):
    login = CharField(max_length=255)  # telefon yoki username
    temporary_password = CharField(max_length=255)

    def validate(self, data):
        login = data.get('login')
        password = data.get('temporary_password')

        # Telefon raqami yoki username bo'yicha qidirish
        user = (
                User.objects.filter(phone_number=login).first()
                or User.objects.filter(username=login).first()
        )

        if not user:
            raise ValidationError('Foydalanuvchi topilmadi')

        if user.check_password(password):
            data['user'] = user
            return data

        if user.temporary_password and user.temporary_password == password:
            data['user'] = user
            return data

        raise ValidationError('Login yoki parol xato')


class RegisterUserModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone_number", "email", "password")
        extra_kwargs = {'temporary_password': {'read_only': True}}

    def create(self, validated_data):
        password = validated_data.pop("password")
        # phone_number = validated_data.get("phone_number")
        first_name = validated_data.get("first_name")
        random_number = random.randint(1, 1000)

        validated_data["username"] = f"{first_name}_{random_number}"

        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginUserModelSerializer(Serializer):
    # phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True)
    email = serializers.EmailField(write_only=True)

    # def validate_phone_number(self, value):
    #     clean_phone_number = re.sub(r'\D', '', value)
    #
    #     if len(clean_phone_number) > 9:
    #         clean_phone_number = clean_phone_number[-9:]
    #
    #     return clean_phone_number

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")
        user = User.objects.get(email=email)
        # user = authenticate(email=email, password=password)
        if not user:
            raise serializers.ValidationError("Email yoki parol xato")

        if not user.check_password(password):
            raise ValidationError('Email yoki parol xato')
        data['user'] = user
        return data


class OrderItemModelSerializer(ModelSerializer):
    chef = StringRelatedField()

    class Meta:
        model = OrderItem
        fields = ("chef", "status")


class ManagerModelSerializer(ModelSerializer):
    table = StringRelatedField()
    waiter = StringRelatedField()
    order_items = OrderItemModelSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ("status", "total_price", "table", "waiter", "order_items")

class ManagerAlertSerializer(ModelSerializer):
    related_user_name = CharField(source='related_user.first_name', read_only=True, default='')

    class Meta:
        model = ManagerAlert
        fields = ('id', 'alert_type', 'title', 'message', 'related_user', 'related_user_name', 'created_at', 'is_resolved')

class SendEmailSerializer(Serializer):
    email = CharField(max_length=255)


class OtpVerifySerializer(Serializer):
    email = CharField(max_length=255)
    code = CharField(max_length=6)

    def validate(self, value):
        email = value.get("email")
        code = value.get("code")
        redis = Redis()
        otp_code = redis.get(email)
        if not otp_code:
            raise ValidationError("expire date")

        if otp_code.decode() != str(code):
            raise ValidationError("parol xato")

        redis.delete(email)
        return value

class ResetPasswordSerializer(Serializer):
    email = serializers.EmailField(required=True)
    new_password = serializers.CharField(required=True, min_length=8, write_only=True)

# user update serializers
class UserUpdateModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "phone_number", "email", "password", "username")


class EmployeeModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "first_name", "last_name", "phone_number",
                  "email", "password", "username", "bank_card",
                  "base_salary", "fine_balance", "emergency_contact",
                  "is_at_work", "shift", "photo")


class AdminEmployeeUpdateSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("role", "is_at_work", "base_salary", "fine_balance", "shift")


class EmployeeListModelSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "first_name", "last_name", "role", "phone_number", "is_at_work", "shift", "base_salary", "fine_balance")

class LoginSessionSerializer(ModelSerializer):
    is_current = SerializerMethodField()

    class Meta:
        model = EmployeeLoginSession
        fields = (
            'id', 'device_name', 'os', 'browser',
            'ip_address', 'logged_in_at', 'last_active',
            'is_active', 'is_current'
        )
        read_only_fields = fields

    def get_is_current(self, obj):
        request = self.context.get('request')
        if not request:
            return False
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            auth = request.headers.get('Authorization', '')
            token = AccessToken(auth.replace('Bearer ', ''))
            return obj.refresh_token_jti == str(token['jti'])
        except Exception:
            return False


class DeviceRemovalRequestSerializer(Serializer):
    code = CharField(max_length=6, min_length=6)

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(
                "Kod faqat raqamlardan iborat bo'lishi kerak"
            )
        return value

class TableModelSerializer(ModelSerializer):
    class Meta:
        model = Table
        fields = ("id", "number", "capacity", "is_active")
        read_only_fields = ("number",)

    def create(self, validated_data):
        last_table = Table.objects.order_by("number").last()
        validated_data['number'] = (last_table.number + 1) if last_table else 1
        return super().create(validated_data)


class TableRUDModelSerializer(ModelSerializer):
    class Meta:
        model = Table
        fields = ("id", "number", "capacity", "is_active",)

class EmployeeSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "first_name")

class TableSessionCreateModelSerializer(ModelSerializer):
    class Meta:
        model = TableSession
        fields = ("id", "table", "is_active", "waiter", "started_at", "ended_at", )

    def create(self, validated_data):
        table_id = validated_data['table']
        now = timezone.now()
        is_reserved = Reservation.objects.filter(table=table_id, date_of_reserve__lte=now, ended_date__gte=now)
        if is_reserved:
            raise ValidationError('bu stol band qilingan')
        request = self.context.get("request")
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            validated_data['waiter'] = request.user
        validated_data['is_active'] = True
        return super().create(validated_data)

class TableSessionListSerializer(ModelSerializer):
    waiter = EmployeeSerializer(read_only=True)
    table = TableRUDModelSerializer(read_only=True)

    class Meta:
        model = TableSession
        fields = ("id", "table", "is_active", "waiter", "started_at", "ended_at")

class ChefSerializer(ModelSerializer):
    chef = EmployeeSerializer(read_only=True)
    product = ProductModelSerializer(read_only=True)

    class Meta:
        model = OrderItem
        fields = ("id", "chef", "status", "product", "quantity")


class ChefDailyTakeoutSerializer(ModelSerializer):
    ingredient_name = CharField(source='ingredient.name', read_only=True)
    unit = CharField(source='ingredient.stack_type', read_only=True) 
    chef_name = CharField(source='chef.get_full_name', read_only=True)

    class Meta:
        model = ChefDailyTakeout
        fields = ['id', 'ingredient', 'ingredient_name', 'amount',
                  'unit', 'note', 'date', 'chef_name', 'created_at']
        read_only_fields = ['chef', 'date', 'created_at']

class OrderModelSerializer(ModelSerializer):
    waiter = EmployeeSerializer(read_only=True)
    order_items = ChefSerializer(many=True, read_only=True)
    table = TableRUDModelSerializer(read_only=True)

    class Meta:
        model = Order
        fields = ("id", "waiter", "table", "status", "total_price", "created_at", "order_items", "payment_type")

class OrderPaymentProofSerializer(ModelSerializer):
    # Frontenda shu URL orqali rasmni ko'rsatasiz:
    # https://api.telegram.org/file/bot{TOKEN}/{file_path}
    # Avval file_path ni olish kerak:
    # GET https://api.telegram.org/bot{TOKEN}/getFile?file_id={photo_file_id}

    class Meta:
        model = OrderPaymentProof
        fields = ('id', 'photo_file_id', 'submitted_at', 'is_confirmed')

class OwnerSalaryPaymentModelSerializer(ModelSerializer):
    paid_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SalaryPayment
        fields = ("id", "employee", "paid_by", "paid_by_name", "amount",
                  "status", "month", "payment_date", "payment_type", "paid_at", "created_at")

    def get_paid_by_name(self, obj):
        if obj.paid_by:
            return f"{obj.paid_by.first_name} {obj.paid_by.last_name}".strip()
        return "Menejer"


# reservation qilingandagi message xabari
class NotificationSerializer(ModelSerializer):
    class Meta:
        model = Notification
        fields = ("id", "message", "is_read", "created_at")


class ReservationCreateModelSerializer(ModelSerializer):
    date_of_reserve = serializers.DateTimeField(format="%Y-%m-%d %H:%M", input_formats=["%Y-%m-%d %H:%M", "iso-8601"])

    class Meta:
        model = Reservation
        fields = ("full_name", "capacity", "date_of_reserve", "email", 'table', 'ended_date')
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['table'] = TableModelSerializer(instance).data
        return data


        

class TableQRCodeCreateSerializer(serializers.ModelSerializer):
    table = serializers.PrimaryKeyRelatedField(queryset=Table.objects.filter(is_active=True))

    class Meta:
        model = TableQRCode
        fields = ['id', 'table', 'label']

    def validate_table(self, table):
        if TableQRCode.objects.filter(table=table, is_deleted=False).exists():
            raise serializers.ValidationError(f"Table #{table.number} uchun allaqachon aktiv QR code mavjud.")
        return table

    def create(self, validated_data):
        qr = TableQRCode(**validated_data)
        qr.save()
        return qr


class TableQRCodeDeleteSerializer(Serializer):
    reason = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default=''
    )

class TableQRCodeListSerializer(ModelSerializer):
    table_number = serializers.IntegerField(source='table.number', read_only=True)
    image_url = serializers.SerializerMethodField()
    redirect_url = serializers.SerializerMethodField()
    deleted_by_name = serializers.CharField(
        source='deleted_by.get_full_name',
        read_only=True,
        default=''
    )

    class Meta:
        model = TableQRCode
        fields = [
            'id', 'table', 'table_number', 'label',
            'image_url', 'redirect_url', 'created_at',
            # Soft delete fieldlar
            'is_deleted', 'deleted_at', 'deleted_by',
            'deleted_by_name', 'deleted_reason'
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

    def get_redirect_url(self, obj):
        return obj.get_redirect_url()

#     owner dashboard serializers
class TodaySummarySerializer(Serializer):
    revenue = SerializerMethodField()
    total_orders = SerializerMethodField()
    active_orders = SerializerMethodField()

    # kunlik daromadni hisoblab jo'natish
    def get_revenue(self, obj):
        today = timezone.now().date()
        return Order.objects.filter(created_at__date=today, status=Order.OrderStatusType.PAID).aggregate(
            total=Sum('total_price'))['total'] or 0

    # kunlik ordersni sanaymiz
    def get_total_orders(self, obj):
        today = timezone.now().date()
        return Order.objects.filter(created_at__date=today).count()

    def get_active_orders(self, obj):
        return Order.objects.exclude(status__in=[Order.OrderStatusType.PAID, Order.OrderStatusType.CANCELED]).count()


# hozirda stollar holati
class LiveTablesSerializer(Serializer):
    total = SerializerMethodField()
    occupied = SerializerMethodField()
    free = SerializerMethodField()
    occupied_rate = SerializerMethodField()

    # stollar soni
    def get_total(self, obj):
        return Table.objects.count()

    # band stollar soni distinct bu yerda bir stolda bir dan ko'p order bo'lsa ularni takrorlamasdan bir marta sanash vazifasini bajaradi
    def get_occupied(self, obj):
        return Table.objects.filter(orders__status__in=[Order.OrderStatusType.PENDING, Order.OrderStatusType.COOKING,
                                                        Order.OrderStatusType.CONFIRMED,
                                                        Order.OrderStatusType.READY]).distinct().count()

    # bo'sh stollar soni
    def get_free(self, obj):
        return self.get_total(obj) - self.get_occupied(obj)

    def get_occupied_rate(self, obj):
        total = self.get_total(obj)
        if total == 0:
            return "0%"
        rate = (self.get_occupied(obj) / total) * 100
        return f"{round(rate, 1)}"


class LiveKitchenSerializer(Serializer):
    pending_dishes = SerializerMethodField()
    cooking_dishes = SerializerMethodField()
    ready_dishes = SerializerMethodField()

    # N+1 xatosini oldini olish uchun malumotlarni cashe qilamiz
    def _get_kitchen_stats(self):
        if not hasattr(self, '_kitchen_stats_cache'):
            today = timezone.now().date()
            self._kitchen_stats_cache = OrderItem.objects.filter(order__created_at__date=today).aggregate(
                waiting=Count('id', filter=Q(status='waiting')),
                cooking=Count('id', filter=Q(status='cooking')),
                ready=Count('id', filter=Q(status='ready')))
        return self._kitchen_stats_cache

    # kutilayotgan order lar yani hech bir oshpaz qabul qilmagan order lar
    def get_pending_dishes(self, obj):
        return self._get_kitchen_stats()['waiting']

    # pishirilayotgan orderlar
    def get_cooking_dishes(self, obj):
        return self._get_kitchen_stats()['cooking']

    # tayyor order lar yani oshpaz pishirib bo'lgan buyurtmalar
    def get_ready_dishes(self, obj):
        return self._get_kitchen_stats()['ready']

class OwnerOrderModelSerializer(ModelSerializer):
    table_number = CharField(source='table.number', read_only=True)
    waiter_name = CharField(source='waiter.first_name', read_only=True)

    class Meta:
        model = Order
        fields = ('id', 'table_number', 'waiter_name', 'total_price', 'status', 'created_at')


# asosiy owner dashboard serializer hammasi jamlanadigan final serializer
class OwnerDashboardSerializer(Serializer):
    today_summary = SerializerMethodField()
    live_table = SerializerMethodField()
    live_kitchen = SerializerMethodField()
    owner_order = SerializerMethodField()

    def get_today_summary(self, obj):
        return TodaySummarySerializer(obj).data

    def get_live_table(self, obj):
        return LiveTablesSerializer(obj).data

    def get_live_kitchen(self, obj):
        return LiveKitchenSerializer(obj).data

    def get_owner_order(self, obj):
        recent_orders = Order.objects.select_related('waiter', 'table').order_by('-id')[:5]
        return OwnerOrderModelSerializer(recent_orders, many=True).data


class OwnerSalaryCreateModelSerializer(ModelSerializer):

    class Meta:
        model = SalaryPayment
        fields = ("employee", "amount", "month", "payment_date", "payment_type",)

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['paid_by'] = request.user
        return super().create(validated_data)

    def validate(self, data):
        employee = data['employee']
        payment_date = data.get('payment_date')
        if payment_date:
            duplicate = SalaryPayment.objects.filter(
                employee=employee,
                payment_date=payment_date,
                status__in=['approved', 'paid']
            ).exists()
            if duplicate:
                raise serializers.ValidationError(
                    "Bu xodimga shu sanada allaqachon to'lov qilingan"
                )
        return data


#  comentariya
class CommentListSerializer(ModelSerializer):
    class Meta:
        model = Comment
        fields = ("id", "display_name", "text", "rating", "created_at")

class CommentCreateSerializer(Serializer):
    product_id = serializers.IntegerField()
    text = serializers.CharField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    display_name = serializers.CharField(max_length=50, required=False, default="Anonim")

    def create(self, validated_data):
        request = self.context['request']
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR')
        comment = Comment.objects.create(
            product_id=validated_data['product_id'],
            text=validated_data['text'],
            rating=validated_data['rating'],
            display_name=validated_data.get('display_name', 'Anonim'),
            ip_address=ip,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            user=request.user if request.user.is_authenticated else None,
        )
        return comment


class PaymentCreateSerializer(Serializer):
    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.filter(
            status__in=[
                Order.OrderStatusType.READY,
                Order.OrderStatusType.SERVED,  # YANGI
            ]
        )
    )
    method = ChoiceField(choices=Payment.PaymentMethod.choices)
    amount = DecimalField(max_digits=12, decimal_places=2)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Summa 0 dan katta bo'lishi kerak")
        return value


class PaymentOrderSerializer(ModelSerializer):
    table_number = serializers.IntegerField(source='table.number', read_only=True)
    waiter_name = serializers.CharField(source='waiter.first_name', read_only=True, default='')

    class Meta:
        model = Order
        fields = ('id', 'table_number', 'waiter_name', 'total_price', 'status')


class PaymentListSerializer(ModelSerializer):
    order = PaymentOrderSerializer(read_only=True)
    method_display = serializers.CharField(source='get_method_display', read_only=True)

    class Meta:
        model = Payment
        fields = (
            'id', 'order', 'method', 'method_display',
            'amount', 'status', 'paid_at', 'created_at',
        )

class ExpenseSerializer(serializers.ModelSerializer):
    added_by_name = serializers.CharField(
        source='added_by.get_full_name', read_only=True
    )
    expense_type_display = serializers.CharField(
        source='get_expense_type_display', read_only=True
    )

    class Meta:
        model = Expense
        fields = ('id', 'expense_type', 'expense_type_display',
                  'amount', 'description', 'date',
                  'added_by', 'added_by_name', 'created_at')
        read_only_fields = ('id', 'added_by', 'created_at')

    def create(self, validated_data):
        validated_data['added_by'] = self.context['request'].user
        return super().create(validated_data)

# serializers.py ga qo'shing
class FineCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fine
        fields = ('employee', 'amount', 'reason')

    def create(self, validated_data):
        validated_data['issued_by'] = self.context['request'].user
        return super().create(validated_data)

class FineListSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.get_full_name', read_only=True)
    issued_by_name = serializers.CharField(source='issued_by.get_full_name', read_only=True)

    class Meta:
        model = Fine
        fields = ('id', 'employee', 'employee_name', 'issued_by',
                  'issued_by_name', 'amount', 'reason', 'created_at', 'is_active')

class BotSerializer(serializers.ModelSerializer):
    raw_token = serializers.CharField(write_only=True, required=True)
    bot_username = serializers.CharField(read_only=True)
    bot_name = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    webhook_set = serializers.BooleanField(read_only=True)

    class Meta:
        model = RestaurantBot
        fields = (
            'id', 'bot_type', 'raw_token',
            'bot_username', 'bot_name',
            'is_active', 'webhook_set',
            'created_at',
        )
        read_only_fields = ('id', 'bot_username', 'bot_name', 'is_active', 'webhook_set', 'created_at')

    def create(self, validated_data):
        raw_token = validated_data.pop('raw_token')
        request = self.context['request']

        import httpx
        try:
            resp = httpx.get(f"https://api.telegram.org/bot{raw_token}/getMe", timeout=8)
            resp.raise_for_status()
            info = resp.json()['result']
        except Exception:
            raise serializers.ValidationError({"raw_token": "Token noto'g'ri yoki Telegram ulanmadi"})

        bot = RestaurantBot(
            restaurant=RestaurantInfo.objects.first(),
            bot_type=validated_data.get('bot_type', RestaurantBot.BotType.CUSTOMER),
            bot_username=info.get('username', ''),
            bot_name=info.get('first_name', ''),
            added_by=request.user,
        )
        bot.set_token(raw_token)
        bot.save()
        set_webhook(bot, raw_token, request)
        return bot

class SalaryScheduleSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.get_full_name', read_only=True)
    payment_days = serializers.SerializerMethodField()

    class Meta:
        model = SalarySchedule
        fields = ('id', 'employee', 'employee_name', 'frequency', 'start_day',
                  'payment_days', 'updated_at')
        read_only_fields = ('id', 'updated_at')

    def get_payment_days(self, obj):
        return obj.get_payment_days()

    def validate_frequency(self, value):
        if value not in (1, 2, 4):
            raise serializers.ValidationError("Chastota faqat 1, 2 yoki 4 bo'lishi mumkin")
        return value

    def validate_start_day(self, value):
        if not (1 <= value <= 28):
            raise serializers.ValidationError("Boshlanish kuni 1 dan 28 gacha bo'lishi kerak")
        return value

    def create(self, validated_data):
        validated_data['set_by'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['set_by'] = self.context['request'].user
        return super().update(instance, validated_data)


class EmployeeSalaryInfoSerializer(serializers.ModelSerializer):
    """Hisobchi panelida har bir xodim qatorida ko'rsatish uchun — schedule + necha marta to'langani"""
    schedule_frequency = serializers.SerializerMethodField()
    schedule_start_day = serializers.SerializerMethodField()
    payment_days = serializers.SerializerMethodField()
    is_override = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "first_name", "last_name", "role", "phone_number",
                  "is_at_work", "shift", "base_salary", "fine_balance", "photo",
                  "schedule_frequency", "schedule_start_day", "payment_days", "is_override")

    def _get_restaurant_default(self):
        return RestaurantInfo.objects.first()

    def get_schedule_frequency(self, obj):
        if hasattr(obj, 'salary_schedule'):
            return obj.salary_schedule.frequency
        rest = self._get_restaurant_default()
        return rest.default_salary_frequency if rest else 1

    def get_schedule_start_day(self, obj):
        if hasattr(obj, 'salary_schedule'):
            return obj.salary_schedule.start_day
        rest = self._get_restaurant_default()
        return rest.default_salary_start_day if rest else 1

    def get_payment_days(self, obj):
        freq = self.get_schedule_frequency(obj)
        day = self.get_schedule_start_day(obj)
        return compute_payment_days(freq, day)

    def get_is_override(self, obj):
        return hasattr(obj, 'salary_schedule')

class RestaurantInfoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantInfo
        fields = (
            'id', 'name', 'slogan', 'description',
            'address', 'phone', 'email',
            'instagram', 'telegram',
            'open_time', 'close_time',
            'hero_image', 'logo',
            'bot_username',
            'default_salary_frequency', 'default_salary_start_day',
        )
        read_only_fields = ('id',)




#         shaxsiy admin panel uchun kelajak dagi kerak bo'ladigan serializer
class LinkSerializer(ModelSerializer):
    class Meta:
        model = Link
        fields = ['id', 'title', 'url', 'icon', 'order', 'is_active']


class SocialLinkSerializer(ModelSerializer):
    platform_display = CharField(source='get_platform_display', read_only=True)

    class Meta:
        model = SocialLink
        fields = ['id', 'platform', 'platform_display', 'url', 'order']


class ProfileSerializer(ModelSerializer):
    links = LinkSerializer(many=True, read_only=True)
    socials = SocialLinkSerializer(many=True, read_only=True)

    class Meta:
        model = Profile
        fields = ['id', 'name', 'bio', 'photo', 'is_active', 'links', 'socials']
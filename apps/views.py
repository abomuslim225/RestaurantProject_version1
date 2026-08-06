import random
from datetime import timedelta

from django.db.models.functions import TruncWeek, TruncHour

from django.db.models import Count, Sum, Q, ExpressionWrapper, F, DecimalField
from django.contrib.auth import login
from django.db.models import Prefetch
from django.db.models.functions import TruncDate
from django.utils.dateparse import parse_date

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from apps.tasks import process_telegram_update
from apps.consumers import broadcast_order_status
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.http import JsonResponse
from django_filters.rest_framework import DjangoFilterBackend
from redis import Redis
from rest_framework.filters import SearchFilter
from rest_framework.generics import ListAPIView, CreateAPIView, GenericAPIView, RetrieveUpdateDestroyAPIView, \
    ListCreateAPIView, DestroyAPIView, RetrieveUpdateAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_201_CREATED
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from apps.filters import OrderFilter
from apps.models import Product, Category, Recipe, Ingredient, User, Order, OrderItem, TableSession, Table, \
    SalaryPayment, Notification, Reservation, TableQRCode, DailyIngredientReport, Comment, Gallery, RestaurantInfo, \
    IngredientPurchase, Payment, ChefDailyTakeout, OrderPaymentProof, RestaurantBot, ManagerAlert, DeviceRemovalRequest, \
    EmployeeLoginSession, Fine, IngredientTransaction, SalarySchedule, Expense, SocialLink, Link, Profile
from apps.permissions import IsOwner, IsManager, IsChef, IsWaiter, IsCashier, IsAccountant, IsMe
from apps.send import send_email
from apps.serializers import MenuProductModelSerializer, MenuCategoryModelSerializer, OrderCreateSerializer, \
    ProductModelSerializer, RecipeModelSerializer, IngredientModelSerializer, CreateEmployeeModelSerializer, \
    UserModelSerializer, RegisterUserModelSerializer, LoginUserModelSerializer, ManagerModelSerializer, \
    OtpVerifySerializer, SendEmailSerializer, UserUpdateModelSerializer, EmployeeModelSerializer, \
    EmployeeListModelSerializer, TableSessionCreateModelSerializer, TableModelSerializer, OrderModelSerializer, \
    OwnerSalaryPaymentModelSerializer, EmployeeLoginSerializer, NotificationSerializer, \
    ReservationCreateModelSerializer, TableRUDModelSerializer, CategoryModelSerializer, TableQRCodeCreateSerializer, \
    TableQRCodeListSerializer, DailyIngredientReportSerializer, OwnerDashboardSerializer, \
    OwnerSalaryCreateModelSerializer, CommentListSerializer, CommentCreateSerializer, RestaurantInfoSerializer, \
    GallerySerializer, ResetPasswordSerializer, IngredientPurchaseSerializer, PaymentCreateSerializer, \
    PaymentListSerializer, ChefDailyTakeoutSerializer, BotSerializer, RestaurantInfoUpdateSerializer, \
    ManagerAlertSerializer, TableSessionListSerializer, LoginSessionSerializer, TableQRCodeDeleteSerializer, \
    FineCreateSerializer, FineListSerializer, IngredientTransactionSerializer, SalaryScheduleSerializer, \
    EmployeeSalaryInfoSerializer, ExpenseSerializer, SocialLinkSerializer, LinkSerializer, ProfileSerializer
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone

from apps.utils import set_webhook


# Restoran haqida umumiy ma'lumotni (nomi, manzil, ish vaqti va h.k.) qaytaradi.
# Returns general restaurant information (name, address, working hours, etc.).
class RestaurantInfoAPIView(RetrieveAPIView):
    serializer_class = RestaurantInfoSerializer

    def get_object(self):
        return RestaurantInfo.objects.first()


# Restoran galereya rasmlarining to'liq ro'yxatini qaytaradi.
# Returns the full list of restaurant gallery images.
class GalleryListAPIView(ListAPIView):
    queryset = Gallery.objects.all()
    serializer_class = GallerySerializer


# Menyudagi barcha mahsulotlarni ro'yxatini qaytaradi; kategoriya bo'yicha filterlash va nom/tavsif bo'yicha qidiruv imkoniyati mavjud.
# Returns all menu products with support for category filtering and name/description search.
class MenuListAPIView(ListAPIView):
    queryset = Product.objects.all()
    serializer_class = MenuProductModelSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'price']
    ordering = ['name']  # default a-z


class MenuCategoriesAPIView(ListAPIView):
    queryset = Category.objects.all()
    serializer_class = MenuCategoryModelSerializer


class FeaturedProductListAPIView(ListAPIView):
    queryset = Product.objects.filter(is_featured=True)
    serializer_class = MenuProductModelSerializer





class OrdersPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'


def _get_period_range(period: str):
    today = timezone.now().date()
    if period == 'daily':
        return today, today
    elif period == 'weekly':
        date_from = today - timedelta(days=today.weekday())  # shu haftaning dushanbasi
        return date_from, today
    elif period == 'monthly':
        return today.replace(day=1), today
    return today, today


def _resolve_date_range(request):

    raw_from = request.query_params.get('date_from')
    raw_to = request.query_params.get('date_to')

    if raw_from and raw_to:
        date_from = parse_date(raw_from)
        date_to = parse_date(raw_to)
        if date_from and date_to:
            if date_from > date_to:
                date_from, date_to = date_to, date_from
            return date_from, date_to, None

    period = request.query_params.get('period', 'daily')
    if period not in ('daily', 'weekly', 'monthly'):
        period = 'daily'
    date_from, date_to = _get_period_range(period)
    return date_from, date_to, period


class OrderStatsCardsAPIView(APIView):

    permission_classes = [IsOwner | IsManager]

    def get(self, request):
        date_from, date_to, period = _resolve_date_range(request)

        orders_qs = Order.objects.filter(created_at__date__range=(date_from, date_to))

        total_orders = orders_qs.count()
        paid_orders = orders_qs.filter(status=Order.OrderStatusType.PAID).count()
        unpaid_orders = orders_qs.exclude(
            status__in=[Order.OrderStatusType.PAID, Order.OrderStatusType.CANCELED]
        ).count()
        canceled_orders = orders_qs.filter(status=Order.OrderStatusType.CANCELED).count()

        payments = Payment.objects.filter(
            status=Payment.PaymentStatus.COMPLETED,
            paid_at__date__range=(date_from, date_to),
        )
        cash = float(payments.filter(method='cash').aggregate(t=Sum('amount'))['t'] or 0)
        card = float(payments.filter(method='card').aggregate(t=Sum('amount'))['t'] or 0)
        online = float(payments.filter(method='online').aggregate(t=Sum('amount'))['t'] or 0)
        total_revenue = cash + card + online

        return Response({
            'period': period,  # custom range bo'lsa None bo'ladi
            'date_from': date_from,
            'date_to': date_to,
            'total_orders': total_orders,
            'paid_orders': paid_orders,
            'unpaid_orders': unpaid_orders,
            'canceled_orders': canceled_orders,
            'revenue': {
                'cash': cash,
                'card': card,
                'online': online,
                'total': total_revenue,
            },
            'payment_counts': {
                'cash': payments.filter(method='cash').count(),
                'card': payments.filter(method='card').count(),
                'online': payments.filter(method='online').count(),
            },
        })


class OrderPeriodListAPIView(ListAPIView):

    serializer_class = OrderModelSerializer
    permission_classes = [IsOwner | IsManager]
    pagination_class = OrdersPagination

    def get_queryset(self):
        date_from, date_to, _period = _resolve_date_range(self.request)
        return (
            Order.objects
            .filter(created_at__date__range=(date_from, date_to))
            .select_related('table', 'waiter')
            .prefetch_related(Prefetch('order_items', queryset=OrderItem.objects.select_related('product', 'chef')))
            .order_by('-created_at')
        )

class OrderRequestCreateAPIView(CreateAPIView):
    serializer_class = OrderCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        # Faqat shu stolning waiter'iga WebSocket xabari
        if order.waiter_id:
            items = [
                {
                    'order_item_id': item.id,
                    'product_id': item.product_id,
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                }
                for item in order.order_items.select_related('product').all()
            ]
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"waiter_{order.waiter_id}",
                {
                    'type': 'new_order',
                    'order_id': order.id,
                    'table_id': order.table_id,
                    'table_number': order.table.number,
                    'total_price': str(order.total_price),
                    'comment': order.comment,
                    'items': items,
                }
            )

        return Response({
            'id': order.id,
            'payment_type': order.payment_type,
            'total_price': str(order.total_price),
        }, status=HTTP_201_CREATED)


class OrderPaymentProofAPIView(GenericAPIView):

    permission_classes = [IsWaiter | IsManager | IsOwner]

    def get(self, request, pk):
        # Avval tasdiqlanmagan, keyin tasdiqlangan — ikkalasini ham qaytaramiz
        proof = OrderPaymentProof.objects.filter(
            order_id=pk
        ).order_by('-submitted_at').first()

        if not proof:
            return Response({'detail': 'Chek topilmadi'}, status=404)

        return Response({
            'id': proof.id,
            'order_id': int(pk),
            'photo_file_id': proof.photo_file_id,
            'photo_url': proof.photo.url if proof.photo else None,
            'submitted_at': proof.submitted_at,
            'is_confirmed': proof.is_confirmed,
        })

    def post(self, request, pk):
        try:
            order = Order.objects.select_related('table').get(id=pk)
        except Order.DoesNotExist:
            return Response({'error': 'Order topilmadi'}, status=404)

        if order.status == Order.OrderStatusType.PAID:
            return Response({'error': "Allaqachon to'langan"}, status=400)

        order.status = Order.OrderStatusType.PAID
        order.save(update_fields=['status'])

        Payment.objects.create(
            order=order,
            method=Payment.PaymentMethod.ONLINE,
            status=Payment.PaymentStatus.COMPLETED,
            amount=order.total_price,
            paid_at=timezone.now(),
        )

        OrderPaymentProof.objects.filter(order=order).update(is_confirmed=True)

        broadcast_order_status(order.id, 'delivered')

        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            "cashiers",
            {
                'type': 'order_paid',
                'order_id': order.id,
                'table_number': order.table.number,
                'amount': str(order.total_price),
                'method': 'online',
                'paid_by': "Telegram (bank o'tkazma)",
            }
        )
        async_to_sync(channel_layer.group_send)(
            "managers",
            {
                'type': 'order_paid',
                'order_id': order.id,
                'table_number': order.table.number,
                'amount': str(order.total_price),
                'method': 'online',
            }
        )

        return Response({
            'message': 'Tasdiqlandi',
            'order_id': order.id,
            'status': order.status,
        })

class OrderStatusAPIView(RetrieveAPIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            order = Order.objects.get(id=pk)
        except Order.DoesNotExist:
            return Response({'error': 'Order topilmadi'}, status=404)
        return Response({
            'id': order.id,
            'status': order.status,
            'payment_type': order.payment_type,
            'total_price': str(order.total_price),
        })

class MyOrderProofsListAPIView(ListAPIView):
    """Waiter ning barcha orderlaridagi cheklar ro'yxati"""
    permission_classes = [IsWaiter | IsManager | IsOwner]

    def get(self, request):
        # Waiter ning orderlarini olish
        waiter_order_ids = Order.objects.filter(
            waiter=request.user
        ).values_list('id', flat=True)

        proofs = OrderPaymentProof.objects.filter(
            order_id__in=waiter_order_ids
        ).select_related('order__table').order_by('-submitted_at')

        data = [{
            'id':            p.id,
            'order_id':      p.order.id,
            'table_number':  p.order.table.number,
            'photo_url':     p.photo.url if p.photo else None,
            'photo_file_id': p.photo_file_id,
            'submitted_at':  p.submitted_at,
            'is_confirmed':  p.is_confirmed,
            'payment_type':  p.order.payment_type,
            'total_price':   str(p.order.total_price),
        } for p in proofs]

        return Response(data)

class CategoryCreateListAPIView(ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategoryModelSerializer


class CategoryRUDApiView(RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategoryModelSerializer
    permission_classes = [IsOwner | IsManager]
    lookup_field = "pk"


class ProductListAPIView(ListCreateAPIView):
    queryset = Product.objects.prefetch_related(
        Prefetch('recipes', queryset=Recipe.objects.select_related('ingredient'))
    ).all()
    serializer_class = ProductModelSerializer


class ProductRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductModelSerializer
    lookup_field = "pk"


class CommentAnonThrottle(AnonRateThrottle):
    scope = 'comment_anon'


class CommentUserThrottle(UserRateThrottle):
    scope = 'comment_user'


class ProductCommentsAPIView(ListAPIView):
    serializer_class = CommentListSerializer

    def get_queryset(self):
        return Comment.objects.filter(
            product_id=self.kwargs['pk'],
            is_blocked=False
        ).order_by('-created_at')


class CommentCreateAPIView(CreateAPIView):
    serializer_class = CommentCreateSerializer
    throttle_classes = [CommentAnonThrottle, CommentUserThrottle]


class RecipeCreateAPIView(CreateAPIView):
    queryset = Recipe.objects.all()
    serializer_class = RecipeModelSerializer


class RecipeListAPIView(ListAPIView):
    queryset = Recipe.objects.all()
    serializer_class = RecipeModelSerializer


class RecipeRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = Recipe.objects.all()
    serializer_class = RecipeModelSerializer
    lookup_field = 'pk'


# Barcha ingredientlarni ko'rish va yangi ingredient qo'shish imkonini beradi.
# Lists all ingredients and allows adding a new one.
class IngredientCreateAPIView(ListCreateAPIView):
    queryset = Ingredient.objects.all()
    serializer_class = IngredientModelSerializer


class IngredientRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = Ingredient.objects.all()
    serializer_class = IngredientModelSerializer
    lookup_field = "pk"


class IngredientTransactionListAPIView(ListAPIView):
    serializer_class = IngredientTransactionSerializer
    permission_classes = [IsAccountant | IsManager | IsOwner]

    def get_queryset(self):
        return IngredientTransaction.objects.filter(
            performed_by=self.request.user
        ).select_related('ingredient').order_by('-created_at')[:100]


# Ingredient xaridlari tarixini ko'rish va yangi xarid qayd etish imkonini beradi (ombor boshqaruvi uchun).
# Lists ingredient purchase history and allows recording a new purchase (for stock management).
class IngredientPurchaseListCreateAPIView(ListCreateAPIView):
    queryset = IngredientPurchase.objects.select_related('ingredient', 'purchased_by').order_by('-purchased_at')
    serializer_class = IngredientPurchaseSerializer
    permission_classes = [IsOwner | IsManager | IsAccountant]

# Xodim tizimga kiradi va JWT access hamda refresh tokenlarni, shuningdek xodim profilini qaytaradi.
# Logs in an employee and returns JWT access/refresh tokens along with the employee's profile data.
class EmployeeTokenAPIView(GenericAPIView):
    serializer_class = EmployeeLoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        login(request, user)
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone_number': user.phone_number,
                'role': user.role,
                'is_at_work': user.is_at_work,
                'base_salary': str(user.base_salary),
                'fine_balance': str(user.fine_balance),
                'shift': user.shift,
                'bank_card': user.bank_card or '',
            }
        })


class EmployeeCreateAPIView(ListCreateAPIView):
    queryset = User.objects.all()
    serializer_class = CreateEmployeeModelSerializer


class EmployeeLoginAPIView(GenericAPIView):
    queryset = User.objects.all()
    serializer_class = EmployeeLoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']

        return Response({
            "id": user.id,
            "phone_number": user.phone_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
        })


class EmployeeDestroyAPIView(DestroyAPIView):
    queryset = User.objects.exclude(role=User.RoleChoice.CUSTOMER)
    serializer_class = EmployeeModelSerializer
    permission_classes = [IsManager | IsOwner]


class EmployeeUpdateAPIView(RetrieveUpdateAPIView):
    queryset = User.objects.exclude(role=User.RoleChoice.CUSTOMER)
    serializer_class = EmployeeModelSerializer


class EmployeeListAPIView(ListAPIView):
    queryset = User.objects.exclude(role=User.RoleChoice.CUSTOMER)
    serializer_class = EmployeeListModelSerializer
    permission_classes = [IsAccountant | IsManager | IsOwner]


# 1. Barcha devicelarni ko'rish
class MyDevicesListAPIView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LoginSessionSerializer

    def get_queryset(self):
        return EmployeeLoginSession.objects.filter(
            user=self.request.user,
            is_active=True
        )


# 2. Device o'chirish so'rovi → email ketadi
class DeviceRemovalRequestAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        # Session mavjudligini tekshir
        try:
            session = EmployeeLoginSession.objects.get(
                id=session_id,
                user=request.user,  # faqat o'zining devicei
                is_active=True
            )
        except EmployeeLoginSession.DoesNotExist:
            return Response(
                {'error': 'Device topilmadi'},
                status=404
            )

        # Eski so'rovlarni o'chir
        DeviceRemovalRequest.objects.filter(
            session=session,
            is_used=False
        ).delete()

        # Yangi kod yarat
        code = str(random.randint(100000, 999999))
        DeviceRemovalRequest.objects.create(
            session=session,
            requested_by=request.user,
            code=code,
            expires_at=timezone.now() + timedelta(minutes=15)
        )

        # Email jo'nat
        send_email(request.user.email, code=code)

        return Response({
            'message': f'{request.user.email} ga tasdiqlash kodi yuborildi'
        })


# 3. Kodni tasdiqlash → device o'chiriladi
class DeviceRemovalConfirmAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        code = request.data.get('code')

        try:
            removal = DeviceRemovalRequest.objects.select_related(
                'session'
            ).get(
                session_id=session_id,
                requested_by=request.user,
                code=code,
                is_used=False,
                expires_at__gt=timezone.now()
            )
        except DeviceRemovalRequest.DoesNotExist:
            return Response(
                {'error': 'Kod xato yoki muddati tugagan'},
                status=400
            )

        # Device o'chir
        removal.session.is_active = False
        removal.session.save(update_fields=['is_active'])

        # Kodni ishlatilgan deb belgilab qo'y
        removal.is_used = True
        removal.save(update_fields=['is_used'])

        return Response({'message': 'Device muvaffaqiyatli o\'chirildi'})


# @method_decorator(ratelimit(key='ip', rate='1/d', block=True), name='post')
# @method_decorator(ratelimit(key='header:user-agent', rate='3/d', block=True), name='post')
class UserRegisterAPIView(CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterUserModelSerializer


class UserLoginAPIView(GenericAPIView):
    serializer_class = LoginUserModelSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            refresh = RefreshToken.for_user(user)
            return Response({"access": str(refresh.access_token),
                             "refresh": str(refresh)}, status=HTTP_200_OK)
        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)


class UserRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.filter(role=User.RoleChoice.CUSTOMER)
    serializer_class = UserUpdateModelSerializer
    lookup_field = "pk"


class ManagerOrderStatisticAPIView(ListAPIView):
    queryset = Order.objects.select_related("table", "product", "waiter").prefetch_related("order_items__chef")
    serializer_class = ManagerModelSerializer
    permission_classes = [IsManager]


class ManagerOrderListAPIView(ListAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderModelSerializer
    permission_classes = [IsCashier | IsManager | IsOwner]


class ManagerAlertListAPIView(ListAPIView):
    queryset = ManagerAlert.objects.select_related('related_user').order_by('-created_at')[:100]
    serializer_class = ManagerAlertSerializer


class VerifyEmailAPIView(GenericAPIView):
    serializer_class = SendEmailSerializer

    def post(self, request):
        serializer = SendEmailSerializer(data=request.data)
        if not serializer.is_valid():
            return JsonResponse(serializer.errors, status=HTTP_400_BAD_REQUEST)
        email = serializer.validated_data["email"]
        code = random.randint(100000, 999999)
        send_email(email, code=code)
        redis = Redis()
        redis.mset({email: code})
        redis.expire(email, time=900)
        # redis = Redis()

        return JsonResponse({"message": "tasdiqlash code jo'natildi"}, status=HTTP_200_OK)


class VerifyOtpCodeAPIView(APIView):
    serializer_class = OtpVerifySerializer

    def post(self, request):
        serializer = OtpVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return JsonResponse(serializer.errors, safe=False, status=HTTP_400_BAD_REQUEST)
        return JsonResponse({"message": "otp code success"}, status=HTTP_200_OK)


class ResetPasswordAPIView(GenericAPIView):
    serializer_class = ResetPasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        email = serializer.validated_data.get('email').strip().lower()
        password = serializer.validated_data.get('new_password')
        try:
            user = User.objects.get(email__iexact=email)
            user.set_password(password)

            if hasattr(user, 'temporary_password'):
                user.temporary_password = None

            user.save()
            return Response({'message': 'Parol muvaffaqiyatli yangilandi'}, status=HTTP_200_OK)
        except User.DoesNotExist:
            return Response({'error': 'Foydalanuvchi topilmadi'}, status=400)


class TableCreateListAPIView(ListCreateAPIView):
    queryset = Table.objects.all().order_by('number')
    serializer_class = TableModelSerializer


class TableRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = Table.objects.all()
    serializer_class = TableRUDModelSerializer
    lookup_field = "pk"


class TableSessionCreateAPIView(CreateAPIView):
    queryset = TableSession.objects.all()
    serializer_class = TableSessionCreateModelSerializer
    permission_classes = [IsWaiter | IsOwner | IsManager]

    def patch(self, request, *args, **kwargs):
        session = TableSession.objects.get(pk=kwargs['pk'])
        session.is_active = False
        session.ended_at = timezone.now()
        session.save(update_fields=['is_active', 'ended_at'])
        return Response({'message': 'Session yopildi'})


class TableSessionListAPIView(ListAPIView):
    queryset = TableSession.objects.filter(is_active=True).select_related('table', 'waiter')
    serializer_class = TableSessionListSerializer


class TableSessionRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = TableSession.objects.all()
    serializer_class = TableSessionCreateModelSerializer
    permission_classes = [IsWaiter]
    lookup_field = "pk"

    def perform_update(self, serializer):
        instance = serializer.instance
        is_active = self.request.data.get('is_active')
        if is_active is False or is_active == 'false':
            serializer.save(is_active=False, ended_at=timezone.now())
        else:
            serializer.save()


class OwnerOrderStatisticsListAPIView(ListAPIView):
    queryset = (Order.objects.select_related("table", "waiter").prefetch_related(
        Prefetch("order_items", queryset=OrderItem.objects.select_related("product", "chef"))))
    serializer_class = OrderModelSerializer
    permission_classes = [IsOwner | IsManager | IsWaiter]
    filter_backends = [DjangoFilterBackend]
    filterset_class = OrderFilter


class OwnerSalaryPaymentListAPIView(ListAPIView):
    queryset = SalaryPayment.objects.select_related("employee", "paid_by")
    serializer_class = OwnerSalaryPaymentModelSerializer
    permission_classes = [IsOwner]


class OwnerDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated, IsOwner]

    def get(self, request):
        period = request.query_params.get('period', 'weekly')  # daily/weekly/monthly

        today = timezone.now().date()

        if period == 'daily':
            # Bugun soat bo'yicha

            data = (
                Payment.objects
                .filter(status=Payment.PaymentStatus.COMPLETED, paid_at__date=today)
                .annotate(label=TruncHour('paid_at'))
                .values('label')
                .annotate(total=Sum('amount'))
                .order_by('label')
            )
            labels = [d['label'].strftime('%H:00') for d in data]
            profit = [float(d['total']) for d in data]

        elif period == 'weekly':
            # So'nggi 7 kun

            days = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
            data_map = {
                d['label']: float(d['total'])
                for d in Payment.objects
                .filter(status=Payment.PaymentStatus.COMPLETED, paid_at__date__gte=days[0])
                .annotate(label=TruncDate('paid_at'))
                .values('label')
                .annotate(total=Sum('amount'))
            }
            day_names = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']
            labels = [day_names[d.weekday()] for d in days]
            profit = [data_map.get(d, 0) for d in days]

        elif period == 'monthly':
            # So'nggi 4 hafta

            data = (
                Payment.objects
                .filter(status=Payment.PaymentStatus.COMPLETED,
                        paid_at__date__gte=today - timedelta(weeks=4))
                .annotate(label=TruncWeek('paid_at'))
                .values('label')
                .annotate(total=Sum('amount'))
                .order_by('label')
            )
            labels = [f"{i + 1}-hafta" for i in range(len(data))]
            profit = [float(d['total']) for d in data]

        # Xarajatlar (IngredientPurchase)
        if period == 'daily':
            loss_data = (
                IngredientPurchase.objects
                .filter(purchased_at__date=today)
                .annotate(label=TruncHour('purchased_at'))
                .values('label')
                .annotate(total=Sum('total_price'))
                .order_by('label')
            )
            loss_map = {d['label'].strftime('%H:00'): float(d['total']) for d in loss_data}
            loss = [loss_map.get(l, 0) for l in labels]
        elif period == 'weekly':
            loss_data_map = {
                d['label']: float(d['total'])
                for d in IngredientPurchase.objects
                .filter(purchased_at__date__gte=days[0])
                .annotate(label=TruncDate('purchased_at'))
                .values('label')
                .annotate(total=Sum('total_price'))
            }
            loss = [loss_data_map.get(d, 0) for d in days]
        else:
            loss_data = (
                IngredientPurchase.objects
                .filter(purchased_at__date__gte=today - timedelta(weeks=4))
                .annotate(label=TruncWeek('purchased_at'))
                .values('label')
                .annotate(total=Sum('total_price'))
                .order_by('label')
            )
            loss = [float(d['total']) for d in loss_data]

        total_profit = sum(profit)
        total_loss = sum(loss)


        # ── OYLIK TOP XODIMLAR (Waiter + Chef) — daromad bo'yicha kamayish tartibida ──
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month_start = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month_start = month_start.replace(month=month_start.month + 1)

        # Ofitsiantlar — shu oy ichida to'langan buyurtmalar bo'yicha
        month_filter_orders = Q(
            orders__status=Order.OrderStatusType.PAID,
            orders__created_at__gte=month_start,
            orders__created_at__lt=next_month_start,
        )
        waiters_qs = (
            User.objects.filter(role=User.RoleChoice.WAITER)
            .annotate(
                order_count=Count('orders', filter=month_filter_orders),
                revenue=Sum('orders__total_price', filter=month_filter_orders),
            )
            .filter(order_count__gt=0)
        )

        # Oshpazlar — shu oy ichida pishirilgan va to'langan taomlar bo'yicha
        month_filter_items = Q(
            order_items__order__status=Order.OrderStatusType.PAID,
            order_items__order__created_at__gte=month_start,
            order_items__order__created_at__lt=next_month_start,
        )
        chefs_qs = (
            User.objects.filter(role=User.RoleChoice.CHEF)
            .annotate(
                order_count=Count('order_items', filter=month_filter_items),
                revenue=Sum(
                    ExpressionWrapper(
                        F('order_items__product__price') * F('order_items__quantity'),
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    ),
                    filter=month_filter_items,
                ),
            )
            .filter(order_count__gt=0)
        )

        combined_staff = [
            {
                'name': f"{s.first_name} {s.last_name}",
                'role': s.role,
                'order_count': s.order_count or 0,
                'revenue': float(s.revenue or 0),
            }
            for s in list(waiters_qs) + list(chefs_qs)
        ]
        # Daromad bo'yicha kamayish tartibida, teng bo'lsa order_count bo'yicha
        combined_staff.sort(key=lambda x: (x['revenue'], x['order_count']), reverse=True)
        top_staff = combined_staff[:5]

        return Response({
            # KPI
            'today_revenue': _today_revenue(),
            'today_orders': _today_orders_count(),
            'occupied_tables': _occupied_tables(),
            'total_tables': Table.objects.count(),
            'staff_at_work': _staff_at_work(),
            'waiting_items': _waiting_items(),
            'cooking_items': OrderItem.objects.filter(status=OrderItem.ItemStatus.COOKING).count(),
            'ready_items': OrderItem.objects.filter(status=OrderItem.ItemStatus.READY).count(),
            # Chart
            'chart': {
                'labels': labels,
                'profit': profit,
                'loss': loss,
                'total_profit': total_profit,
                'total_loss': total_loss,
            },
            # Top staff
            'top_staff': top_staff,
            # Banner
            'total_staff': User.objects.exclude(role=User.RoleChoice.CUSTOMER).count(),
        })


class NotificationListAPIView(ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user, is_read=False).order_by("-created_at")


class ReservationCreateAPIView(ListCreateAPIView):
    queryset = Reservation.objects.all()
    serializer_class = ReservationCreateModelSerializer
    lookup_field = 'pk'


class AccountantListAPIView(ListAPIView):
    queryset = Order.objects.filter()


class TableQRCodeListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsOwner | IsManager]

    def get_queryset(self):
        show_deleted = self.request.query_params.get('show_deleted', 'false')
        if show_deleted == 'true':
            return TableQRCode.objects.select_related(
                'table', 'deleted_by'
            ).order_by('table__number')
        # Default: faqat aktiv QR codelar
        return TableQRCode.objects.select_related(
            'table', 'deleted_by'
        ).filter(is_deleted=False).order_by('table__number')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TableQRCodeCreateSerializer
        return TableQRCodeListSerializer

    def create(self, request, *args, **kwargs):
        serializer = TableQRCodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        output = TableQRCodeListSerializer(instance, context={'request': request})
        return Response(output.data, status=HTTP_201_CREATED)


class TableQRCodeDetailAPIView(APIView):
    permission_classes = [IsOwner | IsManager]
    parser_classes = [JSONParser]

    def get_object(self, pk):
        try:
            return TableQRCode.objects.select_related(
                'table', 'deleted_by'
            ).get(pk=pk)
        except TableQRCode.DoesNotExist:
            return None

    def get(self, request, pk):
        qr = self.get_object(pk)
        if not qr:
            return Response({'error': 'QR code topilmadi'}, status=404)
        serializer = TableQRCodeListSerializer(qr, context={'request': request})
        return Response(serializer.data)

    def delete(self, request, pk):
        qr = self.get_object(pk)
        if not qr:
            return Response({'error': 'QR code topilmadi'}, status=404)

        if qr.is_deleted:
            return Response(
                {'error': 'Bu QR code allaqachon o\'chirilgan'},
                status=400
            )

        reason_serializer = TableQRCodeDeleteSerializer(data=request.data)
        reason_serializer.is_valid(raise_exception=True)

        qr.is_deleted = True
        qr.deleted_at = timezone.now()
        qr.deleted_by = request.user
        qr.deleted_reason = reason_serializer.validated_data.get('reason', '')
        qr.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'deleted_reason'])

        # Manager Alert log
        ManagerAlert.objects.create(
            alert_type=ManagerAlert.AlertType.DAILY_REPORT,  # yoki yangi type
            title=f"QR Code o'chirildi — Stol #{qr.table.number}",
            message=(
                f"{request.user.get_full_name()} tomonidan "
                f"Stol #{qr.table.number} QR kodi o'chirildi. "
                f"Sabab: {qr.deleted_reason or 'ko\'rsatilmagan'}"
            ),
            table=qr.table,
            related_user=request.user,
        )

        return Response({
            'message': f"Stol #{qr.table.number} QR kodi o'chirildi",
            'deleted_by': request.user.get_full_name(),
            'deleted_at': qr.deleted_at.isoformat(),
            'reason': qr.deleted_reason,
        })

    def patch(self, request, pk):
        qr = self.get_object(pk)
        if not qr:
            return Response({'error': 'QR code topilmadi'}, status=404)
        if not qr.is_deleted:
            return Response({'error': 'Bu QR code aktiv'}, status=400)

        # Shu stol uchun boshqa aktiv QR bormi?
        if TableQRCode.objects.filter(table=qr.table, is_deleted=False).exists():
            return Response({
                'error': f"Stol #{qr.table.number} uchun allaqachon aktiv QR kod mavjud. Avval uni o'chiring."
            }, status=400)

        qr.is_deleted = False
        qr.deleted_at = None
        qr.deleted_by = None
        qr.deleted_reason = ''
        qr.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'deleted_reason'])

        ManagerAlert.objects.create(
            alert_type=ManagerAlert.AlertType.DAILY_REPORT,
            title=f"QR Code tiklandi — Stol #{qr.table.number}",
            message=(
                f"{request.user.get_full_name()} tomonidan "
                f"Stol #{qr.table.number} QR kodi tiklandi."
            ),
            table=qr.table,
            related_user=request.user,
        )

        return Response({
            'message': f"Stol #{qr.table.number} QR kodi tiklandi",
            'restored_by': request.user.get_full_name(),
        })


class DailyReportConfirmAPIView(GenericAPIView):
    """
    Manager/Owner qo'lda tasdiqlaydi:
    {
        "report_id": 1,
        "actual_used": 80,
        "actual_closing": 20,
        "note": "Bir oz isrof bo'ldi"
    }
    """
    permission_classes = [IsManager | IsOwner]

    def post(self, request):

        report_id = request.data.get('report_id')
        actual_used = request.data.get('actual_used')
        actual_closing = request.data.get('actual_closing')
        note = request.data.get('note', '')

        try:
            report = DailyIngredientReport.objects.select_related(
                'ingredient'
            ).get(id=report_id)
        except DailyIngredientReport.DoesNotExist:
            return Response(
                {'error': 'Hisobot topilmadi'},
                status=HTTP_400_BAD_REQUEST
            )

        # Tasdiqlash
        report.actual_used = actual_used
        report.actual_closing = actual_closing
        report.note = note
        report.status = DailyIngredientReport.StatusChoice.CONFIRMED
        report.confirmed_by = request.user
        report.confirmed_at = timezone.now()
        report.save()

        # Ingredient haqiqiy miqdorini yangilash
        ingredient = report.ingredient
        ingredient.stack_amount = actual_closing
        ingredient.save(update_fields=['stack_amount'])

        return Response({
            'message': 'Tasdiqlandi',
            'ingredient': ingredient.name,
            'actual_closing': actual_closing,
        })


# Kunlik ingredient sarfi hisobotlari ro'yxatini sana bo'yicha kamayish tartibida qaytaradi.
# Returns the list of daily ingredient usage reports ordered by date descending.
class DailyReportListAPIView(ListAPIView):
    queryset = DailyIngredientReport.objects.select_related('ingredient', 'confirmed_by').order_by('-date')
    serializer_class = DailyIngredientReportSerializer


# Hozir ishda bo'lgan barcha oshpazlar ro'yxatini qaytaradi.
# Returns the list of all chefs who are currently at work.
class ChefListAPIView(ListAPIView):
    queryset = User.objects.filter(role=User.RoleChoice.CHEF, is_at_work=True)
    serializer_class = EmployeeListModelSerializer


# Oshpaz bugun ombordан olgan ingredientlarni ko'rish va yangi chiqim qayd etish imkonini beradi;
# ingredient ombor miqdorini kamaytiradi va manager/owner ga WebSocket orqali xabar yuboradi.
# Lists today's ingredient takeouts by chefs and allows recording a new one;
# decreases ingredient stock and notifies managers/owners via WebSocket.
class ChefDailyTakeoutListCreateAPIView(ListCreateAPIView):
    serializer_class = ChefDailyTakeoutSerializer
    permission_classes = [IsChef]

    def get_queryset(self):
        today = timezone.now().date()
        return ChefDailyTakeout.objects.filter(date=today)

    def perform_create(self, serializer):
        try:
            instance = serializer.save(chef=self.request.user)
        except DjangoValidationError as e:
            raise DRFValidationError({'detail': e.messages[0]})

        instance.ingredient.refresh_from_db()
        ingredient = instance.ingredient

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "managers", {
                'type': 'chef_took_ingredient',
                'chef_name': f"{self.request.user.first_name} {self.request.user.last_name}",
                'ingredient': ingredient.name,
                'amount': instance.amount,
                'unit': ingredient.stack_type,
                'remaining': ingredient.stack_amount,
            }
        )


class SalaryPaymentCreateAPIView(CreateAPIView):
    queryset = SalaryPayment.objects.all()
    serializer_class = OwnerSalaryCreateModelSerializer
    permission_classes = [IsOwner | IsManager | IsAccountant]

    def get_serializer_context(self):
        return {"request": self.request}


class SalaryPaymentListAPIView(ListAPIView):
    serializer_class = OwnerSalaryPaymentModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Owner yoki Manager barcha to'lovlarni ko'radi
        if user.role in ('owner', 'manager', 'accountant'):
            return SalaryPayment.objects.select_related('employee', 'paid_by').all()
        return SalaryPayment.objects.filter(employee=user)

class SalaryScheduleListCreateAPIView(ListCreateAPIView):
    queryset = SalarySchedule.objects.select_related('employee', 'set_by')
    serializer_class = SalaryScheduleSerializer
    permission_classes = [IsOwner]

    def get_serializer_context(self):
        return {"request": self.request}


class SalaryScheduleRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = SalarySchedule.objects.select_related('employee', 'set_by')
    serializer_class = SalaryScheduleSerializer
    permission_classes = [IsOwner]
    lookup_field = "pk"

    def get_serializer_context(self):
        return {"request": self.request}


# Hisobchi panelida xodimlar ro'yxatini schedule ma'lumoti bilan birga ko'rsatish uchun.
class EmployeeSalaryInfoListAPIView(ListAPIView):
    queryset = User.objects.exclude(role=User.RoleChoice.CUSTOMER).select_related('salary_schedule')
    serializer_class = EmployeeSalaryInfoSerializer
    permission_classes = [IsAccountant | IsManager | IsOwner]

class PaymentCreateAPIView(CreateAPIView):
    serializer_class = PaymentCreateSerializer
    permission_classes = [IsCashier]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_id = serializer.validated_data['order'].id
        method = serializer.validated_data['method']
        amount = serializer.validated_data['amount']

        # 1. Order mavjudligini tekshir
        try:
            order = Order.objects.select_related('table', 'waiter').get(
                id=order_id,
                status__in=[Order.OrderStatusType.READY, Order.OrderStatusType.SERVED],
            )
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order topilmadi yoki READY statusda emas'},
                status=HTTP_400_BAD_REQUEST,
            )

        # 2. Payment yarat
        payment = Payment.objects.create(
            order=order,
            method=method,
            status=Payment.PaymentStatus.COMPLETED,
            amount=amount,
            paid_at=timezone.now(),
        )

        # 3. Order statusini PAID ga o'tkazish
        order.status = Order.OrderStatusType.PAID
        order.payment_type = method
        order.save(update_fields=['status', 'payment_type'])

        # 4. WebSocket: barcha kassirlarga
        channel_layer = get_channel_layer()
        cashier_name = (
                f"{request.user.first_name} {request.user.last_name}".strip()
                or request.user.username
        )
        async_to_sync(channel_layer.group_send)(
            "cashiers",
            {
                'type': 'order_paid',
                'order_id': order.id,
                'table_number': order.table.number,
                'amount': str(amount),
                'method': method,
                'paid_by': cashier_name,
            }
        )

        # 5. WebSocket: manager/owner ga ham xabar
        async_to_sync(channel_layer.group_send)(
            "managers",
            {
                'type': 'order_paid',  # ManagerConsumer da shu handler kerak
                'order_id': order.id,
                'table_number': order.table.number,
                'amount': str(amount),
                'method': method,
            }
        )

        # 6. Owner dashboard yangilash
        async_to_sync(channel_layer.group_send)(
            "owner_dashboard",
            {
                'type': 'dashboard_update',
                'today_orders': _today_orders_count(),
                'today_revenue': str(_today_revenue()),
                'occupied_tables': _occupied_tables(),
                'waiting_items': _waiting_items(),
                'staff_at_work': _staff_at_work(),
            }
        )

        return Response(
            {
                'payment_id': payment.id,
                'order_id': order.id,
                'amount': str(payment.amount),
                'method': payment.method,
                'status': payment.status,
                'paid_at': payment.paid_at.isoformat(),
            },
            status=HTTP_201_CREATED,
        )


# Kassir uchun bugungi yakunlangan (COMPLETED) to'lovlar ro'yxatini eng yangiidan boshlab qaytaradi.
# Returns today's list of completed payments for the cashier, ordered by newest first.
class PaymentListAPIView(ListAPIView):
    serializer_class = PaymentListSerializer
    permission_classes = [IsCashier | IsAccountant | IsManager | IsOwner]

    def get_queryset(self):
        today = timezone.now().date()
        return (
            Payment.objects
            .filter(
                status=Payment.PaymentStatus.COMPLETED,
                paid_at__isnull=False,
                paid_at__date=today,
            )
            .select_related('order__table', 'order__waiter')
            .order_by('-paid_at')
        )

# ── COGS HELPER ───────────────────────────────────────────
def calculate_cogs(date_from, date_to):
    """Sotilgan mahsulotlar tannarxi"""
    items = OrderItem.objects.filter(
        order__status='paid',
        order__created_at__date__range=(date_from, date_to)
    ).prefetch_related(
        'product__recipes__ingredient__purchases'
    )

    total_cogs = 0.0
    for item in items:
        for recipe in item.product.recipes.all():
            if not recipe.ingredient:
                continue
            last_purchase = IngredientPurchase.objects.filter(
                ingredient=recipe.ingredient
            ).order_by('-purchased_at').first()

            if last_purchase and last_purchase.quantity:
                unit_cost = float(last_purchase.unit_price)
                used = recipe.amount_in_stock_unit * item.quantity
                total_cogs += used * unit_cost

    return round(total_cogs, 2)


# ── EXPENSE VIEW ──────────────────────────────────────────
class ExpenseListCreateAPIView(ListCreateAPIView):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAccountant | IsManager | IsOwner]

    def get_queryset(self):
        qs = Expense.objects.select_related('added_by')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def get_serializer_context(self):
        return {'request': self.request}


class ExpenseDestroyAPIView(DestroyAPIView):
    queryset = Expense.objects.all()
    permission_classes = [IsAccountant | IsOwner]


# ── PROFIT REPORT VIEW ────────────────────────────────────
class ProfitReportAPIView(APIView):
    permission_classes = [IsAccountant | IsManager | IsOwner]

    def get(self, request):
        today = timezone.now().date()
        period = request.query_params.get('period', 'today')

        if period == 'today':
            date_from = date_to = today
        elif period == 'week':
            date_from = today - timedelta(days=7)
            date_to = today
        elif period == 'month':
            date_from = today.replace(day=1)
            date_to = today
        else:
            date_from = date_to = today

        # Kirim
        payments = Payment.objects.filter(
            status=Payment.PaymentStatus.COMPLETED,
            paid_at__isnull=False,
            paid_at__date__range=(date_from, date_to)
        )
        income_cash   = float(payments.filter(method='cash').aggregate(t=Sum('amount'))['t'] or 0)
        income_card   = float(payments.filter(method='card').aggregate(t=Sum('amount'))['t'] or 0)
        income_online = float(payments.filter(method='online').aggregate(t=Sum('amount'))['t'] or 0)
        total_income  = income_cash + income_card + income_online

        # Chiqim
        ingredient_cost = float(
            IngredientPurchase.objects.filter(
                purchased_at__date__range=(date_from, date_to)
            ).aggregate(t=Sum('total_price'))['t'] or 0
        )
        salary_cost = float(
            SalaryPayment.objects.filter(
                status__in=['approved', 'paid'],
                payment_date__range=(date_from, date_to)
            ).aggregate(t=Sum('amount'))['t'] or 0
        )
        expense_cost = float(
            Expense.objects.filter(
                date__range=(date_from, date_to)
            ).aggregate(t=Sum('amount'))['t'] or 0
        )

        # Tannarx (COGS)
        cogs = calculate_cogs(date_from, date_to)

        total_expense = ingredient_cost + salary_cost + expense_cost
        gross_profit  = total_income - cogs          # Yalpi foyda
        net_profit    = total_income - total_expense  # Sof foyda
        margin = round(gross_profit / total_income * 100, 1) if total_income else 0

        return Response({
            'period': period,
            'date_from': date_from,
            'date_to': date_to,
            'income': {
                'cash': income_cash,
                'card': income_card,
                'online': income_online,
                'total': total_income,
            },
            'expense': {
                'ingredient': ingredient_cost,
                'salary': salary_cost,
                'other': expense_cost,
                'total': total_expense,
            },
            'cogs': cogs,
            'gross_profit': gross_profit,
            'net_profit': net_profit,
            'margin_pct': margin,
        })

class FineListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsManager | IsOwner]

    def get_queryset(self):
        emp_id = self.request.query_params.get('employee')
        qs = Fine.objects.select_related('employee', 'issued_by')
        if emp_id:
            qs = qs.filter(employee_id=emp_id)
        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return FineCreateSerializer
        return FineListSerializer


class FineDestroyAPIView(DestroyAPIView):
    queryset = Fine.objects.all()
    permission_classes = [IsOwner]

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        # fine_balance ni qayta hisoblash signal orqali bo'ladi
        instance.employee.save()  # signal triggerlash uchun


# ── Helper funksiyalar (owner dashboard uchun) ─────────────────────────

# Bugun yaratilgan buyurtmalar sonini qaytaradi.
# Returns the total number of orders created today.
def _today_orders_count():
    today = timezone.now().date()
    return Order.objects.filter(created_at__date=today).count()


# Bugungi yakunlangan to'lovlarning umumiy summasini qaytaradi.
# Returns the total revenue from completed payments today.
def _today_revenue():
    from django.db.models import Sum
    today = timezone.now().date()
    result = Payment.objects.filter(
        status=Payment.PaymentStatus.COMPLETED,
        paid_at__date=today,
    ).aggregate(total=Sum('amount'))
    return result['total'] or 0


# Hozir band bo'lgan stollar sonini qaytaradi.
# Returns the number of currently occupied tables.
def _occupied_tables():
    from apps.models import Table
    return Table.objects.filter(is_occupied=True).count()


# Hozir kutilayotgan (WAITING statusidagi) buyurtma elementlari sonini qaytaradi.
# Returns the number of order items currently in WAITING status.
def _waiting_items():
    from apps.models import OrderItem
    return OrderItem.objects.filter(status=OrderItem.ItemStatus.WAITING).count()


# Hozir ishda bo'lgan xodimlar sonini qaytaradi (mijozlarni hisobga olmaydi).
# Returns the number of staff currently at work (excluding customers).
def _staff_at_work():
    from apps.models import User
    return User.objects.filter(is_at_work=True).exclude(role='customer').count()


class BotListCreateAPIView(ListCreateAPIView):
    serializer_class = BotSerializer
    permission_classes = [IsOwner | IsManager]

    def get_queryset(self):
        return RestaurantBot.objects.select_related('added_by').order_by('-created_at')

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


class BotDetailAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = BotSerializer
    permission_classes = [IsOwner | IsManager]
    queryset = RestaurantBot.objects.all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx


class BotActivateAPIView(APIView):
    permission_classes = [IsOwner | IsManager]

    def post(self, request, pk):
        try:
            bot = RestaurantBot.objects.get(pk=pk)
        except RestaurantBot.DoesNotExist:
            return Response({'error': 'Bot topilmadi'}, status=404)
        RestaurantBot.activate(bot)
        return Response({'message': f"@{bot.bot_username} aktiv qilindi"})


class BotResetWebhookAPIView(APIView):
    permission_classes = [IsOwner | IsManager]

    def post(self, request, pk):
        try:
            bot = RestaurantBot.objects.get(pk=pk)
        except RestaurantBot.DoesNotExist:
            return Response({'error': 'Bot topilmadi'}, status=404)
        raw_token = bot.get_token()
        ok = set_webhook(bot, raw_token, request)
        if ok:
            return Response({'message': "Webhook muvaffaqiyatli o'rnatildi"})
        return Response({'error': "Webhook o'rnatishda xatolik"}, status=400)


class TelegramWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, bot_id):
        try:
            bot = RestaurantBot.objects.get(id=bot_id, is_active=True)
        except RestaurantBot.DoesNotExist:
            return Response({'error': 'Bot topilmadi'}, status=404)

        update_data = request.data

        # update_id yo'q bo'lsa — Telegram test so'rovi, 200 qaytaramiz
        if not update_data or 'update_id' not in update_data:
            return Response({'ok': True})

        try:
            process_telegram_update(bot.id, dict(update_data))
        except Exception as e:
            print(f"[WEBHOOK XATO] {e}")
            # Baribir 200 — Telegram qayta urinmasin

        return Response({'ok': True})

class RestaurantInfoUpdateAPIView(RetrieveUpdateAPIView):
    serializer_class = RestaurantInfoUpdateSerializer
    permission_classes = [IsOwner | IsManager]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        obj, _ = RestaurantInfo.objects.get_or_create(
            pk=1,
            defaults={
                'name': '',
                'slogan': '',
                'description': '',
                'address': '',
                'phone': '',
                'email': 'admin@restaurant.com',
                'open_time': '09:00',
                'close_time': '23:00',
            }
        )
        return obj


class MeRetrieveAPIView(RetrieveAPIView):
    """GET /api/v1/employees/me/ — joriy xodim ma'lumotlari"""
    serializer_class = EmployeeModelSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class MeUpdateAPIView(GenericAPIView):
    """PATCH /api/v1/employees/me/update/ — profil yangilash"""
    serializer_class = EmployeeModelSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request):
        user = request.user
        data = request.data.copy()

        # Parol alohida ishlaydi
        new_password = data.pop('password', None)
        if new_password:
            if isinstance(new_password, list):
                new_password = new_password[0]
            user.set_password(new_password)

        serializer = self.get_serializer(
            user, data=data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if new_password:
            user.save(update_fields=['password'])

        return Response(serializer.data)


# kelajakdagi admin panelim uchun kerak view lar
# ── PROFILE ───────────────────────────────────────────────
class ProfileListAPIView(ListAPIView):
    queryset = Profile.objects.filter(is_active=True)
    serializer_class = ProfileSerializer
    permission_classes = [AllowAny]


class ProfileCreateAPIView(CreateAPIView):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsMe]


class ProfileRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsMe]


# ── LINK ──────────────────────────────────────────────────
class LinkCreateAPIView(CreateAPIView):
    queryset = Link.objects.all()
    serializer_class = LinkSerializer
    permission_classes = [IsMe]


class LinkRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = Link.objects.all()
    serializer_class = LinkSerializer
    permission_classes = [IsMe]


# ── SOCIAL LINK ───────────────────────────────────────────
class SocialLinkCreateAPIView(CreateAPIView):
    queryset = SocialLink.objects.all()
    serializer_class = SocialLinkSerializer
    permission_classes = [IsMe]


class SocialLinkRUDAPIView(RetrieveUpdateDestroyAPIView):
    queryset = SocialLink.objects.all()
    serializer_class = SocialLinkSerializer
    permission_classes = [IsMe]
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.views import (
    # Menu
    MenuListAPIView, MenuCategoriesAPIView, FeaturedProductListAPIView,
    # Orders
    OrderRequestCreateAPIView, OwnerOrderStatisticsListAPIView, ManagerOrderStatisticAPIView,
    # Products
    ProductListAPIView, ProductRUDAPIView,
    # Categories
    CategoryCreateListAPIView, CategoryRUDApiView,
    # Ingredients
    IngredientCreateAPIView, IngredientRUDAPIView,
    # Recipes
    RecipeCreateAPIView, RecipeRUDAPIView,
    # Tables
    TableCreateListAPIView, TableRUDAPIView, TableSessionCreateAPIView,
    TableQRCodeListCreateAPIView, TableSessionRUDAPIView, TableSessionListAPIView,
    # Employees
    EmployeeCreateAPIView, EmployeeLoginAPIView, ChefListAPIView,
    EmployeeDestroyAPIView, EmployeeUpdateAPIView, EmployeeTokenAPIView,
    MeRetrieveAPIView, MeUpdateAPIView,
    # Auth
    UserRegisterAPIView, UserLoginAPIView, VerifyEmailAPIView,
    VerifyOtpCodeAPIView, ResetPasswordAPIView,
    # Users
    UserRUDAPIView,
    # Orders & Reports
    ManagerOrderListAPIView, DailyReportListAPIView, DailyReportConfirmAPIView,
    # Salary
    SalaryPaymentCreateAPIView, SalaryPaymentListAPIView,
    # Reservations
    ReservationCreateAPIView, NotificationListAPIView,
    # Comments
    ProductCommentsAPIView, CommentCreateAPIView,
    # Restaurant
    RestaurantInfoAPIView, GalleryListAPIView, RestaurantInfoUpdateAPIView,
    # Ingredients extra
    IngredientPurchaseListCreateAPIView, ChefDailyTakeoutListCreateAPIView,
    # Payments
    PaymentListAPIView, PaymentCreateAPIView, OrderPaymentProofAPIView,
    # Bots
    BotListCreateAPIView, BotDetailAPIView, BotActivateAPIView, BotResetWebhookAPIView, EmployeeListAPIView,
    ManagerAlertListAPIView, TelegramWebhookView, MyDevicesListAPIView, DeviceRemovalRequestAPIView,
    DeviceRemovalConfirmAPIView, TableQRCodeDetailAPIView, OwnerDashboardAPIView, FineDestroyAPIView,
    FineListCreateAPIView, IngredientTransactionListAPIView, MyOrderProofsListAPIView, OrderStatusAPIView,
    SalaryScheduleListCreateAPIView, SalaryScheduleRUDAPIView, EmployeeSalaryInfoListAPIView, ExpenseListCreateAPIView,
    ExpenseDestroyAPIView, ProfitReportAPIView, ProfileListAPIView, ProfileCreateAPIView, ProfileRUDAPIView,
    LinkCreateAPIView, LinkRUDAPIView, SocialLinkCreateAPIView, SocialLinkRUDAPIView, OrderPeriodListAPIView,
    OrderStatsCardsAPIView,
)

urlpatterns = [

    # ── SCHEMA ────────────────────────────────────────────────────────
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # ── AUTENTIFIKATSIYA ──────────────────────────────────────────────
    path('auth/token/refresh/', TokenRefreshView.as_view()),
    path('auth/token/verify/', TokenVerifyView.as_view()),
    path('auth/register/', UserRegisterAPIView.as_view()),
    path('auth/login/', UserLoginAPIView.as_view()),
    path('auth/verify/email/', VerifyEmailAPIView.as_view()),
    path('auth/verify/otp/', VerifyOtpCodeAPIView.as_view()),
    path('auth/reset-password/', ResetPasswordAPIView.as_view()),

    # ── RESTORAN ──────────────────────────────────────────────────────
    path('restaurant/info/', RestaurantInfoAPIView.as_view()),
    path('restaurant/info/update/', RestaurantInfoUpdateAPIView.as_view()),
    path('restaurant/gallery/', GalleryListAPIView.as_view()),

    # ── MENYU ─────────────────────────────────────────────────────────
    path('menu/products/', MenuListAPIView.as_view()),
    path('menu/categories/', MenuCategoriesAPIView.as_view()),
    path('menu/featured/', FeaturedProductListAPIView.as_view()),

    # ── KATEGORIYALAR ─────────────────────────────────────────────────
    path('categories/', CategoryCreateListAPIView.as_view()),
    path('categories/<int:pk>/', CategoryRUDApiView.as_view()),

    # ── MAHSULOTLAR ───────────────────────────────────────────────────
    path('products/', ProductListAPIView.as_view()),
    path('products/<int:pk>/', ProductRUDAPIView.as_view()),
    path('products/<int:pk>/comments/', ProductCommentsAPIView.as_view()),

    # ── SHARHLAR ──────────────────────────────────────────────────────
    path('comments/', CommentCreateAPIView.as_view()),

    # ── INGREDIENTLAR ─────────────────────────────────────────────────────
    path('ingredients/', IngredientCreateAPIView.as_view()),
    path('ingredients/purchases/', IngredientPurchaseListCreateAPIView.as_view()),
    path('ingredients/chef-takeout/', ChefDailyTakeoutListCreateAPIView.as_view()),
    path('ingredients/transactions/', IngredientTransactionListAPIView.as_view()),
    path('ingredients/<int:pk>/', IngredientRUDAPIView.as_view()),

    # ── RETSEPTLAR ────────────────────────────────────────────────────
    path('recipes/', RecipeCreateAPIView.as_view()),
    path('recipes/<int:pk>/', RecipeRUDAPIView.as_view()),

    # ── BUYURTMALAR ───────────────────────────────────────────────────
    path('orders/', OrderRequestCreateAPIView.as_view()),
    path('orders/statistics/', OwnerOrderStatisticsListAPIView.as_view()),
    path('orders/manager/', ManagerOrderStatisticAPIView.as_view()),
    path('orders/<int:pk>/proof/', OrderPaymentProofAPIView.as_view()),
    path('orders/<int:pk>/proof/confirm/', OrderPaymentProofAPIView.as_view()),
    path('orders/<int:pk>/status/', OrderStatusAPIView.as_view()),
    path('orders/my-proofs/', MyOrderProofsListAPIView.as_view()),

    # ── MANAGER PANELI ────────────────────────────────────────────────
    path('manager/orders/', ManagerOrderListAPIView.as_view()),
    path('manager/alerts/', ManagerAlertListAPIView.as_view()),

    path('orders/stats/', OrderStatsCardsAPIView.as_view()),
    path('orders/period-list/', OrderPeriodListAPIView.as_view()),
    path('owner/dashboard/', OwnerDashboardAPIView.as_view()),

    # ── STOLLAR ───────────────────────────────────────────────────────
    path('tables/', TableCreateListAPIView.as_view()),
    path('tables/<int:pk>/', TableRUDAPIView.as_view()),
    path('tables/<int:pk>/sessions/', TableSessionCreateAPIView.as_view()),
    path('tables/qr-codes/', TableQRCodeListCreateAPIView.as_view()),
    path('tables/qr-codes/', TableQRCodeListCreateAPIView.as_view()),
    path('tables/qr-codes/<int:pk>/', TableQRCodeDetailAPIView.as_view()),

    # ── STOL SESSIYALARI ──────────────────────────────────────────────
    path('sessions/', TableSessionListAPIView.as_view()),
    path('sessions/<int:pk>/', TableSessionRUDAPIView.as_view()),

    # ── XODIMLAR ──────────────────────────────────────────────────────
    path('employees/', EmployeeCreateAPIView.as_view()),

    path('employees/token/', EmployeeTokenAPIView.as_view()),
    path('employees/login/', EmployeeLoginAPIView.as_view()),
    path('employees/me/', MeRetrieveAPIView.as_view()),
    path('employees/me/update/', MeUpdateAPIView.as_view()),
    path('employees/chefs/', ChefListAPIView.as_view()),
    path('employees/delete/<int:pk>/', EmployeeDestroyAPIView.as_view()),
    path('employees/ru/<int:pk>/', EmployeeUpdateAPIView.as_view()),
    path('employees/list/', EmployeeListAPIView.as_view()),

    path('employees/devices/', MyDevicesListAPIView.as_view()),
    path('employees/devices/<int:session_id>/remove/', DeviceRemovalRequestAPIView.as_view()),
    path('employees/devices/<int:session_id>/confirm/', DeviceRemovalConfirmAPIView.as_view()),

    # ── FOYDALANUVCHILAR ──────────────────────────────────────────────
    path('users/<int:pk>/', UserRUDAPIView.as_view()),

    # ── MAOSH ─────────────────────────────────────────────────────────
    path('salary/payments/', SalaryPaymentListAPIView.as_view()),
    path('salary/payments/create/', SalaryPaymentCreateAPIView.as_view()),
    path('fines/', FineListCreateAPIView.as_view()),
    path('fines/<int:pk>/', FineDestroyAPIView.as_view()),
    path('salary/schedules/', SalaryScheduleListCreateAPIView.as_view()),
    path('salary/schedules/<int:pk>/', SalaryScheduleRUDAPIView.as_view()),
    path('salary/employees-info/', EmployeeSalaryInfoListAPIView.as_view()),

    # ── TO'LOVLAR ─────────────────────────────────────────────────────
    path('payments/', PaymentCreateAPIView.as_view()),
    path('payments/history/', PaymentListAPIView.as_view()),

    # ── expance ─────────────────────────────────────────────────────
    path('expenses/', ExpenseListCreateAPIView.as_view()),
    path('expenses/<int:pk>/', ExpenseDestroyAPIView.as_view()),
    path('reports/profit/', ProfitReportAPIView.as_view()),

    # ── HISOBOTLAR ────────────────────────────────────────────────────
    path('reports/daily/', DailyReportListAPIView.as_view()),
    path('reports/daily/confirm/', DailyReportConfirmAPIView.as_view()),

    # ── REZERVATSIYALAR ───────────────────────────────────────────────
    path('reservations/', ReservationCreateAPIView.as_view()),

    # ── BILDIRISHNOMALAR ──────────────────────────────────────────────
    path('notifications/', NotificationListAPIView.as_view()),

    # ── BOTLAR ────────────────────────────────────────────────────────
    path('bots/', BotListCreateAPIView.as_view()),
    path('bots/<int:pk>/', BotDetailAPIView.as_view()),
    path('bots/<int:pk>/activate/', BotActivateAPIView.as_view()),
    path('bots/<int:pk>/reset-webhook/', BotResetWebhookAPIView.as_view()),
    # ── TELEGRAM WEBHOOK ──────────────────────────────────────────────
    path('telegram/webhook/<int:bot_id>/', TelegramWebhookView.as_view()),

    # ── LINKTREE ──────────────────────────────────────────────────────
    path('linktree/profiles/', ProfileListAPIView.as_view()),
    path('linktree/profiles/create/', ProfileCreateAPIView.as_view()),
    path('linktree/profiles/<int:pk>/', ProfileRUDAPIView.as_view()),

    path('linktree/links/create/', LinkCreateAPIView.as_view()),
    path('linktree/links/<int:pk>/', LinkRUDAPIView.as_view()),

    path('linktree/socials/create/', SocialLinkCreateAPIView.as_view()),
    path('linktree/socials/<int:pk>/', SocialLinkRUDAPIView.as_view()),
]

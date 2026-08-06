from django.contrib import admin
from django.contrib.admin import ModelAdmin

from apps.models import (
    Product, Category, Order, OrderItem, User, Ingredient, RestaurantInfo,
    Link, SocialLink, Profile,
    # Qo'shimcha
    Table, TableSession, SalaryPayment, Reservation, Gallery,
    IngredientPurchase, Payment, RestaurantBot, ManagerAlert, Fine,
    IngredientTransaction, SalarySchedule, Expense, TableQRCode,
    DailyIngredientReport, Comment, Recipe,
)

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ('name', 'category', 'price', 'is_featured')
    list_filter = ('category', 'is_featured')
    search_fields = ('name',)


@admin.register(Table)
class TableAdmin(ModelAdmin):
    list_display = ('number', 'capacity', 'is_active', 'is_occupied')


@admin.register(TableSession)
class TableSessionAdmin(ModelAdmin):
    list_display = ('table', 'waiter', 'is_active', 'started_at', 'ended_at')
    list_filter = ('is_active',)


@admin.register(SalaryPayment)
class SalaryPaymentAdmin(ModelAdmin):
    list_display = ('employee', 'amount', 'status', 'month', 'payment_date')
    list_filter = ('status', 'payment_type')


@admin.register(Reservation)
class ReservationAdmin(ModelAdmin):
    list_display = ('full_name', 'table', 'date_of_reserve', 'capacity')


@admin.register(Gallery)
class GalleryAdmin(ModelAdmin):
    list_display = ('caption', 'order')


@admin.register(IngredientPurchase)
class IngredientPurchaseAdmin(ModelAdmin):
    list_display = ('ingredient', 'quantity', 'unit_price', 'total_price', 'purchased_by', 'purchased_at')


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ('order', 'method', 'status', 'amount', 'paid_at')
    list_filter = ('method', 'status')


@admin.register(RestaurantBot)
class RestaurantBotAdmin(ModelAdmin):
    list_display = ('bot_username', 'bot_type', 'is_active', 'webhook_set', 'created_at')
    list_filter = ('bot_type', 'is_active')
    # DIQQAT: token_encrypted ni list_display yoki fields ga qo'shmang — bu maxfiy ma'lumot
    exclude = ('token_encrypted',)


@admin.register(ManagerAlert)
class ManagerAlertAdmin(ModelAdmin):
    list_display = ('alert_type', 'title', 'created_at', 'is_resolved')
    list_filter = ('alert_type', 'is_resolved')


@admin.register(Fine)
class FineAdmin(ModelAdmin):
    list_display = ('employee', 'amount', 'issued_by', 'created_at', 'is_active')


@admin.register(IngredientTransaction)
class IngredientTransactionAdmin(ModelAdmin):
    list_display = ('ingredient', 'tx_type', 'delta', 'before', 'after', 'created_at')
    list_filter = ('tx_type',)


@admin.register(SalarySchedule)
class SalaryScheduleAdmin(ModelAdmin):
    list_display = ('employee', 'frequency', 'start_day', 'updated_at')


@admin.register(Expense)
class ExpenseAdmin(ModelAdmin):
    list_display = ('expense_type', 'amount', 'date', 'added_by')
    list_filter = ('expense_type',)


@admin.register(TableQRCode)
class TableQRCodeAdmin(ModelAdmin):
    list_display = ('table', 'label', 'is_deleted', 'created_at')
    list_filter = ('is_deleted',)


@admin.register(DailyIngredientReport)
class DailyIngredientReportAdmin(ModelAdmin):
    list_display = ('ingredient', 'date', 'status', 'confirmed_by')
    list_filter = ('status',)


@admin.register(Comment)
class CommentAdmin(ModelAdmin):
    list_display = ('product', 'display_name', 'rating', 'is_blocked', 'created_at')
    list_filter = ('is_blocked', 'rating')


@admin.register(Recipe)
class RecipeAdmin(ModelAdmin):
    list_display = ('product', 'ingredient', 'amount', 'unit')
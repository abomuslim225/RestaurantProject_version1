from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from rest_framework.test import APIClient
from django.test import TestCase

from apps.models import (
    Ingredient, Product, Category, Table, TableSession, User,
    Order, OrderItem, Recipe, Comment, Payment, SalaryPayment, Fine,
    Expense, Reservation, Notification, RestaurantInfo, IngredientPurchase,
    ChefDailyTakeout, DailyIngredientReport, TableQRCode, Profile, Link, SocialLink,
)


# Create your tests here.

@pytest.fixture()
def user():
    User.objects.create_user(
        username="owner_user",
        password="test1234",
        role=User.RoleChoice.OWNER,
        is_at_work=True,
        phone_number="+998901234567",
        shift=User.ShiftChoices.DAY,
        base_salary=5000000.00,
        fine_balance=0.00,
        bank_card="1234567890123456",
        emergency_contact="+998901234568",
    )
    User.objects.create_user(
        username="manager_user",
        password="test1234",
        role=User.RoleChoice.MANAGER,
        is_at_work=True,
        phone_number="+998901234569",
        shift=User.ShiftChoices.NIGHT,
        base_salary=3000000.00,
        fine_balance=50000.00,
        bank_card="9876543210987654",
        emergency_contact="+998901234570",
    )
    User.objects.create_user(
        username="waiter_user",
        password="test1234",
        role=User.RoleChoice.WAITER,
        is_at_work=False,
        phone_number="+998901234571",
        shift=User.ShiftChoices.DAY,
        base_salary=1500000.00,
        fine_balance=0.00,
    )
    User.objects.create_user(
        username="customer_user",
        password="test1234",
        role=User.RoleChoice.CUSTOMER,
        phone_number="+998901234572",
    )


@pytest.fixture()
def category():
    return Category.objects.create(title="milliy taomlar")


@pytest.fixture()
def ingredient():
    Ingredient.objects.create(name="go'sht", stack_amount=1.0)
    Ingredient.objects.create(name="sabzi", stack_amount=7.0)


@pytest.fixture()
def product(category):
    Product.objects.create(name="osh", price=40000.0, category_id=category.id)
    Product.objects.create(name="tort", price=20000.0, category_id=category.id)


@pytest.fixture()
def table(db):
    Table.objects.create(number=1, capacity=4, is_active=True)
    Table.objects.create(number=2, capacity=3, is_active=True)
    Table.objects.create(number=3, capacity=5, is_active=True)
    Table.objects.create(number=4, capacity=6, is_active=False)


@pytest.fixture()
def waiter_user(db):
    return User.objects.create_user(
        username="waiter1",
        password="test1234",
        role=User.RoleChoice.WAITER,
        phone_number="+998901234571",
        is_at_work=True,
        shift=User.ShiftChoices.DAY,
    )


@pytest.fixture()
def table_session(db, table, waiter_user):
    t1 = Table.objects.get(number=1)
    t2 = Table.objects.get(number=2)
    t3 = Table.objects.get(number=3)


    TableSession.objects.create(table=t1, waiter=waiter_user,is_active=True,)
    TableSession.objects.create(table=t2,waiter=waiter_user,is_active=True,)
    TableSession.objects.create(table=t3,waiter=None)


# ── QO'SHIMCHA FIXTURELAR (qolgan API'lar uchun) ────────────────────────

@pytest.fixture()
def owner_user(db):
    return User.objects.create_user(
        username="owner_fix",
        password="test1234",
        role=User.RoleChoice.OWNER,
        email="owner_fix@example.com",
        phone_number="+998900000001",
        is_at_work=True,
    )


@pytest.fixture()
def manager_user(db):
    return User.objects.create_user(
        username="manager_fix",
        password="test1234",
        role=User.RoleChoice.MANAGER,
        email="manager_fix@example.com",
        phone_number="+998900000002",
        is_at_work=True,
    )


@pytest.fixture()
def chef_user(db):
    return User.objects.create_user(
        username="chef_fix",
        password="test1234",
        role=User.RoleChoice.CHEF,
        email="chef_fix@example.com",
        phone_number="+998900000003",
        is_at_work=True,
    )


@pytest.fixture()
def cashier_user(db):
    return User.objects.create_user(
        username="cashier_fix",
        password="test1234",
        role=User.RoleChoice.CASHIER,
        email="cashier_fix@example.com",
        phone_number="+998900000004",
        is_at_work=True,
    )


@pytest.fixture()
def accountant_user(db):
    return User.objects.create_user(
        username="accountant_fix",
        password="test1234",
        role=User.RoleChoice.ACCOUNTANT,
        email="accountant_fix@example.com",
        phone_number="+998900000005",
        is_at_work=True,
    )


@pytest.mark.django_db
class TestIngredientWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/ingredients/"

    def test_ingredient_list(self, ingredient):
        response = self.client.get(self.url)
        data = response.data
        assert len(data) == 2
        assert response.status_code == 200
        assert response.data[0]['name'] == "go'sht"

    def test_ingredient_create(self, ingredient):
        product_data = {"name": "guruch", "stack_amount": 15.0, "stack_type": "kg"}
        response = self.client.post(self.url, data=product_data)
        assert response.status_code == HTTP_201_CREATED
        assert Ingredient.objects.count() == 3

    # def test_ingredient_delete(self, ingredient:list):
    #     # del_ing = ingredient[0]
    #     response = self.client.delete(self.url, data=ingredient[0].id)
    #     assert response.status_code == 204


@pytest.mark.django_db
class TestProductWithFixture:
    def setup_method(self):
        self.client = APIClient()

        self.url = "/api/v1/products/"

    def test_ingredient_list(self, product):
        response = self.client.get(self.url)
        data = response.data
        assert len(data) == 2
        assert response.status_code == 200
        assert response.data[0]['name'] == "osh"

    def test_ingredient_create(self, product):
        cat = Category.objects.all().first()
        product_data = {"name": "manti", "price": 15000.0, "category": cat.id}
        response = self.client.post(self.url, data=product_data)
        assert response.status_code == HTTP_201_CREATED
        assert Product.objects.count() == 3


@pytest.mark.django_db
class TestTableWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/tables/"

    def test_ingredient_list(self, table):
        response = self.client.get(self.url)
        data = response.data
        assert len(data) == 4
        assert response.status_code == 200
        assert response.data[0]['number'] == 1

    def test_ingredient_create(self, table):
        table_data = {"number": 5, "capacity": 3, "is_active": True}
        response = self.client.post(self.url, data=table_data)
        assert response.status_code == HTTP_201_CREATED
        assert Table.objects.count() == 5


@pytest.mark.django_db
class TestTableSessionWithFixture:
    def setup_method(self):
        self.client = APIClient()
        # Ro'yxat: /api/v1/sessions/ (TableSessionListAPIView)
        self.list_url = "/api/v1/sessions/"

    def test_table_session_list(self, table_session, waiter_user):
        self.client.force_authenticate(user=waiter_user)
        response = self.client.get(self.list_url)
        data = response.data
        assert response.status_code == 200
        assert len(data) == 3
        # assert response.data[0]['table'] == Table.objects.get(number=1)

    def test_table_session_create(self, table_session, waiter_user):
        # Yaratish: /api/v1/tables/<pk>/sessions/ (TableSessionCreateAPIView)
        self.client.force_authenticate(user=waiter_user)
        waiter = User.objects.filter(role=User.RoleChoice.WAITER).first()
        table_obj = Table.objects.get(number=4)
        create_url = f"/api/v1/tables/{table_obj.id}/sessions/"
        table_session_data = {"table": table_obj.id, "waiter": waiter.id, "is_active": True}
        response = self.client.post(create_url, data=table_session_data, format="json")
        assert response.status_code == HTTP_201_CREATED
        assert TableSession.objects.count() == 4


# ═══════════════════════════════════════════════════════════════════════
# QOLGAN API'LAR UCHUN TESTLAR
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestAuthWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_register(self):
        url = "/api/v1/auth/register/"
        data = {
            "first_name": "Ali",
            "last_name": "Valiyev",
            "phone_number": "+998901112233",
            "email": "ali@example.com",
            "password": "StrongPass123",
        }
        response = self.client.post(url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert User.objects.filter(email="ali@example.com").exists()

    def test_login(self):
        User.objects.create_user(
            username="loginuser",
            password="StrongPass123",
            email="login@example.com",
            role=User.RoleChoice.CUSTOMER,
        )
        url = "/api/v1/auth/login/"
        data = {"email": "login@example.com", "password": "StrongPass123"}
        response = self.client.post(url, data=data)
        assert response.status_code == HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data


@pytest.mark.django_db
class TestRestaurantInfoWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_restaurant_info_retrieve(self):
        RestaurantInfo.objects.create(
            name="Milliy Taomlar",
            slogan="Mazali va sifatli",
            description="Restoran haqida",
            address="Toshkent",
            phone="+998901234567",
            email="info@restaurant.uz",
            open_time="09:00",
            close_time="23:00",
        )
        response = self.client.get("/api/v1/restaurant/info/")
        assert response.status_code == HTTP_200_OK
        assert response.data['name'] == "Milliy Taomlar"

    def test_gallery_list(self):
        response = self.client.get("/api/v1/restaurant/gallery/")
        assert response.status_code == HTTP_200_OK


@pytest.mark.django_db
class TestMenuWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_menu_products(self, product):
        response = self.client.get("/api/v1/menu/products/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 2

    def test_menu_categories(self, category):
        response = self.client.get("/api/v1/menu/categories/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1

    def test_featured_products(self, category):
        Product.objects.create(
            name="maxsus taom", price=Decimal("35000.00"),
            category=category, is_featured=True,
        )
        response = self.client.get("/api/v1/menu/featured/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1


@pytest.mark.django_db
class TestCategoryWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/categories/"

    def test_category_list(self, category):
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1

    def test_category_create(self):
        response = self.client.post(self.url, data={"title": "ichimliklar"})
        assert response.status_code == HTTP_201_CREATED
        assert Category.objects.count() == 1

    def test_category_update(self, category, manager_user):
        self.client.force_authenticate(user=manager_user)
        url = f"{self.url}{category.id}/"
        response = self.client.patch(url, data={"title": "yangi nom"})
        assert response.status_code == HTTP_200_OK
        category.refresh_from_db()
        assert category.title == "yangi nom"

    def test_category_delete(self, category, owner_user):
        self.client.force_authenticate(user=owner_user)
        url = f"{self.url}{category.id}/"
        response = self.client.delete(url)
        assert response.status_code == 204
        assert Category.objects.count() == 0


@pytest.mark.django_db
class TestRecipeWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/recipes/"

    def test_recipe_create(self, product, ingredient):
        product_obj = Product.objects.first()
        ingredient_obj = Ingredient.objects.first()
        data = {
            "product": product_obj.id,
            "ingredient": ingredient_obj.id,
            "amount": 200,
            "unit": "gr",
        }
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert Recipe.objects.count() == 1

    def test_recipe_rud(self, product, ingredient):
        product_obj = Product.objects.first()
        ingredient_obj = Ingredient.objects.first()
        recipe = Recipe.objects.create(
            product=product_obj, ingredient=ingredient_obj, amount=150, unit="gr"
        )
        url = f"{self.url}{recipe.id}/"

        response = self.client.get(url)
        assert response.status_code == HTTP_200_OK
        assert response.data['amount'] == 150

        response = self.client.delete(url)
        assert response.status_code == 204
        assert Recipe.objects.count() == 0


@pytest.mark.django_db
class TestCommentWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_comment_create(self, product):
        product_obj = Product.objects.first()
        data = {
            "product_id": product_obj.id,
            "text": "juda mazali",
            "rating": 5,
            "display_name": "Aziz",
        }
        response = self.client.post("/api/v1/comments/", data=data)
        assert response.status_code == HTTP_201_CREATED
        assert Comment.objects.count() == 1

    def test_product_comments_list(self, product):
        product_obj = Product.objects.first()
        Comment.objects.create(product=product_obj, text="zo'r", rating=5, display_name="Vali")
        url = f"/api/v1/products/{product_obj.id}/comments/"
        response = self.client.get(url)
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1


@pytest.mark.django_db
class TestOrderWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/orders/"

    def test_order_create(self, table_session, product):
        table_obj = Table.objects.get(number=1)
        product_obj = Product.objects.first()
        data = {
            "table_id": table_obj.id,
            "items": [{"product": product_obj.id, "quantity": 2}],
            "payment_type": "cash",
        }
        response = self.client.post(self.url, data=data, format="json")
        assert response.status_code == HTTP_201_CREATED
        assert Order.objects.count() == 1
        order = Order.objects.first()
        assert order.total_price == product_obj.price * 2

    def test_order_status(self, table_session, product):
        table_obj = Table.objects.get(number=1)
        product_obj = Product.objects.first()
        order = Order.objects.create(
            table=table_obj, total_price=product_obj.price, payment_type="cash"
        )
        url = f"/api/v1/orders/{order.id}/status/"
        response = self.client.get(url)
        assert response.status_code == HTTP_200_OK
        assert response.data['status'] == Order.OrderStatusType.PENDING


@pytest.mark.django_db
class TestOrderStatsWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_order_stats_cards(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get("/api/v1/orders/stats/")
        assert response.status_code == HTTP_200_OK
        assert "revenue" in response.data

    def test_order_period_list(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get("/api/v1/orders/period-list/")
        assert response.status_code == HTTP_200_OK


@pytest.mark.django_db
class TestOwnerDashboardWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_owner_dashboard(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get("/api/v1/owner/dashboard/")
        assert response.status_code == HTTP_200_OK
        assert "chart" in response.data
        assert "top_staff" in response.data


@pytest.mark.django_db
class TestPaymentWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_payment_create(self, table, product, cashier_user):
        self.client.force_authenticate(user=cashier_user)
        table_obj = Table.objects.get(number=1)
        product_obj = Product.objects.first()
        order = Order.objects.create(
            table=table_obj, total_price=product_obj.price,
            payment_type="cash", status=Order.OrderStatusType.READY,
        )
        data = {"order": order.id, "method": "cash", "amount": str(product_obj.price)}
        response = self.client.post("/api/v1/payments/", data=data, format="json")
        assert response.status_code == HTTP_201_CREATED
        order.refresh_from_db()
        assert order.status == Order.OrderStatusType.PAID

    def test_payment_history(self, table, product, cashier_user):
        self.client.force_authenticate(user=cashier_user)
        table_obj = Table.objects.get(number=1)
        product_obj = Product.objects.first()
        order = Order.objects.create(table=table_obj, total_price=product_obj.price, payment_type="cash")
        Payment.objects.create(
            order=order, method="cash", status=Payment.PaymentStatus.COMPLETED,
            amount=product_obj.price, paid_at=timezone.now(),
        )
        response = self.client.get("/api/v1/payments/history/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1


@pytest.mark.django_db
class TestEmployeeWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_employee_create(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        data = {
            "first_name": "Jasur",
            "last_name": "Karimov",
            "phone_number": "+998907778899",
            "role": User.RoleChoice.WAITER,
            "base_salary": "1500000.00",
            "fine_balance": "0.00",
        }
        response = self.client.post("/api/v1/employees/", data=data)
        assert response.status_code == HTTP_201_CREATED
        assert User.objects.filter(phone_number="+998907778899").exists()

    def test_employee_list(self, owner_user, waiter_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get("/api/v1/employees/list/")
        assert response.status_code == HTTP_200_OK

    def test_chef_list(self, chef_user):
        response = self.client.get("/api/v1/employees/chefs/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1

    def test_me_retrieve(self, waiter_user):
        self.client.force_authenticate(user=waiter_user)
        response = self.client.get("/api/v1/employees/me/")
        assert response.status_code == HTTP_200_OK
        assert response.data['phone_number'] == waiter_user.phone_number


@pytest.mark.django_db
class TestIngredientPurchaseWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/ingredients/purchases/"

    def test_purchase_create(self, ingredient, owner_user):
        self.client.force_authenticate(user=owner_user)
        ingredient_obj = Ingredient.objects.get(name="go'sht")
        data = {
            "ingredient": ingredient_obj.id,
            "quantity": 10,
            "unit_price": "15000.00",
            "supplier": "Bozor",
        }
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert IngredientPurchase.objects.count() == 1
        ingredient_obj.refresh_from_db()
        assert ingredient_obj.stack_amount == 11.0

    def test_purchase_list(self, ingredient, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK


@pytest.mark.django_db
class TestChefTakeoutWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/ingredients/chef-takeout/"

    def test_takeout_create(self, ingredient, chef_user):
        self.client.force_authenticate(user=chef_user)
        ingredient_obj = Ingredient.objects.get(name="sabzi")
        data = {"ingredient": ingredient_obj.id, "amount": 2, "note": "salat uchun"}
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        ingredient_obj.refresh_from_db()
        assert ingredient_obj.stack_amount == 5.0


@pytest.mark.django_db
class TestDailyReportWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_daily_report_list(self, ingredient):
        ingredient_obj = Ingredient.objects.first()
        DailyIngredientReport.objects.create(
            ingredient=ingredient_obj, date=timezone.now().date(),
            opening_amount=10, estimated_used=2, estimated_closing=8,
        )
        response = self.client.get("/api/v1/reports/daily/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1

    def test_daily_report_confirm(self, ingredient, manager_user):
        self.client.force_authenticate(user=manager_user)
        ingredient_obj = Ingredient.objects.first()
        report = DailyIngredientReport.objects.create(
            ingredient=ingredient_obj, date=timezone.now().date(),
            opening_amount=10, estimated_used=2, estimated_closing=8,
        )
        data = {
            "report_id": report.id,
            "actual_used": 3,
            "actual_closing": 7,
            "note": "biroz farq bor",
        }
        response = self.client.post("/api/v1/reports/daily/confirm/", data=data)
        assert response.status_code == HTTP_200_OK
        report.refresh_from_db()
        assert report.status == DailyIngredientReport.StatusChoice.CONFIRMED
        ingredient_obj.refresh_from_db()
        assert ingredient_obj.stack_amount == 7


@pytest.mark.django_db
class TestSalaryWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_salary_payment_create(self, accountant_user, waiter_user):
        self.client.force_authenticate(user=accountant_user)
        data = {
            "employee": waiter_user.id,
            "amount": "1500000.00",
            "month": "2026-07-01",
            "payment_date": "2026-07-05",
            "payment_type": "cash",
        }
        response = self.client.post("/api/v1/salary/payments/create/", data=data)
        assert response.status_code == HTTP_201_CREATED
        assert SalaryPayment.objects.count() == 1

    def test_salary_payment_list(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get("/api/v1/salary/payments/")
        assert response.status_code == HTTP_200_OK


@pytest.mark.django_db
class TestFineWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/fines/"

    def test_fine_create(self, manager_user, waiter_user):
        self.client.force_authenticate(user=manager_user)
        data = {"employee": waiter_user.id, "amount": "20000.00", "reason": "kech qoldi"}
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert Fine.objects.count() == 1

    def test_fine_list(self, manager_user, waiter_user):
        self.client.force_authenticate(user=manager_user)
        Fine.objects.create(
            employee=waiter_user, issued_by=manager_user,
            amount=Decimal("10000.00"), reason="test",
        )
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1


@pytest.mark.django_db
class TestExpenseWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/expenses/"

    def test_expense_create(self, accountant_user):
        self.client.force_authenticate(user=accountant_user)
        data = {
            "expense_type": "rent",
            "amount": "500000.00",
            "description": "oylik ijara",
            "date": str(timezone.now().date()),
        }
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert Expense.objects.count() == 1

    def test_expense_list(self, accountant_user):
        self.client.force_authenticate(user=accountant_user)
        Expense.objects.create(
            expense_type="utility", amount=Decimal("100000.00"),
            date=timezone.now().date(), added_by=accountant_user,
        )
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1

    def test_expense_delete(self, accountant_user):
        self.client.force_authenticate(user=accountant_user)
        expense = Expense.objects.create(
            expense_type="other", amount=Decimal("5000.00"),
            date=timezone.now().date(), added_by=accountant_user,
        )
        url = f"{self.url}{expense.id}/"
        response = self.client.delete(url)
        assert response.status_code == 204
        assert Expense.objects.count() == 0

    def test_profit_report(self, accountant_user):
        self.client.force_authenticate(user=accountant_user)
        response = self.client.get("/api/v1/reports/profit/")
        assert response.status_code == HTTP_200_OK
        assert "net_profit" in response.data


@pytest.mark.django_db
class TestReservationWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/reservations/"

    def test_reservation_create(self, table):
        table_obj = Table.objects.get(number=1)
        data = {
            "full_name": "Dilshod Rahimov",
            "email": "dilshod@example.com",
            "capacity": 4,
            "date_of_reserve": "2026-07-10 19:00",
            "table": table_obj.id,
        }
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert Reservation.objects.count() == 1


@pytest.mark.django_db
class TestNotificationWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/notifications/"

    def test_notification_list(self, waiter_user):
        self.client.force_authenticate(user=waiter_user)
        Notification.objects.create(user=waiter_user, message="Yangi buyurtma keldi")
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1


@pytest.mark.django_db
class TestTableQRCodeWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/tables/qr-codes/"

    def test_qr_code_create(self, table, owner_user):
        self.client.force_authenticate(user=owner_user)
        table_obj = Table.objects.get(number=1)
        data = {"table": table_obj.id, "label": "Kirish eshigi"}
        response = self.client.post(self.url, data=data)
        assert response.status_code == HTTP_201_CREATED
        assert TableQRCode.objects.count() == 1

    def test_qr_code_list(self, table, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK


@pytest.mark.django_db
class TestBotWithFixture:
    def setup_method(self):
        self.client = APIClient()
        self.url = "/api/v1/bots/"

    def test_bot_list(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        response = self.client.get(self.url)
        assert response.status_code == HTTP_200_OK


@pytest.mark.django_db
class TestLinktreeWithFixture:
    def setup_method(self):
        self.client = APIClient()

    def test_profile_list(self):
        Profile.objects.create(name="Restoran", bio="Bizning ijtimoiy tarmoqlar", is_active=True)
        response = self.client.get("/api/v1/linktree/profiles/")
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1

    @pytest.mark.skip(
        reason="IsMe permission hali implement qilinmagan (has_permission hech narsa "
               "return qilmaydi -> doim False). Kelajakda IsMe tugallangach, bu testni yoqing."
    )
    def test_link_create(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        profile = Profile.objects.create(name="Restoran", is_active=True)
        data = {
            "profile": profile.id, "title": "Instagram",
            "url": "https://instagram.com/restoran", "order": 1,
        }
        response = self.client.post("/api/v1/linktree/links/create/", data=data)
        assert response.status_code == HTTP_201_CREATED
        assert Link.objects.count() == 1

    @pytest.mark.skip(
        reason="IsMe permission hali implement qilinmagan (has_permission hech narsa "
               "return qilmaydi -> doim False). Kelajakda IsMe tugallangach, bu testni yoqing."
    )
    def test_social_link_create(self, owner_user):
        self.client.force_authenticate(user=owner_user)
        profile = Profile.objects.create(name="Restoran", is_active=True)
        data = {
            "profile": profile.id, "platform": "telegram",
            "url": "https://t.me/restoran", "order": 1,
        }
        response = self.client.post("/api/v1/linktree/socials/create/", data=data)
        assert response.status_code == HTTP_201_CREATED
        assert SocialLink.objects.count() == 1
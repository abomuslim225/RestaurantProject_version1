from django_filters import DateTimeFilter, NumberFilter, CharFilter
from django_filters.rest_framework import FilterSet

from apps.models import Order


class OrderFilter(FilterSet):
    start_date = DateTimeFilter(field_name="created_at", lookup_expr='gte')
    end_date = DateTimeFilter(field_name="created_at", lookup_expr='lte')

    min_price = NumberFilter(field_name="price", lookup_expr='gte')
    max_price = NumberFilter(field_name="price", lookup_expr='lte')

    product_name = CharFilter(field_name="order_items__product__name", lookup_expr='icontains')
    waiter_name = CharFilter(field_name="waiter__first_name", lookup_expr='icontains')

    class Meta:
        model = Order
        fields = ["status", "waiter"]

    # def filter_brand(self, queryset, name, value):
    #     value = self.request.GET.get('brand', None)



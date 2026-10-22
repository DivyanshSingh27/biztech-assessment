
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Customer, Order, OrderItem


class OrderSummaryTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name="Test Customer",
            email="customer@example.com",
        )
        self.order = Order.objects.create(
            customer=self.customer,
            status="completed",
        )
        OrderItem.objects.create(
            order=self.order,
            product_name="Keyboard",
            quantity=2,
            unit_price=Decimal("50.00"),
        )
        OrderItem.objects.create(
            order=self.order,
            product_name="Mouse",
            quantity=1,
            unit_price=Decimal("25.00"),
        )

    def test_summary_returns_order_and_customer(self):
        response = self.client.get(reverse("order_summary"))

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data["orders"]), 1)
        self.assertEqual(data["orders"][0]["customer"], "Test Customer")
        self.assertEqual(data["orders"][0]["status"], "completed")

    def test_summary_calculates_item_count_and_total(self):
        response = self.client.get(reverse("order_summary"))

        self.assertEqual(response.status_code, 200)

        order = response.json()["orders"][0]
        self.assertEqual(order["item_count"], 2)
        self.assertEqual(Decimal(order["total"]), Decimal("125"))

    def test_summary_uses_a_bounded_number_of_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Check the endpoint response and capture the SQL it executes.
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("order_summary"))

        self.assertEqual(response.status_code, 200)

        # Silk writes its own profiling records. Count only SELECT statements
        # that read from the orders table, not Silk's instrumentation queries.
        order_queries = [
            query["sql"]
            for query in captured.captured_queries
            if '"orders_order"' in query["sql"]
            and query["sql"].lstrip().upper().startswith("SELECT")
        ]

        self.assertEqual(
            len(order_queries),
            1,
            "Expected one optimized order-summary SELECT query",
        )

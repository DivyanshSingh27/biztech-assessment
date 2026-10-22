from django.shortcuts import render

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import Order


@require_GET
def order_summary(request):
    orders = (
        Order.objects
        .select_related("customer")
        .annotate(
            item_count=Count("items"),
            total=Sum(
                ExpressionWrapper(
                    F("items__quantity") * F("items__unit_price"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            ),
        )
        .order_by("-created_at")[:200]
    )

    results = [
        {
            "order_id": order.id,
            "customer": order.customer.name,
            "status": order.status,
            "item_count": order.item_count,
            "total": str(order.total or 0),
        }
        for order in orders
    ]

    return JsonResponse({"orders": results})

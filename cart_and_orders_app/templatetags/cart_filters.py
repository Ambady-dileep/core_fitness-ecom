from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def multiply(value, arg):
    """Multiply two values."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def aggregate(queryset, expression=None):
    """Aggregate the total price * quantity over a queryset."""
    total = 0
    for item in queryset:
        try:
            price = float(item.price if hasattr(item, 'price') and item.price is not None else item.variant.price)
            quantity = item.quantity
            total += price * quantity
        except (AttributeError, ValueError, TypeError):
            continue
    return total

@register.filter
def in_stock(queryset):
    """Return items in the queryset where stock > 0."""
    return [item for item in queryset if item.variant.stock > 0]

@register.filter
def subtract(value, arg):
    """Subtract arg from value."""
    try:
        # Handle None or empty string
        val = float(value) if value not in (None, '') else 0
        arg_val = float(arg) if arg not in (None, '') else 0
        return val - arg_val
    except (ValueError, TypeError):
        return 0
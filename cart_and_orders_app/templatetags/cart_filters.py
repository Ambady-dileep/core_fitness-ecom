from django import template
from decimal import Decimal
import logging

register = template.Library()

# Set up logging to debug issues
logger = logging.getLogger(__name__)

@register.filter
def multiply(value, arg):
    """Multiply two values."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError) as e:
        logger.error(f"Multiply filter error: value={value}, arg={arg}, error={e}")
        return 0

@register.filter
def aggregate(queryset, expression=None):
    """Aggregate the total price * quantity over a queryset."""
    total = Decimal('0')
    for item in queryset:
        try:
            # Ensure item has the required attributes
            if not hasattr(item, 'quantity') or not hasattr(item, 'variant'):
                logger.warning(f"Item missing attributes: {item}")
                continue

            # Get price: use item.price if available, otherwise item.variant.price
            price = item.price if hasattr(item, 'price') and item.price is not None else item.variant.price
            if price is None:
                logger.warning(f"Price is None for item: {item}")
                continue

            # Convert price and quantity to Decimal for precise calculation
            price = Decimal(str(price))
            quantity = Decimal(str(item.quantity))

            # Add to total
            total += price * quantity
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error in aggregate filter for item {item}: {e}")
            continue
    return float(total)

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
    except (ValueError, TypeError) as e:
        logger.error(f"Subtract filter error: value={value}, arg={arg}, error={e}")
        return 0
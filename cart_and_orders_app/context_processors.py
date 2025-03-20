from .models import Cart, Wishlist

def cart_count(request):
    cart_count = 0
    wishlist_count = 0
    if request.user.is_authenticated:
        try:
            cart = Cart.objects.get(user=request.user)
            cart_count = cart.items.count()
        except Cart.DoesNotExist:
            cart_count = 0
        try:
            wishlist_count = Wishlist.objects.filter(user=request.user).count()
        except Wishlist.DoesNotExist:
            wishlist_count = 0
    return {
        'cart_count': cart_count,
        'wishlist_count': wishlist_count,
    }
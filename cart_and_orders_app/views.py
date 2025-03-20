from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import transaction
from .forms import OrderStatusForm
from .models import Cart, CartItem, Wishlist, Order, OrderItem, ReturnRequest, ProductVariant
import json
from django.http import JsonResponse, HttpResponse
from xhtml2pdf import pisa
from io import BytesIO
from django.views.decorators.cache import never_cache
from offer_and_coupon_app.models import Coupon, UserCoupon
from django.utils import timezone
from user_app.models import Address 
from django.views.decorators.http import require_POST 
from datetime import timezone
from django.template.loader import get_template
from io import BytesIO

def is_admin(user):
    return user.is_staff or user.is_superuser

# Admin Views
@login_required
@user_passes_test(is_admin)
@never_cache
def admin_orders_list(request):
    """Admin view for listing all orders"""
    search_query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', '-order_date')
    status_filter = request.GET.get('status', '')

    orders = Order.objects.all().select_related('user', 'shipping_address', 'coupon')
    
    if search_query:
        orders = orders.filter(
            Q(order_id__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query) |
            Q(user__full_name__icontains=search_query)
        )
    
    if status_filter:
        orders = orders.filter(status=status_filter)

    valid_sorts = ['order_date', '-order_date', 'total_amount', '-total_amount']
    sort_by = sort_by if sort_by in valid_sorts else '-order_date'
    orders = orders.order_by(sort_by)

    paginator = Paginator(orders, 10)  # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if 'clear' in request.GET:
        return redirect('cart_and_orders_app:admin_orders_list')

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'sort_by': sort_by,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'admin_orders_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_order_detail(request, order_id):
    """Admin view for order details and status updates"""
    order = get_object_or_404(Order, order_id=order_id)
    
    if request.method == 'POST':
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            old_status = order.status
            order = form.save()
            if order.status == 'Pending' and old_status != 'Pending':
                order.decrease_stock()
            elif order.status == 'Cancelled' and old_status != 'Cancelled':
                order.restore_stock()
            messages.success(request, f"Order {order.order_id} status updated to {order.status}")
            return redirect('cart_and_orders_app:admin_orders_list')
    else:
        form = OrderStatusForm(instance=order)

    context = {
        'order': order,
        'form': form,
        'order_items': order.items.all(),
        'return_requests': order.return_requests.all(),
    }
    return render(request, 'admin_order_detail.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_verify_return_request(request, return_id):
    """Admin view for verifying and processing return requests"""
    return_request = get_object_or_404(ReturnRequest, id=return_id)
    order = return_request.order

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            return_request.is_verified = True
            return_request.process_refund()
            order.status = 'Cancelled'
            order.save()
            messages.success(request, f"Return request for {order.order_id} approved and refunded")
        elif action == 'reject':
            return_request.is_verified = False
            return_request.refund_processed = False
            return_request.save()
            messages.warning(request, f"Return request for {order.order_id} rejected")
        return redirect('cart_and_orders_app:admin_orders_list')

    context = {
        'return_request': return_request,
        'order': order,
    }
    return render(request, 'admin_verify_return.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_inventory_list(request):
    """Admin view for inventory/stock management"""
    search_query = request.GET.get('q', '')
    variants = ProductVariant.objects.all().select_related('product')

    if search_query:
        variants = variants.filter(
            Q(product__product_name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(flavor__icontains=search_query) |
            Q(size_weight__icontains=search_query)
        )

    paginator = Paginator(variants, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    if 'clear' in request.GET:
        return redirect('cart_and_orders_app:admin_inventory_list')

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'admin_inventory_list.html', context)

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_update_stock(request, variant_id):
    """Admin view for updating product variant stock"""
    variant = get_object_or_404(ProductVariant, id=variant_id)
    
    if request.method == 'POST':
        try:
            new_stock = int(request.POST.get('stock', 0))
            if new_stock >= 0:
                variant.stock = new_stock
                variant.save()
                messages.success(request, f"Stock updated for {variant.product.product_name}")
                return redirect('cart_and_orders_app:admin_inventory_list')
            else:
                messages.error(request, "Stock cannot be negative")
        except ValueError:
            messages.error(request, "Invalid stock value")

    context = {
        'variant': variant,
    }
    return render(request, 'admin_update_stock.html', context)

@login_required
@never_cache
def user_cart_list(request):
    """Display the user's cart."""
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = cart.items.all()
    has_out_of_stock = any(item.variant.stock <= 0 for item in cart_items)
    context = {
        'cart': cart,
        'cart_items': cart_items,
        'has_out_of_stock': has_out_of_stock,
    }
    return render(request, 'user_cart_list.html', context)

@require_POST
@login_required
def user_add_to_cart(request, variant_id):
    try:
        data = json.loads(request.body) if request.body else {}
        quantity = int(data.get('quantity', 1))
        variant = get_object_or_404(ProductVariant, id=variant_id)

        if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active:
            return JsonResponse({'success': False, 'message': 'This product is not available.'}, status=400)

        if variant.stock < quantity:
            return JsonResponse({'success': False, 'message': f'Only {variant.stock} items left in stock.'}, status=400)

        MAX_QUANTITY = 10
        if quantity > MAX_QUANTITY:
            return JsonResponse({'success': False, 'message': f'Maximum limit of {MAX_QUANTITY} reached.'}, status=400)

        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_item, item_created = CartItem.objects.get_or_create(cart=cart, variant=variant)
        if not item_created:
            cart_item.quantity += quantity
            if cart_item.quantity > variant.stock:
                return JsonResponse({'success': False, 'message': 'Not enough stock available.'}, status=400)
            if cart_item.quantity > MAX_QUANTITY:
                return JsonResponse({'success': False, 'message': f'Maximum limit of {MAX_QUANTITY} reached.'}, status=400)
        cart_item.save()

        return JsonResponse({
            'success': True,
            'message': 'Item added to cart successfully',
            'cart_count': cart.items.count()
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
def user_remove_from_cart(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    product_name = cart_item.variant.product.product_name
    cart_item.delete()
    messages.success(request, f"{product_name} removed from cart.")
    return redirect('cart_and_orders_app:user_cart_list')

@require_POST
@login_required
def buy_now(request):
    try:
        data = json.loads(request.body)
        variant_id = data.get('variant_id')
        quantity = int(data.get('quantity', 1))

        if not variant_id or quantity < 1:
            return JsonResponse({
                'success': False,
                'message': 'Invalid variant or quantity'
            }, status=400)

        # Get the variant
        variant = get_object_or_404(ProductVariant, id=variant_id)

        # Check if product is available
        if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active:
            return JsonResponse({
                'success': False,
                'message': 'This product is not available.'
            }, status=400)

        # Check stock
        if variant.stock < quantity:
            return JsonResponse({
                'success': False,
                'message': f'Only {variant.stock} items left in stock.'
            }, status=400)

        # Check maximum quantity limit
        MAX_QUANTITY = 10
        if quantity > MAX_QUANTITY:
            return JsonResponse({
                'success': False,
                'message': f'Maximum limit of {MAX_QUANTITY} reached.'
            }, status=400)

        # Clear existing cart and add the selected item
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart.items.all().delete()

        CartItem.objects.create(
            cart=cart,
            variant=variant,
            quantity=quantity
        )

        # Remove from wishlist if present
        Wishlist.objects.filter(user=request.user, variant=variant).delete()

        return JsonResponse({
            'success': True,
            'message': 'Item added to cart for immediate checkout',
            'cart_count': cart.items.count(),
            'wishlist_count': Wishlist.objects.filter(user=request.user).count()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)

@login_required
def user_update_cart_quantity(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    MAX_QUANTITY = 10
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'increment':
            if cart_item.quantity + 1 > cart_item.variant.stock:
                return JsonResponse({'success': False, 'message': f"Only {cart_item.variant.stock} items left in stock."})
            elif cart_item.quantity + 1 > MAX_QUANTITY:
                return JsonResponse({'success': False, 'message': f"Maximum limit of {MAX_QUANTITY} reached."})
            else:
                cart_item.quantity += 1
                cart_item.save()
                return JsonResponse({'success': True, 'message': "Quantity updated."})
        elif action == 'decrement':
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
                return JsonResponse({'success': True, 'message': "Quantity updated."})
            else:
                cart_item.delete()
                return JsonResponse({'success': True, 'message': f"{cart_item.variant.product.product_name} removed from cart."})
    return JsonResponse({'success': False, 'message': "Invalid request."}, status=400)

# Wishlist views
@login_required
@never_cache
def user_wishlist(request):
    wishlist_items = Wishlist.objects.filter(user=request.user).select_related('variant__product')
    context = {
        'wishlist_items': wishlist_items,
    }
    return render(request, 'user_wishlist.html', context)

@login_required
def user_add_to_wishlist(request, variant_id):
    variant = get_object_or_404(ProductVariant, id=variant_id)
    
    if not variant.is_active or not variant.product.is_active or not variant.product.category.is_active:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'This product is not available.'})
        messages.error(request, "This product is not available.")
        return redirect('product_app:user_product_detail', slug=variant.product.slug)
    
    wishlist_item, created = Wishlist.objects.get_or_create(user=request.user, variant=variant)
    wishlist_count = Wishlist.objects.filter(user=request.user).count()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': created,
            'message': f"{variant.product.product_name} {'added to' if created else 'already in'} your wishlist!",
            'wishlist_count': wishlist_count,
            'wishlist_item': {
                'id': wishlist_item.id,
                'variant_id': variant.id,
                'product_name': variant.product.product_name,
                'product_slug': variant.product.slug,
                'flavor': variant.flavor or 'Standard',
                'size_weight': variant.size_weight or 'N/A',
                'price': str(variant.price),  # Convert Decimal to string
                'stock': variant.stock,
            } if created else None
        })
    
    if created:
        messages.success(request, f"{variant.product.product_name} added to wishlist!")
    else:
        messages.info(request, f"{variant.product.product_name} is already in your wishlist.")
    
    return redirect('cart_and_orders_app:user_wishlist')

@login_required
def user_remove_from_wishlist(request, wishlist_id):
    """Remove an item from the wishlist."""
    wishlist_item = get_object_or_404(Wishlist, id=wishlist_id, user=request.user)
    product_name = wishlist_item.variant.product.product_name
    wishlist_item.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': f"{product_name} removed from wishlist."
        })
    messages.success(request, f"{product_name} removed from wishlist.")
    return redirect('cart_and_orders_app:user_wishlist')

@login_required
def check_wishlist(request):
    """Check for new wishlist items."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Get the last time this user checked their wishlist
        last_check_time = request.session.get('last_wishlist_check', None)
        
        # Update the last check time to now
        now = timezone.now()
        request.session['last_wishlist_check'] = now.timestamp()
        
        # If no previous check, just return empty list (first visit)
        if last_check_time is None:
            return JsonResponse({'success': True, 'new_items': []})
        
        # Convert timestamp back to datetime
        from datetime import timezone as dt_timezone
        last_check = timezone.datetime.fromtimestamp(last_check_time, tz=dt_timezone.utc)
        
        # Rest of the function remains the same
        new_items = []
        recent_wishlist_items = Wishlist.objects.filter(
            user=request.user,
            created_at__gt=last_check
        ).select_related('variant__product')
        
        for item in recent_wishlist_items:
            new_items.append({
                'id': item.id,
                'variant_id': item.variant.id,
                'product_name': item.variant.product.product_name,
                'product_slug': item.variant.product.slug,
                'flavor': item.variant.flavor or 'Standard',
                'size_weight': item.variant.size_weight or 'N/A',
                'price': str(item.variant.price),
                'stock': item.variant.stock,
            })
        
        return JsonResponse({
            'success': True,
            'new_items': new_items
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

@require_POST
@login_required
def set_buy_now_flag(request):
    try:
        data = json.loads(request.body)
        request.session['from_buy_now'] = data.get('from_buy_now', False)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
@never_cache
def user_checkout(request):
    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect('cart_and_orders_app:user_cart_list')

    out_of_stock_items = [item for item in cart_items if item.quantity > item.variant.stock]
    if out_of_stock_items:
        messages.error(request, "Some items are out of stock. Please update your cart.")
        return redirect('cart_and_orders_app:user_cart_list')

    addresses = Address.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first()
    if not default_address:
        messages.warning(request, "Please set a default shipping address.")
        return redirect('user_app:user_address_list')

    subtotal = sum(float(item.price or item.variant.price) * item.quantity for item in cart_items)
    shipping_cost = 50.0  # Default
    tax = subtotal * 0.05
    discount = 0.0
    coupon_code = None

    if 'applied_coupon' in request.session:
        coupon_data = request.session['applied_coupon']
        discount = float(coupon_data['discount'])
        coupon_code = coupon_data['code']
        try:
            coupon = Coupon.objects.get(code=coupon_code)
            current_discount = coupon.get_discount_amount(subtotal, cart_items)
            if not coupon.is_valid or current_discount != discount:
                messages.warning(request, "Coupon is no longer valid.")
                del request.session['applied_coupon']
                discount = 0.0
                coupon_code = None
        except Coupon.DoesNotExist:
            del request.session['applied_coupon']
            discount = 0.0
            coupon_code = None

    total = subtotal + shipping_cost + tax - discount

    context = {
        'cart_items': cart_items,
        'addresses': addresses,
        'default_address': default_address,
        'subtotal': subtotal,
        'shipping_cost': shipping_cost,
        'tax': tax,
        'discount': discount,
        'total': total,
        'is_buy_now': request.session.get('from_buy_now', False),
        'coupon_code': coupon_code,
    }
    if 'from_buy_now' in request.session:
        del request.session['from_buy_now']

    return render(request, 'checkout.html', context)


@login_required
def place_order(request):
    if request.method != 'POST':
        return redirect('cart_and_orders_app:user_checkout')

    cart = get_object_or_404(Cart, user=request.user)
    cart_items = cart.items.all()
    default_address = Address.objects.filter(user=request.user, is_default=True).first()
    if not default_address:
        messages.error(request, "Please set a default shipping address.")
        return redirect('cart_and_orders_app:user_checkout')
    if not cart_items:
        messages.error(request, "Your cart is empty.")
        return redirect('cart_and_orders_app:user_cart_list')

    for item in cart_items:
        if item.quantity > item.variant.stock:
            messages.error(request, f"{item.variant.product.product_name} is out of stock.")
            return redirect('cart_and_orders_app:user_cart_list')

    subtotal = sum(float(item.price or item.variant.price) * item.quantity for item in cart_items)
    shipping_method = request.POST.get('shipping_method', 'standard')
    shipping_cost = 50.0 if shipping_method == 'standard' else 100.0
    tax_rate = 0.05
    tax = subtotal * tax_rate
    discount = 0.0
    coupon = None

    if 'applied_coupon' in request.session:
        coupon_data = request.session['applied_coupon']
        discount = float(coupon_data['discount'])
        try:
            coupon = Coupon.objects.get(code=coupon_data['code'])
            user_coupon = UserCoupon.objects.get(user=request.user, coupon=coupon)
            if not coupon.is_valid or user_coupon.is_used:
                messages.error(request, "The applied coupon is no longer valid.")
                del request.session['applied_coupon']
                return redirect('cart_and_orders_app:user_checkout')
        except (Coupon.DoesNotExist, UserCoupon.DoesNotExist):
            messages.error(request, "Invalid coupon data.")
            del request.session['applied_coupon']
            return redirect('cart_and_orders_app:user_checkout')

    total = subtotal + shipping_cost + tax - discount

    try:
        with transaction.atomic():
            order = Order.objects.create(
                user=request.user,
                shipping_address=default_address,
                total_amount=total,
                discount_amount=discount,
                coupon=coupon,
                status='Pending',
                payment_method=request.POST.get('payment_method', 'COD')
            )
            order.cart_items.set(cart_items)
            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    variant=item.variant,
                    quantity=item.quantity,
                    price=item.price or item.variant.price
                )
            order.decrease_stock()
            cart_items.delete()
            if 'user_coupon' in locals():
                user_coupon.is_used = True
                user_coupon.used_at = timezone.now()
                user_coupon.order = order
                user_coupon.save()
                coupon.usage_count += 1
                coupon.save()
                del request.session['applied_coupon']
            messages.success(request, "Order placed successfully!")
            return redirect('cart_and_orders_app:user_order_success', order_id=order.order_id)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('cart_and_orders_app:user_cart_list')
    except Exception as e:
        messages.error(request, f"Failed to place order: {str(e)}")
        return redirect('cart_and_orders_app:user_checkout')

@login_required
@never_cache
def user_order_success(request, order_id):
    """Display order success page."""
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    context = {
        'order': order,
    }
    return render(request, 'user_order_success.html', context)

def checkout_view(request):
    if request.method == "POST":
        order_placed_successfully = True  
        
        if order_placed_successfully:
            return redirect('order_placed')
        else:
            messages.error(request, "There was an issue placing your order.")
            return render(request, 'checkout.html', {'user_order_success': False})
    return render(request, 'checkout.html', {'user_order_success': False})

def order_placed(request):
    return render(request, 'order_placed.html', {'user_order_success': True})

@login_required
def user_order_list(request):
    search_query = request.GET.get('q', '')  
    status_filter = request.GET.get('status', '') 
    orders = Order.objects.filter(user=request.user)
    if search_query:
        orders = orders.filter(
            Q(order_id__icontains=search_query) |
            Q(status__icontains=search_query)
        )
    if status_filter:
        orders = orders.filter(status=status_filter)

    context = {
        'orders': orders,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,  
    }
    return render(request, 'user_order_list.html', context)

@login_required
def user_order_detail(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    context = {
        'order': order,
    }
    return render(request, 'user_order_detail.html', context)

@login_required
def user_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if request.method == 'POST':
        reason = request.POST.get('reason', '')  # Optional reason for cancellation
        if order.status in ['Pending', 'Shipped']:  # Only allow cancellation for certain statuses
            order.status = 'Cancelled'
            order.save()
            order.restore_stock()  # Restore stock for cancelled items
            messages.success(request, f"Order {order.order_id} has been cancelled.")
            return redirect('cart_and_orders_app:user_order_list')
        else:
            messages.error(request, "This order cannot be cancelled.")
            return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    context = {
        'order': order,
    }
    return render(request, 'user_cancel_order.html', context)

@login_required
def user_return_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    if request.method == 'POST':
        reason = request.POST.get('reason', '') 
        if order.status == 'Delivered' and reason: 
            ReturnRequest.objects.create(order=order, reason=reason)
            messages.success(request, "Return request submitted. We will process it shortly.")
            return redirect('cart_and_orders_app:user_order_list')
        else:
            messages.error(request, "This order cannot be returned or the reason is missing.")
            return redirect('cart_and_orders_app:user_order_detail', order_id=order.order_id)
    context = {
        'order': order,
    }
    return render(request, 'user_return_order.html', context)

def generate_pdf(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    template = get_template('invoice.html')
    context = {'order': order}
    html = template.render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=invoice_{order.order_id}.pdf'
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error generating PDF', status=500)
    return response

@login_required
@user_passes_test(is_admin)
@never_cache
def admin_bulk_actions(request):
    """Handle bulk actions for orders (e.g., mark as shipped or cancel)"""
    if request.method == 'POST':
        order_ids = request.POST.getlist('order_ids')
        action = request.POST.get('action')

        if not order_ids or not action:
            messages.error(request, "No orders or action selected.")
            return redirect('cart_and_orders_app:admin_orders_list')

        orders = Order.objects.filter(id__in=order_ids)

        if action == 'mark_shipped':
            orders.update(status='Shipped')
            messages.success(request, f"Marked {len(order_ids)} orders as Shipped.")
        elif action == 'cancel':
            orders.update(status='Cancelled')
            for order in orders:
                order.restore_stock()
            messages.success(request, f"Cancelled {len(order_ids)} orders and restored stock.")
        else:
            messages.error(request, "Invalid action.")
            return redirect('cart_and_orders_app:admin_orders_list')

        return redirect('cart_and_orders_app:admin_orders_list')

    return redirect('cart_and_orders_app:admin_orders_list')

def download_invoice(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    template = get_template('invoice.html')
    context = {'order': order}
    html = template.render(context)
    buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=buffer)
    if pisa_status.err:
        return HttpResponse('Error generating PDF', status=500)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=invoice_{order.order_id}.pdf'
    return response

@login_required
@user_passes_test(is_admin)
def admin_mark_shipped(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    order.status = 'Shipped'
    order.save()
    messages.success(request, f"Order {order.order_id} marked as shipped.")
    return redirect('cart_and_orders_app:admin_orders_list')

@login_required
@user_passes_test(is_admin)
def admin_cancel_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id)
    if request.method == 'POST':
        order.status = 'Cancelled'
        order.save()
        order.restore_stock()  # Restore stock for cancelled items
        messages.success(request, f"Order {order.order_id} has been cancelled.")
        return redirect('cart_and_orders_app:admin_orders_list')
    context = {
        'order': order,
    }
    return render(request, 'admin_cancel_order.html', context)

@login_required
def check_wishlist_updates(request):
    """Check for new wishlist items since last check."""
    last_check = request.session.get('last_wishlist_check', None)
    now = timezone.now()
    new_items = Wishlist.objects.filter(user=request.user, added_at__gt=last_check).select_related('variant__product')
    request.session['last_wishlist_check'] = now.isoformat()
    
    return JsonResponse({
        'new_items': [{
            'id': item.id,
            'variant_id': item.variant.id,
            'product_name': item.variant.product.product_name,
            'product_slug': item.variant.product.slug,
            'flavor': item.variant.flavor or 'Standard',
            'size_weight': item.variant.size_weight or 'N/A',
            'price': str(item.variant.price),
            'stock': item.variant.stock,
        } for item in new_items]
    })
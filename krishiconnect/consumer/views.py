from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.http import JsonResponse
from farmer.models import Product
from .models import Cart, CartItem, Order, OrderItem, Notification, ProductReview
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timesince import timesince
from django.utils import timezone
from django.db.models import F
from django.db.models import Avg, Count
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json
import razorpay
import threading

# Create your views here.

@login_required
def consumer_dashboard(request):
    products = Product.objects.annotate(avg_rating=Avg('productreview__rating'), review_count=Count('productreview')).order_by('price').all()

    # Filter by City (Only show products from farmers in the same city)
    try:
        user_city = request.user.userprofile.city
        if user_city:
            products = products.filter(farmer__userprofile__city__iexact=user_city)
        else:
            products = Product.objects.none()
    except Exception:
        products = Product.objects.none()

    # Filter by Category
    category = request.GET.get('category')
    if category:
        products = products.filter(category=category)

    # Sort by Price or Rating
    sort_by = request.GET.get('sort')
    if sort_by == 'price_high':
        products = products.order_by('-price')
    elif sort_by == 'rating':
        products = products.order_by('-avg_rating')
    else:
        products = products.order_by('price')
        sort_by = 'price_low'

    # Pagination
    paginator = Paginator(products, 12)  # Show 12 products per page
    page = request.GET.get('page')
    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        products = paginator.page(1)
    except EmptyPage:
        products = paginator.page(paginator.num_pages)

    orders = Order.objects.filter(user=request.user).annotate(item_count=Count('items')).prefetch_related('items__product__farmer').order_by('-created_at')
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    unread_count = notifications.filter(is_read=False).count()
    
    cities = [
        "Ahmednagar (अहमदनगर)", "Akola (अकोला)", "Amravati (अमरावती)", "Chhatrapati Sambhajinagar (छत्रपती संभाजीनगर )", 
        "Beed (बीड)", "Bhandara (भंडारा)", "Buldhana (बुलढाणा)", "Chandrapur (चंद्रपूर)", "Dhule (धुळे)", 
        "Gadchiroli (गडचिरोली)", "Gondia (गोंदिया)", "Hingoli (हिंगोली)", "Jalgaon (जळगाव)", "Jalna (जालना)", 
        "Kolhapur (कोल्हापूर)", "Latur (लातूर)", "Mumbai (मुंबई)", "Nagpur (नागपूर)", "Nanded (नांदेड)", 
        "Nandurbar (नंदुरबार)", "Nashik (नाशिक)", "Dharashiv (धाराशिव)", "Palghar (पालघर)", 
        "Parbhani (परभणी)", "Pune (पुणे)", "Raigad (रायगड)", "Ratnagiri (रत्नागिरी)", "Sangli (सांगली)", 
        "Satara (सातारा)", "Sindhudurg (सिंधुदुर्ग)", "Solapur (सोलापूर)", "Thane (ठाणे)", "Wardha (वर्धा)", 
        "Washim (वाशिम)", "Yavatmal (यवतमाळ)"
    ]

    following = request.user.following.all().select_related('user')

    context = {
        'products': products, 
        'orders': orders,
        'notifications': notifications,
        'unread_count': unread_count,
        'current_category': category,
        'current_sort': sort_by,
        'cities': cities,
        'following_farmers': following,
    }
    try:
        context['user_address'] = request.user.userprofile.address
        context['user_phone'] = request.user.userprofile.phone
        context['user_city'] = request.user.userprofile.city
        
        if not context['user_address'] or not context['user_phone'] or not context['user_city']:
            context['profile_incomplete'] = True
    except Exception:
        context['user_address'] = ''
        context['user_phone'] = ''
        context['user_city'] = ''
        context['profile_incomplete'] = True
        
    return render(request, 'consumer_dashboard.html', context)

@login_required
def add_to_cart(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        cart, created = Cart.objects.get_or_create(user=request.user)
        
        # Check if cart has items from a different farmer
        if cart.items.exists():
            existing_item = cart.items.first()
            if existing_item.product.farmer != product.farmer:
                # Check if the product being added is from the same farmer as existing items
                # This logic is already present and correct, ensuring single-farmer orders.
                # No change needed here, but it's good to acknowledge its purpose.
                
                return JsonResponse({
                    'status': 'error', 
                    'message': 'You can only buy products from one farmer at a time. Please clear your cart or complete the current order.'
                }, status=400)

        # Check if adding to cart would exceed available stock
        # Get existing item quantity or assume 0 if new
        existing_cart_item_quantity = 0
        try:
            existing_cart_item = CartItem.objects.get(cart=cart, product=product)
            existing_cart_item_quantity = existing_cart_item.quantity
        except CartItem.DoesNotExist:
            pass

        if product.stock <= 0:
            return JsonResponse({'status': 'error', 'message': f'{product.name} is out of stock and cannot be added to the cart.'}, status=400)
        if existing_cart_item_quantity + 1 > product.stock:
            return JsonResponse({'status': 'error', 'message': f'Cannot add more {product.name}. Only {product.stock} available in stock.'}, status=400)

        # If stock is sufficient, proceed to add/update cart item
        cart_item, item_created = CartItem.objects.get_or_create(cart=cart, product=product)
        
        if not item_created:
            cart_item.quantity += 1
            cart_item.save()
        
        return JsonResponse({'status': 'success', 'message': 'Item added to cart'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def get_cart(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    items = []
    total = 0
    for item in cart.items.all():
        item_total = item.quantity * item.product.price
        items.append({
            'id': item.product.id,
            'name': item.product.name,
            'description': item.product.description,
            'price': item.product.price,
            'quantity': item.quantity,
            'total': item_total,
            'farmer_name': item.product.farmer.get_full_name() or item.product.farmer.username
        })
        total += item_total
    
    return JsonResponse({'items': items, 'total': total})

@login_required
def update_cart_item(request, product_id, action):
    if request.method == 'POST':
        cart = get_object_or_404(Cart, user=request.user)
        product = get_object_or_404(Product, id=product_id)
        cart_item = get_object_or_404(CartItem, cart=cart, product=product)

        if action == 'increase':
            # Check if increasing quantity exceeds available stock
            if cart_item.quantity + 1 > product.stock:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Cannot add more {product.name}. Only {product.stock} available in stock.'
                }, status=400)
            cart_item.quantity += 1
            cart_item.save()
        elif action == 'decrease':
            cart_item.quantity -= 1
            if cart_item.quantity > 0:
                cart_item.save()
            else:
                cart_item.delete()
        
        return JsonResponse({'status': 'success', 'message': 'Cart updated'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def clear_cart(request):
    if request.method == 'POST':
        try:
            cart = Cart.objects.get(user=request.user)
            cart.items.all().delete()
            return JsonResponse({'status': 'success', 'message': 'Cart cleared successfully'})
        except Cart.DoesNotExist:
            # If cart doesn't exist, it's already clear.
            return JsonResponse({'status': 'success', 'message': 'Cart is already empty'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def farmer_profile_view(request, farmer_id):
    farmer_user = get_object_or_404(User, id=farmer_id, userprofile__user_type='farmer')
    
    # Get unique categories for the farmer's products
    product_categories = Product.objects.filter(farmer=farmer_user).values_list('category', flat=True).distinct()
    
    # Map category slugs to full names for display
    # This is based on the options in farmer_dashboard.html and translations.js
    category_display_map = {
        'vegetables': 'Vegetables',
        'fruits': 'Fruits',
        'grains': 'Grains',
        'pulses': 'Pulses',
        'spices': 'Spices',
        'others': 'Others',
    }
    
    categories = [category_display_map.get(cat, cat.capitalize()) for cat in product_categories]

    # Calculate average rating
    reviews = ProductReview.objects.filter(product__farmer=farmer_user)
    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    review_count = reviews.count()

    # Fetch products
    products = Product.objects.filter(farmer=farmer_user)
    
    # Check follow status
    is_following = False
    if request.user.is_authenticated:
        is_following = request.user in farmer_user.userprofile.followers.all()

    follower_count = farmer_user.userprofile.followers.count()

    context = {
        'farmer_user': farmer_user,
        'categories': categories,
        'avg_rating': round(avg_rating, 1),
        'review_count': review_count,
        'products': products,
        'is_following': is_following,
        'follower_count': follower_count,
    }
    return render(request, 'farmer_profile.html', context)

@login_required
def toggle_follow_farmer(request, farmer_id):
    if request.method == 'POST':
        farmer = get_object_or_404(User, id=farmer_id)
        
        # Prevent users from following themselves
        if farmer == request.user:
            return JsonResponse({'status': 'error', 'message': 'You cannot follow yourself.'}, status=400)
            
        try:
            if request.user in farmer.userprofile.followers.all():
                farmer.userprofile.followers.remove(request.user)
                is_following = False
                msg = "Unfollowed successfully"
            else:
                farmer.userprofile.followers.add(request.user)
                is_following = True
                msg = "Followed successfully"
            follower_count = farmer.userprofile.followers.count()
            return JsonResponse({'status': 'success', 'is_following': is_following, 'message': msg, 'follower_count': follower_count})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
def message_farmer(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            farmer_id = data.get('farmer_id')
            message_text = data.get('message')
            product_name = data.get('product_name')
            
            farmer = get_object_or_404(User, id=farmer_id)
            
            # Prevent users from messaging themselves
            if farmer == request.user:
                return JsonResponse({'status': 'error', 'message': 'You cannot send a message to yourself.'}, status=400)
            
            full_message = f"Inquiry from {request.user.get_full_name() or request.user.username}"
            if product_name:
                full_message += f" regarding {product_name}"
            full_message += f": {message_text}"
            
            Notification.objects.create(
                user=farmer,
                sender=request.user,
                message=full_message
            )
            return JsonResponse({'status': 'success', 'message': 'Message sent successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

def send_order_emails_task(order_id):
    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        return

    # Prepare data
    consumer_items_list = []
    farmers_notification_data = {}

    for item in order.items.all():
        consumer_items_list.append(f"{item.product.name} ({item.quantity} kg) - ₹{item.price * item.quantity}")
        farmer = item.product.farmer
        if farmer not in farmers_notification_data:
            farmers_notification_data[farmer] = []
        farmers_notification_data[farmer].append(f"{item.product.name} ({item.quantity} kg)")

    # Email for Consumer
    if order.user.email:
        subject = f"Order Confirmation - Order #{order.id}"
        message = f"Dear {order.user.get_full_name() or order.user.username},\n\nThank you for shopping with Krishi Connect! Your order has been placed successfully.\n\nOrder Details:\n" + "\n".join(consumer_items_list) + f"\n\nTotal Amount: ₹{order.total_amount}\nPayment Method: {order.payment_method}\nShipping Address: {order.shipping_address}\n\nWe will notify you once your order is shipped.\n\nRegards,\nKrishi Connect Team"
        try:
            send_mail(subject, message, settings.EMAIL_HOST_USER, [order.user.email], fail_silently=True)
        except Exception:
            pass

    # Send Email and Notifications to Farmers
    consumer_name = order.user.get_full_name() or order.user.username
    consumer_email = order.user.email
    try:
        consumer_phone = order.user.userprofile.phone
    except:
        consumer_phone = "N/A"

    for farmer, products in farmers_notification_data.items():
        # Create Notification
        Notification.objects.create(
            user=farmer,
            order=order,
            message=f"New Order! Items: {', '.join(products)}"
        )

        # Send Email
        if farmer.email:
            farmer_name = farmer.get_full_name() or farmer.username
            subject = "New Order Received - Krishi Connect"
            message = f"Hello {farmer_name},\n\nYou have received a new order for your products!\n\n" \
                      f"Consumer Details:\nName: {consumer_name}\nPhone: {consumer_phone}\nEmail: {consumer_email}\nAddress: {order.shipping_address}\n\n" \
                      f"Items Sold:\n" + "\n".join(products) + \
                      f"\n\nPlease login to your dashboard to view details and process the order.\n\nRegards,\nKrishi Connect Team"
            try:
                send_mail(subject, message, settings.EMAIL_HOST_USER, [farmer.email], fail_silently=True)
            except Exception:
                pass

def trigger_order_emails(order_id):
    threading.Thread(target=send_order_emails_task, args=(order_id,)).start()

@login_required
def checkout(request):
    if request.method == 'POST':
        cart = Cart.objects.filter(user=request.user).first()
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or (request.content_type and 'application/json' in request.content_type)

        if not cart or not cart.items.exists():
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Cart is empty'}, status=400)
            messages.error(request, 'Cart is empty')
            return redirect('consumer:consumer_dashboard')
        
        address = request.POST.get('address')
        payment_method = request.POST.get('payment_method')

        if is_ajax and not address and not payment_method:
            try:
                data = json.loads(request.body)
                address = data.get('address')
                payment_method = data.get('payment_method')
            except Exception:
                pass

        if not address:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Shipping address is required'}, status=400)
            messages.error(request, 'Shipping address is required')
            return redirect('consumer:consumer_dashboard')

        total = sum(item.product.price * item.quantity for item in cart.items.all())
        
        order = Order.objects.create(
            user=request.user,
            total_amount=total,
            status='Pending',
            shipping_address=address,
            payment_method=payment_method or 'COD'
        )
        
        # Razorpay Order Creation
        razorpay_order_id = None
        if payment_method == 'Online':
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            try:
                razorpay_order = client.order.create(dict(
                    amount=int(total * 100),
                    currency='INR',
                    payment_capture='1'
                ))
                razorpay_order_id = razorpay_order['id']
                order.razorpay_order_id = razorpay_order_id
                order.save()
            except Exception as e:
                order.delete() # Cleanup the order since payment initialization failed
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': f'Payment Gateway Error: {str(e)}'}, status=400)
                messages.error(request, 'Error initializing payment. Please check your configuration.')
                return redirect('consumer:consumer_dashboard')

        # Collect products that need post-purchase processing (notification/deletion)
        products_to_process_after_stock_update = []

        for item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price
            )
            
            # Atomically reduce product stock to prevent race conditions
            # Use F() expression to update the stock directly in the database
            Product.objects.filter(id=item.product.id).update(stock=F('stock') - item.quantity)
            
            # Re-fetch the product instance to get its updated stock value
            # This is crucial for the subsequent check (product.stock <= 0)
            item.product.refresh_from_db()
            
            if item.product.stock <= 0:
                products_to_process_after_stock_update.append(item.product)

        # After all items are processed and stock updated, handle out-of-stock notifications
        for product in products_to_process_after_stock_update:
            # The product is now out of stock (stock <= 0)
            # Instead of deleting it, we will just notify the farmer.
            # The frontend should now display this product as "Out of Stock".
            update_product_url = reverse('farmer:farmer_dashboard') + f'?edit_id={product.id}'
            notification_message = (
                f"Your product '{product.name}' is now out of stock. "
                f"<a href='{update_product_url}'>Please add new stock or remove the product listing.</a>"
            )
            Notification.objects.create(user=product.farmer, message=notification_message)
       
        cart.items.all().delete()
        
        if is_ajax:
            response_data = {'status': 'success', 'message': 'Order placed successfully', 'order_id': order.id}
            if payment_method == 'Online':
                response_data.update({
                    'razorpay_order_id': razorpay_order_id,
                    'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                    'amount': int(total * 100),
                    'currency': 'INR',
                    'user_email': request.user.email,
                    'user_contact': '', # Initialize user_contact before trying to populate
                    'callback_url': request.build_absolute_uri(reverse('consumer:complete_payment', args=[order.id]))
                })
                print(f"DEBUG: Callback URL sent to frontend: {response_data['callback_url']}")
                try:
                    response_data['user_contact'] = request.user.userprofile.phone
                except Exception:
                    pass
            return JsonResponse(response_data)
        
        if payment_method == 'Online':
            # For non-AJAX requests, render a template to initiate payment
            user_phone = ''
            try:
                user_phone = request.user.userprofile.phone
            except Exception:
                pass

            return render(request, 'payment.html', {
                'order': order,
                'razorpay_order_id': razorpay_order_id,
                'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                'amount': int(total * 100),
                'currency': 'INR',
                'user_email': request.user.email,
                'user_phone': user_phone,
                'callback_url': request.build_absolute_uri(reverse('consumer:complete_payment', args=[order.id]))
            })

        trigger_order_emails(order.id)
        messages.success(request, 'Order placed successfully!')
        return redirect('consumer:consumer_dashboard')
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def cancel_order(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)
        if order.status in ['Pending', 'Processing']:
            # Return items to stock atomically
            for item in order.items.all():
                Product.objects.filter(id=item.product.id).update(stock=F('stock') + item.quantity)

            order.status = 'Cancelled'
            
            msg_extra = ""
            # Notify farmers about cancellation
            farmers = set(item.product.farmer for item in order.items.all())
            
            if order.payment_method == 'Online' and order.transaction_id:
                try:
                    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                    client.payment.refund(order.transaction_id, {
                        "amount": int(round(order.total_amount * 100))
                    })
                    order.refund_status = 'Completed'
                    msg_extra = " Refund processed successfully."
                except Exception as e:
                    print(f"Razorpay Refund Error: {e}")
                    order.refund_status = 'Failed'
                    msg_extra = f" Refund failed: {str(e)}"
            else:
                for farmer in farmers:
                    Notification.objects.create(user=farmer, order=order, message=f"Order #{order.id} cancelled by consumer.")

            order.save()
            Notification.objects.create(
                user=request.user,
                order=order,
                message=f'You have successfully cancelled order #{order.id}.{msg_extra}'
            )
            return JsonResponse({'status': 'success', 'message': f'Order cancelled successfully.{msg_extra}'})
        return JsonResponse({'status': 'error', 'message': 'Cannot cancel order in current status'}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def update_profile(request):
    if request.method == 'POST':
        try:
            user = request.user
            user.first_name = request.POST.get('first_name', user.first_name)
            user.last_name = request.POST.get('last_name', user.last_name)
            user.save()
            
            if hasattr(user, 'userprofile'):
                profile = user.userprofile
                profile.phone = request.POST.get('phone', profile.phone)
                profile.address = request.POST.get('address', profile.address)
                profile.city = request.POST.get('city', profile.city)
                profile.save()
            
            return JsonResponse({'status': 'success', 'message': 'Profile updated successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def mark_notifications_as_read(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            if data.get('action') == 'clear':
                Notification.objects.filter(user=request.user).delete()
                return JsonResponse({'status': 'success', 'message': 'Notifications cleared'})
        except Exception:
            pass
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def get_notifications(request):
    all_notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    unread_count = all_notifications.filter(is_read=False).count()
    recent_notifications = all_notifications[:10]
    
    data = []
    for n in recent_notifications:
        data.append({
            'message': n.message,
            'created_at': timesince(n.created_at) + " ago",
            'is_read': n.is_read
        })
    
    return JsonResponse({'notifications': data, 'unread_count': unread_count})

@login_required
def delete_order(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)
        if order.status == 'Delivered':
            order.delete()
            return JsonResponse({'status': 'success', 'message': 'Order history deleted successfully'})
        return JsonResponse({'status': 'error', 'message': 'Can only delete delivered orders'}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

@login_required
def submit_review(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = data.get('product_id')
            rating = data.get('rating')
            review = data.get('review')
            
            # Verify purchase and delivery
            has_purchased = OrderItem.objects.filter(
                order__user=request.user, 
                product_id=product_id, 
                order__status='Delivered'
            ).exists()
            
            if not has_purchased:
                return JsonResponse({'status': 'error', 'message': 'You can only review delivered products you have purchased.'}, status=403)
            
            ProductReview.objects.create(user=request.user, product_id=product_id, rating=rating, review=review)
            return JsonResponse({'status': 'success', 'message': 'Review submitted successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
@login_required
def complete_payment(request, order_id):
    if request.method == 'POST':
        is_ajax = False
        try:
            # Try to parse as JSON (AJAX request)
            try:
                data = json.loads(request.body)
                is_ajax = True
            except (json.JSONDecodeError, TypeError):
                # Fallback to Form Data (Razorpay Callback)
                data = request.POST

            order = get_object_or_404(Order, id=order_id, user=request.user)
            
            # Check for Razorpay Error (sent on callback failure)
            if 'error[code]' in data:
                error_msg = data.get('error[description]', 'Payment failed')
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
                else:
                    messages.error(request, f"Payment Failed: {error_msg}")
                    return redirect('consumer:consumer_dashboard')

            # Razorpay Verification
            if 'razorpay_payment_id' in data and 'razorpay_signature' in data:
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                params_dict = {
                    'razorpay_order_id': order.razorpay_order_id,
                    'razorpay_payment_id': data['razorpay_payment_id'],
                    'razorpay_signature': data['razorpay_signature']
                }
                try:
                    client.utility.verify_payment_signature(params_dict)
                    order.razorpay_payment_id = data['razorpay_payment_id']
                    order.razorpay_signature = data['razorpay_signature']
                    order.transaction_id = data['razorpay_payment_id']
                    order.status = 'Processing'
                    order.save()
                    trigger_order_emails(order.id)
                    
                    if is_ajax:
                        return JsonResponse({'status': 'success', 'message': 'Payment confirmed successfully'})
                    else:
                        messages.success(request, 'Payment confirmed successfully')
                        return redirect('consumer:consumer_dashboard')

                except razorpay.errors.SignatureVerificationError:
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': 'Payment verification failed'}, status=400)
                    else:
                        messages.error(request, 'Payment verification failed')
                        return redirect('consumer:consumer_dashboard')

            transaction_id = data.get('transaction_id')
            if transaction_id:
                order.transaction_id = transaction_id 
                order.save()
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': 'Payment confirmed successfully'})
                else:
                    messages.success(request, 'Payment confirmed successfully')
                    return redirect('consumer:consumer_dashboard')
            
            # Fallback if no payment data found (e.g. payment failed or cancelled)
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Payment data missing'}, status=400)
            else:
                messages.error(request, 'Payment failed or cancelled')
                return redirect('consumer:consumer_dashboard')

        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            else:
                messages.error(request, f"Error: {str(e)}")
                return redirect('consumer:consumer_dashboard')

    # Handle invalid methods (like GET) by redirecting instead of showing raw JSON
    messages.error(request, 'Invalid request method')
    return redirect('consumer:consumer_dashboard')

@csrf_exempt
def razorpay_webhook(request):
    if request.method == "POST":
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        webhook_signature = request.headers.get('X-Razorpay-Signature')

        try:
            # Verify the webhook signature
            client.utility.verify_webhook_signature(request.body.decode('utf-8'), webhook_signature, webhook_secret)
            
            payload = json.loads(request.body)
            event = payload.get('event')

            if event == 'order.paid':
                data = payload['payload']['order']['entity']
                razorpay_order_id = data['id']
                
                try:
                    order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                    # Only update if not already processed to avoid race conditions
                    if order.status == 'Pending':
                        order.status = 'Processing'
                        # Try to capture payment ID from payload if available
                        if 'payment' in payload['payload'] and 'entity' in payload['payload']['payment']:
                            order.razorpay_payment_id = payload['payload']['payment']['entity']['id']
                            order.transaction_id = payload['payload']['payment']['entity']['id']
                        order.save()
                        trigger_order_emails(order.id)
                except Order.DoesNotExist:
                    pass
            
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'method not allowed'}, status=405)

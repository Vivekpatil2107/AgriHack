from django.urls import path
from . import views

app_name = 'consumer'

urlpatterns = [
    path('dashboard/', views.consumer_dashboard, name='consumer_dashboard'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/', views.get_cart, name='get_cart'),
    path('update-cart-item/<int:product_id>/<str:action>/', views.update_cart_item, name='update_cart_item'),
    path('clear-cart/', views.clear_cart, name='clear_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('cancel-order/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('update-profile/', views.update_profile, name='update_profile'),
    path('notifications/mark-as-read/', views.mark_notifications_as_read, name='mark_notifications_as_read'),
    path('notifications/get/', views.get_notifications, name='get_notifications'),
    path('delete-order/<int:order_id>/', views.delete_order, name='delete_order'),
    path('submit-review/', views.submit_review, name='submit_review'),
    path('complete-payment/<int:order_id>/', views.complete_payment, name='complete_payment'),
    path('consumer/razorpay-webhook/', views.razorpay_webhook, name='razorpay_webhook'),
    path('farmer/<int:farmer_id>/', views.farmer_profile_view, name='farmer_profile'),
    path('follow-farmer/<int:farmer_id>/', views.toggle_follow_farmer, name='toggle_follow_farmer'),
    path('message-farmer/', views.message_farmer, name='message_farmer'),
]

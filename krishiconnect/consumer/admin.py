from django.contrib import admin
from .models import Cart, CartItem, Order, OrderItem, Notification, ProductReview

# Register your models here.
admin.site.register(Cart)
admin.site.register(CartItem)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(Notification)
admin.site.register(ProductReview)

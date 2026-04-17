from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from farmer.models import Product
from consumer.models import ProductReview

class Command(BaseCommand):
    help = 'Deletes expired products and reviews based on category shelf life'

    def handle(self, *args, **kwargs):
        category_days = {
            'vegetables': 8,
            'fruits': 8,
            'grains': 90,
            'pulses': 80,
            'spices': 50,
            'others': 20
        }
        
        now = timezone.now()
        
        for category, days in category_days.items():
            cutoff = now - timedelta(days=days)
            
            # Delete expired products
            deleted_products, _ = Product.objects.filter(category=category, created_at__lt=cutoff).delete()
            if deleted_products > 0:
                self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_products} expired {category} products'))

            # Delete expired reviews
            deleted_reviews, _ = ProductReview.objects.filter(product__category=category, created_at__lt=cutoff).delete()
            if deleted_reviews > 0:
                self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_reviews} expired reviews for {category}'))
                
        self.stdout.write(self.style.SUCCESS('Cleanup complete'))

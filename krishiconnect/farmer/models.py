from django.db import models
from django.contrib.auth.models import User
from django.conf import settings

class Product(models.Model):
    CATEGORY_CHOICES = (
        ('vegetables', 'Vegetables'),
        ('fruits', 'Fruits'),
        ('grains', 'Grains'),
        ('pulses', 'Pulses'),
        ('spices', 'Spices'),
        ('others', 'Others'),
    )

    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='vegetables')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField()
    description = models.TextField()
    image = models.ImageField(upload_to='products/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class PredictionHistory(models.Model):
    farmer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prediction_history')
    image = models.ImageField(upload_to='predictions/')
    created_at = models.DateTimeField(auto_now_add=True)
    plant_name = models.CharField(max_length=255, null=True, blank=True)
    plant_probability = models.FloatField(null=True, blank=True)
    plant_common_names = models.CharField(max_length=500, null=True, blank=True)
    plant_description = models.TextField(null=True, blank=True)
    plant_url = models.URLField(max_length=500, null=True, blank=True)
    is_healthy = models.BooleanField(null=True)
    health_probability = models.FloatField(null=True, blank=True)
    disease_name = models.CharField(max_length=255, null=True, blank=True)
    disease_probability = models.FloatField(null=True, blank=True)
    disease_description = models.TextField(null=True, blank=True)
    disease_treatment = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Prediction for {self.farmer.username} on {self.created_at.strftime('%Y-%m-%d')}"

class GovernmentScheme(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    link = models.URLField(max_length=500, blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    added_on = models.DateTimeField(auto_now_add=True)
    eligibility_criteria = models.TextField(null=True, blank=True, help_text="Details about who is eligible for this scheme")
    related_documents = models.TextField(null=True, blank=True, help_text="List of documents required to apply")

    def __str__(self):
        return self.title

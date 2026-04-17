
from django.urls import path, include
from django.conf import settings
from . import views

app_name = 'farmer'

urlpatterns = [
     
    
    path('farmer_dashboard/', views.farmer_dashboard, name='farmer_dashboard'),
    path('weather_info/', views.weather_info, name='weather_info'),
    path('sales_history/', views.sales_history, name='sales_history'),
    path('download_sales_report/', views.download_sales_report, name='download_sales_report'),
    path('manage_order/<int:order_id>/', views.manage_order, name='manage_order'),
    path('market_prices/', views.market_prices, name='market_prices'),
    path('plant_disease_prediction/', views.plant_disease_prediction, name='plant_disease_prediction'),
    path('prediction_history/', views.prediction_history, name='prediction_history'),
    path('followers/', views.followers_list, name='followers_list'),
    path('reply-to-consumer/', views.reply_to_consumer, name='reply_to_consumer'),
    path('govt-schemes/', views.govt_schemes, name='govt_schemes'),
]
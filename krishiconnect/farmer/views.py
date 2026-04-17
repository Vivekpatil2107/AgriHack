from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count, Prefetch, JSONField
from farmer.models import Product, PredictionHistory, GovernmentScheme
from consumer.models import Order, OrderItem, Notification, ProductReview
from .forms import ProductForm
import random
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta, datetime
import csv
from .config import API_KEY
import json
from urllib.request import urlopen
from urllib.parse import urlencode
import razorpay
import difflib
from django.core.paginator import Paginator
import requests, threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
from django.core.files.base import ContentFile
import re
import logging

logger = logging.getLogger(__name__)

def get_requests_session(retries=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504)):
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(['GET', 'POST'])
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def fetch_historical_prices(commodity, city):
    """
    Fetches historical mandi prices using the data.gov.in API.
    """
    dates = []
    prices = []
    session = get_requests_session()
    try:
        api_key = "579b464db66ec23bdd0000010815c9eb32984e27549690e5e7f660f8"
        resource_id = "9ef84268-d588-465a-a308-a864a43d0070"
        url = f"https://api.data.gov.in/resource/{resource_id}"

        params = {
            "api-key": api_key,
            "format": "json",
            "limit": 30,
            "filters[state]": "Maharashtra",
            "filters[district]": city.upper(),
            "filters[commodity]": commodity.upper()
        }

        response = session.get(url, params=params, timeout=20)
        if response.status_code == 200:
            data = response.json()
            records = data.get('records', [])

            # The API usually returns newest records first. Reverse it so the chart plots oldest -> newest.
            for record in reversed(records):
                date_str = record.get('arrival_date', '')
                modal_price = record.get('modal_price')

                if not modal_price:
                    min_p = float(record.get('min_price', 0) or 0)
                    max_p = float(record.get('max_price', 0) or 0)
                    if min_p and max_p:
                        modal_price = (min_p + max_p) / 2
                else:
                    modal_price = float(modal_price)

                if date_str and modal_price > 0:
                    try:
                        dt = datetime.strptime(date_str, '%d/%m/%Y')
                        date_str = dt.strftime('%b %d')
                    except ValueError:
                        pass

                    dates.append(date_str)
                    prices.append(modal_price)
    except Exception as e:
        logger.error(f"Failed to fetch actual historical data for {commodity} in {city}: {e}", exc_info=True)
    finally:
        session.close()

    return dates, prices


def fetch_latest_mandi_price(commodity, city):
    """
    Fetches the latest available mandi price from the data.gov.in API.
    """
    session = get_requests_session()
    try:
        api_key = "579b464db66ec23bdd0000010815c9eb32984e27549690e5e7f660f8"
        resource_id = "9ef84268-d588-465a-a308-a864a43d0070"
        url = f"https://api.data.gov.in/resource/{resource_id}"
        params = {
            "api-key": api_key,
            "format": "json",
            "limit": 40,
            "filters[state]": "Maharashtra",
            "filters[district]": city.upper(),
            "filters[commodity]": commodity.upper()
        }

        response = session.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        records = data.get("records", [])

        if not records:
            logger.info(f"No exact district records found for {city}, commodity {commodity}. Trying fallback search.")
            params.pop("filters[district]", None)
            params["q"] = city
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            records = data.get("records", [])

            if records:
                fallback_records = [record for record in records if city.upper() in record.get("district", "").upper() or city.upper() in record.get("market", "").upper()]
                if fallback_records:
                    records = fallback_records

        if not records:
            return None, None

        latest_record = None
        latest_date = None
        for record in records:
            date_str = record.get("arrival_date")
            try:
                parsed_date = datetime.strptime(date_str, "%d/%m/%Y")
            except Exception:
                continue
            if latest_date is None or parsed_date > latest_date:
                latest_date = parsed_date
                latest_record = record

        if latest_record is None:
            latest_record = records[0]

        modal_price = latest_record.get("modal_price")
        if not modal_price:
            min_p = float(latest_record.get("min_price", 0) or 0)
            max_p = float(latest_record.get("max_price", 0) or 0)
            if min_p and max_p:
                modal_price = (min_p + max_p) / 2
            elif min_p:
                modal_price = min_p
            elif max_p:
                modal_price = max_p
            else:
                return None, latest_record

        return float(modal_price), latest_record
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch latest mandi price for {commodity} in {city}: {e}", exc_info=True)
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error fetching latest mandi price for {commodity} in {city}: {e}", exc_info=True)
        return None, None
    finally:
        session.close()

@login_required

def farmer_dashboard(request):
   
    product_to_edit = None
    if request.GET.get('edit_id'):
        product_to_edit = get_object_or_404(Product, id=request.GET.get('edit_id'), farmer=request.user)

    if request.method == 'POST':
        # Handle Clear Notifications
        if 'clear_notifications' in request.POST:
            Notification.objects.filter(user=request.user).delete()
            messages.success(request, 'Notifications cleared successfully!')
            return redirect('farmer:farmer_dashboard')
        # Handle Profile Update
        if 'update_profile' in request.POST:
            try:
                user = request.user
                user.first_name = request.POST.get('first_name', user.first_name)
                user.last_name = request.POST.get('last_name', user.last_name)
                user.save()
                
                profile = request.user.userprofile
                profile.phone = request.POST.get('phone', profile.phone)
                profile.address = request.POST.get('address', profile.address)
                profile.city = request.POST.get('city', profile.city)

                if 'image' in request.FILES:
                    profile.image = request.FILES['image']
                profile.save()
                messages.success(request, 'Profile updated successfully!')
            except Exception as e:
                messages.error(request, f'Error updating profile: {e}')
            return redirect('farmer:farmer_dashboard')

        if 'delete_product' in request.POST:
            try:
                product_id = request.POST.get('product_id')
                product = get_object_or_404(Product, id=product_id, farmer=request.user)
                product.delete()
                messages.success(request, 'Product deleted successfully!')
            except Exception as e:
                messages.error(request, f'Error deleting product: {e}')
            return redirect('farmer:farmer_dashboard')

        try:
            profile = request.user.userprofile
            if not profile.address or not profile.phone:
                messages.error(request, 'Please add your Address and Phone Number in your profile before adding a product.')
                return redirect('farmer:farmer_dashboard')
        except Exception:
            messages.error(request, 'Please complete your profile details.')
            return redirect('farmer:farmer_dashboard')

        edit_id = request.POST.get('edit_id')
        if edit_id:
            product_instance = get_object_or_404(Product, id=edit_id, farmer=request.user)
            form = ProductForm(request.POST, request.FILES, instance=product_instance)
        else:
            form = ProductForm(request.POST, request.FILES)

        if form.is_valid():
            product = form.save(commit=False)
            product.farmer = request.user
            product.save()
            messages.success(request, 'Product updated successfully!' if edit_id else 'Product added successfully!')
        else:
            action = "updating" if edit_id else "adding"
            messages.error(request, f'Error {action} product: {form.errors}')
        return redirect('farmer:farmer_dashboard')

    products = Product.objects.filter(farmer=request.user)
    form = ProductForm(instance=product_to_edit) if product_to_edit else ProductForm()
    try:
        user_profile = request.user.userprofile
    except Exception:
        user_profile = None
    
    # Fetch notifications (recent orders)
    notifications = Notification.objects.filter(user=request.user).select_related('sender').order_by('-created_at')[:5]

    # Fetch sent messages/replies
    sent_messages = Notification.objects.filter(sender=request.user).select_related('user').order_by('-created_at')[:10]

    # Fetch reviews
    reviews = ProductReview.objects.filter(product__farmer=request.user).select_related('product', 'user').order_by('-created_at')
    
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

    # Check if profile is complete
    profile_incomplete = False
    if user_profile and (not user_profile.phone or not user_profile.address or not user_profile.city):
        profile_incomplete = True

    return render(request, 'farmer_dashboard.html', {'products': products, 'product_to_edit': product_to_edit, 'form': form, 'user_profile': user_profile, 'notifications': notifications, 'sent_messages': sent_messages, 'reviews': reviews, 'cities': cities, 'profile_incomplete': profile_incomplete})

def get_weather_code_text(weather_code):
    weather_map = {
        0: 'Clear sky',
        1: 'Mainly clear',
        2: 'Partly cloudy',
        3: 'Overcast',
        45: 'Fog',
        48: 'Depositing rime fog',
        51: 'Light drizzle',
        53: 'Moderate drizzle',
        55: 'Dense drizzle',
        56: 'Freezing drizzle',
        57: 'Dense freezing drizzle',
        61: 'Slight rain',
        63: 'Moderate rain',
        65: 'Heavy rain',
        66: 'Freezing rain',
        67: 'Heavy freezing rain',
        71: 'Slight snow',
        73: 'Moderate snow',
        75: 'Heavy snow',
        77: 'Snow grains',
        80: 'Slight rain showers',
        81: 'Moderate rain showers',
        82: 'Violent rain showers',
        85: 'Slight snow showers',
        86: 'Heavy snow showers',
        95: 'Thunderstorm',
        96: 'Thunderstorm with slight hail',
        99: 'Thunderstorm with heavy hail',
    }
    return weather_map.get(weather_code, 'Unknown')


def get_open_meteo_icon_url(weather_code):
    icon_map = {
        0: 'https://openweathermap.org/img/wn/01d@2x.png',
        1: 'https://openweathermap.org/img/wn/02d@2x.png',
        2: 'https://openweathermap.org/img/wn/03d@2x.png',
        3: 'https://openweathermap.org/img/wn/04d@2x.png',
        45: 'https://openweathermap.org/img/wn/50d@2x.png',
        48: 'https://openweathermap.org/img/wn/50d@2x.png',
        51: 'https://openweathermap.org/img/wn/09d@2x.png',
        53: 'https://openweathermap.org/img/wn/09d@2x.png',
        55: 'https://openweathermap.org/img/wn/09d@2x.png',
        56: 'https://openweathermap.org/img/wn/13d@2x.png',
        57: 'https://openweathermap.org/img/wn/13d@2x.png',
        61: 'https://openweathermap.org/img/wn/10d@2x.png',
        63: 'https://openweathermap.org/img/wn/10d@2x.png',
        65: 'https://openweathermap.org/img/wn/10d@2x.png',
        66: 'https://openweathermap.org/img/wn/13d@2x.png',
        67: 'https://openweathermap.org/img/wn/13d@2x.png',
        71: 'https://openweathermap.org/img/wn/13d@2x.png',
        73: 'https://openweathermap.org/img/wn/13d@2x.png',
        75: 'https://openweathermap.org/img/wn/13d@2x.png',
        77: 'https://openweathermap.org/img/wn/13d@2x.png',
        80: 'https://openweathermap.org/img/wn/09d@2x.png',
        81: 'https://openweathermap.org/img/wn/09d@2x.png',
        82: 'https://openweathermap.org/img/wn/09d@2x.png',
        85: 'https://openweathermap.org/img/wn/13d@2x.png',
        86: 'https://openweathermap.org/img/wn/13d@2x.png',
        95: 'https://openweathermap.org/img/wn/11d@2x.png',
        96: 'https://openweathermap.org/img/wn/11d@2x.png',
        99: 'https://openweathermap.org/img/wn/11d@2x.png',
    }
    return icon_map.get(weather_code)

@login_required
def weather_info(request):
    weather_data = None
    searched_city = None
    forecast_data = None
    error_message = None

    if 'term' in request.GET:
        term = request.GET.get('term')
        try:
            geo_url = 'https://geocoding-api.open-meteo.com/v1/search'
            params = {'name': term, 'count': 5, 'language': 'en', 'format': 'json'}
            response = requests.get(geo_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            suggestions = []
            for item in data.get('results', []):
                name = item.get('name')
                country = item.get('country')
                admin1 = item.get('admin1')
                admin2 = item.get('admin2')
                label = name
                if admin2 and admin2 != name:
                    label += f", {admin2}"
                if admin1:
                    label += f", {admin1}"
                label += f", {country}"
                suggestions.append({'label': label, 'value': name, 'lat': item.get('latitude'), 'lon': item.get('longitude')})
            return JsonResponse(suggestions, safe=False)
        except requests.exceptions.RequestException as e:
            logger.error(f"Open-Meteo autocomplete failed: {e}")
            return JsonResponse([], safe=False)

    if request.method == 'POST':
        city = request.POST.get('city', '').strip()
        lat = request.POST.get('lat')
        lon = request.POST.get('lon')
        location = None

        logger.info(f"Weather form submitted: city='{city}', lat='{lat}', lon='{lon}'")

        try:
            if lat and lon:
                location = {'name': city or 'Current Location', 'country': '', 'latitude': float(lat), 'longitude': float(lon)}
                if city:
                    searched_city = city
                else:
                    searched_city = f"Current Location ({lat}, {lon})"
            elif city:
                # Simple typo corrections
                corrections = {
                    'aurangbad': 'Aurangabad',
                    'mumbai': 'Mumbai',
                    'pune': 'Pune',
                    'delhi': 'Delhi',
                    'bangalore': 'Bengaluru',
                    # Add more as needed
                }
                corrected_city = corrections.get(city.lower(), city)
                
                geo_url = 'https://geocoding-api.open-meteo.com/v1/search'
                params = {'name': corrected_city, 'count': 1, 'language': 'en', 'format': 'json'}
                response = requests.get(geo_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                results = data.get('results')
                if results:
                    location = results[0]
                    admin = location.get('admin1') or location.get('admin2') or location.get('admin3') or ''
                    if admin:
                        searched_city = f"{location.get('name')}, {admin}, {location.get('country', '')}"
                    else:
                        searched_city = f"{location.get('name')}, {location.get('country', '')}"
                else:
                    error_message = f"Could not find location for '{city}'. Did you mean '{corrected_city}'?" if corrected_city != city else f"Could not find location for '{city}'."

            if location and not error_message:
                forecast_url = 'https://api.open-meteo.com/v1/forecast'
                params = {
                    'latitude': location['latitude'],
                    'longitude': location['longitude'],
                    'current_weather': 'true',
                    'daily': 'temperature_2m_max,temperature_2m_min,weathercode',
                    'timezone': 'auto'
                }
                response = requests.get(forecast_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                current = data.get('current_weather')
                daily = data.get('daily', {})

                if current:
                    weather_data = {
                        'Temperature': {'Metric': {'Value': current.get('temperature'), 'Unit': 'C'}},
                        'WeatherText': get_weather_code_text(current.get('weathercode')),
                        'Wind': {'Speed': {'Metric': {'Value': current.get('windspeed'), 'Unit': 'km/h'}}},
                        'RelativeHumidity': None,
                        'UVIndexText': None,
                        'Visibility': None,
                        'IconUrl': get_open_meteo_icon_url(current.get('weathercode'))
                    }

                if daily and daily.get('time'):
                    forecast_data = {'DailyForecasts': []}
                    for date, max_temp, min_temp, weather_code in zip(
                        daily.get('time', []),
                        daily.get('temperature_2m_max', []),
                        daily.get('temperature_2m_min', []),
                        daily.get('weathercode', [])
                    ):
                        forecast_data['DailyForecasts'].append({
                            'Date': date,
                            'Temperature': {
                                'Maximum': {'Value': max_temp},
                                'Minimum': {'Value': min_temp}
                            },
                            'Day': {
                                'IconUrl': get_open_meteo_icon_url(weather_code)
                            }
                        })
            elif not error_message:
                error_message = "Please enter a city name or choose current location."

        except requests.exceptions.RequestException as e:
            error_message = f"Could not connect to the weather service. Please check your internet connection. ({str(e)[:100]})"
            logger.error(f"Open-Meteo connection error: {e}")
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)[:100]}"
            logger.error(f"Unexpected error in weather_info: {e}", exc_info=True)

    return render(request, 'weather.html', {
        'weather_data': weather_data,
        'searched_city': searched_city,
        'forecast_data': forecast_data,
        'error_message': error_message
    })

@login_required
def market_prices(request):
    # Comprehensive list of districts/major cities in Maharashtra with Marathi names for searchability
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
    
    # Standard commodities list for matching
    standard_commodities = [
        "Wheat", "Rice", "Cotton", "Soybean", "Onion", "Tomato", "Potato", 
        "Maize", "Sugarcane", "Turmeric", "Gram", "Bajra", "Jowar", "Groundnut",
        "Sunflower", "Moong", "Urad", "Ginger", "Garlic", "Chilli"
    ]

    # Hinglish/Marathi to English mapping
    hinglish_map = {
        "tamatar": "Tomato", "pyaz": "Onion", "kanda": "Onion", "aaloo": "Potato", "batata": "Potato",
        "ganna": "Sugarcane", "gehu": "Wheat", "chawal": "Rice", "bhaat": "Rice", "tandul": "Rice",
        "kapas": "Cotton", "kapus": "Cotton", "haldi": "Turmeric", "chana": "Gram", "harbara": "Gram",
        "makka": "Maize", "maka": "Maize", "mung": "Moong", "udid": "Urad", 
        "shengga": "Groundnut", "mungfali": "Groundnut", "shengdana": "Groundnut",
        "bhuimug": "Groundnut", "surajmukhi": "Sunflower", "suryaphool": "Sunflower",
        "bajri": "Bajra", "jwari": "Jowar", "soya": "Soybean", "soyabean": "Soybean",
        "adrak": "Ginger", "ale": "Ginger", "lahsun": "Garlic", "lasun": "Garlic",
        "mirchi": "Chilli", "mirch": "Chilli",
        "कांदा": "Onion", "बटाटा": "Potato", "टोमॅटो": "Tomato", "गहू": "Wheat", "तांदूळ": "Rice", "भात": "Rice",
        "कापूस": "Cotton", "सोयाबीन": "Soybean", "मका": "Maize", "ऊस": "Sugarcane", "हळद": "Turmeric",
        "हरभरा": "Gram", "चणा": "Gram", "बाजरी": "Bajra", "ज्वारी": "Jowar", "भुईमूग": "Groundnut", 
        "शेंगदाणा": "Groundnut", "सूर्यफूल": "Sunflower", "मूग": "Moong", "उडीद": "Urad", "आले": "Ginger",
        "अद्रक": "Ginger", "लसूण": "Garlic", "मिरची": "Chilli"
    }

    response_text = None
    selected_city = None
    commodity = None
    min_price = None
    max_price = None
    avg_price = None
    historical_dates_json = None
    historical_prices_json = None
    searched = False

    if request.method == 'POST':
        searched = True
        # Handle translation requests first
        if request.POST.get('action') == 'translate':
            text_to_translate = request.POST.get('text')
            target_lang = request.POST.get('target_lang', 'hi') # Default to Hindi
            if not text_to_translate:
                 return JsonResponse({'status': 'error', 'message': 'No text provided'})
            
            try:
                # Using Google Translate API (unofficial, might break)
                url = "https://translate.googleapis.com/translate_a/single"
                params = {
                    "client": "gtx",
                    "sl": "en", # Source language is English
                    "tl": target_lang,
                    "dt": "t",
                    "q": text_to_translate
                }
                resp = requests.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    translated_text = "".join([item[0] for item in data[0] if item[0]])
                    return JsonResponse({'status': 'success', 'translated_text': translated_text})
                return JsonResponse({'status': 'error', 'message': 'Translation API failed'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)})

        selected_city = request.POST.get('city')
        raw_commodity = request.POST.get('commodity')
        
        logger.info(f"Market prices form submitted: city='{selected_city}', commodity='{raw_commodity}'")
        
        if selected_city and raw_commodity:
            # Clean city name (remove Marathi part for the prompt if needed)
            city_name_clean = selected_city.split('(')[0].strip()
            district_aliases = {
                'Chhatrapati Sambhajinagar': 'Aurangabad',
                'Dharashiv': 'Osmanabad'
            }
            city_name_clean = district_aliases.get(city_name_clean, city_name_clean)
            
            # Normalize and correct commodity
            commodity_lower = raw_commodity.lower().strip()
            
            if commodity_lower in hinglish_map:
                commodity = hinglish_map[commodity_lower]
            else:
                # Fuzzy matching for spelling mistakes
                matches = difflib.get_close_matches(raw_commodity, standard_commodities, n=1, cutoff=0.6)
                if matches:
                    commodity = matches[0]
                else:
                    commodity = raw_commodity.title()

            logger.info(f"Processing: commodity='{commodity}', city_name_clean='{city_name_clean}'")

            # First try the official data.gov.in mandi API for latest price data
            latest_price, latest_record = fetch_latest_mandi_price(commodity, city_name_clean)
            if latest_price is not None:
                min_price = max_price = avg_price = round(latest_price, 2)
                response_text = f"Latest mandi price for {commodity} in {city_name_clean} is ₹{avg_price} per quintal."

                actual_dates, actual_prices = fetch_historical_prices(commodity, city_name_clean)
                if actual_dates and actual_prices and len(actual_dates) > 5:
                    historical_dates = actual_dates
                    historical_prices = actual_prices
                else:
                    historical_dates = []
                    historical_prices = []
                    base_price = avg_price
                    today = timezone.now().date()
                    for i in range(30, -1, -1):
                        date = today - timedelta(days=i)
                        historical_dates.append(date.strftime('%b %d'))
                        fluctuation = base_price * random.uniform(-0.02, 0.02)
                        base_price = round(base_price + fluctuation, 2)
                        historical_prices.append(base_price)
                    historical_prices[-1] = avg_price

                historical_dates_json = json.dumps(historical_dates)
                historical_prices_json = json.dumps(historical_prices)
            else:
                # Fallback to web search if official API did not return live price data
                try:
                    try:
                        from ddgs import DDGS
                    except ImportError:
                        DDGS = None
                        logger.warning('DDGS library is not installed. Search fallback will be disabled.')

                    if DDGS is None:
                        response_text = (
                            f"No live mandi API results found for {commodity} in {city_name_clean}. "
                            "Fallback web search is unavailable on this server."
                        )
                    else:
                        search_query = f"{commodity} mandi price in {city_name_clean} per quintal"
                        logger.info(f"Searching: {search_query}")
                        with DDGS() as ddgs:
                            search_results = list(ddgs.text(search_query, max_results=5))

                        logger.info(f"Search returned {len(search_results)} results")
                        snippets = " ".join([res.get('body', '') for res in search_results if res.get('body')])

                        if snippets:
                            snippets = re.sub(r'[^\w\s\.,₹\-$%/:;()]+', ' ', snippets)
                            snippets = re.sub(r'\s+', ' ', snippets).strip()

                            price_pattern = r'(?:rs\.?|₹|inr|rupees?)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rs\.?|₹|inr|rupees?)'
                            matches = re.findall(price_pattern, snippets, re.IGNORECASE)

                            prices = []
                            for match in matches:
                                val = match[0] if match[0] else match[1]
                                val = val.replace(',', '')
                                try:
                                    p = float(val)
                                    if 100 <= p <= 500000:
                                        prices.append(p)
                                except ValueError:
                                    pass

                            if prices:
                                min_price = min(prices)
                                max_price = max(prices)
                                avg_price = round(sum(prices) / len(prices), 2)

                            if avg_price:
                                actual_dates, actual_prices = fetch_historical_prices(commodity, city_name_clean)
                                if actual_dates and actual_prices and len(actual_dates) > 5:
                                    historical_dates = actual_dates
                                    historical_prices = actual_prices
                                else:
                                    historical_dates = []
                                    historical_prices = []
                                    base_price = avg_price
                                    today = timezone.now().date()
                                    for i in range(30, -1, -1):
                                        date = today - timedelta(days=i)
                                        historical_dates.append(date.strftime('%b %d'))
                                        fluctuation = base_price * random.uniform(-0.02, 0.02)
                                        base_price = round(base_price + fluctuation, 2)
                                        historical_prices.append(base_price)
                                    historical_prices[-1] = avg_price
                                historical_dates_json = json.dumps(historical_dates)
                                historical_prices_json = json.dumps(historical_prices)

                            sentences = re.split(r'(?<=[.!?]) +', snippets)
                            relevant_sentences = []
                            keywords = ['rs', '₹', 'price', 'quintal', 'rate', 'rupee', 'kg', 'mandi', 'market']

                            for sentence in sentences:
                                if any(keyword in sentence.lower() for keyword in keywords):
                                    if sentence not in relevant_sentences:
                                        relevant_sentences.append(sentence)

                            if relevant_sentences:
                                response_text = " ".join(relevant_sentences[:5])
                            else:
                                response_text = snippets
                        else:
                            response_text = f"No relevant web search results found for {commodity} in {city_name_clean}, Maharashtra."
                except Exception as e:
                    logger.error(f"Error in market_prices web search for {commodity} in {selected_city}: {e}", exc_info=True)
                    response_text = f"An error occurred while fetching market prices: {str(e)[:200]}"

                if not avg_price and not response_text:
                    response_text = (
                        f"No market price data was available for {commodity} in {city_name_clean}. "
                        "Try a different commodity or city."
                    )

    return render(request, 'market_prices.html', {
        'cities': cities,
        'response_text': response_text,
        'selected_city': selected_city,
        'commodity': commodity,
        'min_price': min_price,
        'max_price': max_price,
        'avg_price': avg_price,
        'historical_dates': historical_dates_json,
        'historical_prices': historical_prices_json,
        'searched': searched,
    })

@login_required
def sales_history(request):
    # Base queryset for orders containing products from the current farmer
    orders = Order.objects.filter(items__product__farmer=request.user).distinct()

    # Apply filters from GET parameters
    status_filter = request.GET.get('status')
    if status_filter:
        orders = orders.filter(status=status_filter)

    start_date = request.GET.get('start_date')
    if start_date:
        orders = orders.filter(created_at__date__gte=start_date)

    end_date = request.GET.get('end_date')
    if end_date:
        orders = orders.filter(created_at__date__lte=end_date)

    # Annotate with item count, prefetch related data for efficiency, and order.
    # This avoids the N+1 query problem in the template by fetching related
    # user, userprofile, items, and product data in a minimal number of queries.
    orders = orders.select_related('user', 'user__userprofile').prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.select_related('product'))
    ).annotate(
        item_count=Count('items')
    ).order_by('-created_at')

    paginator = Paginator(orders, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'orders': page_obj,
        'status_filter': status_filter,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'sales_history.html', context)

@login_required
def manage_order(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'accept':
            order.status = 'Processing'
            order.save()
            
            msg = f'Your order #{order.id} has been accepted and is now being processed.'
            Notification.objects.create(
                user=order.user,
                order=order,
                message=msg
            )
            
            if order.user.email:
                try:
                    send_mail(
                        f'Order #{order.id} Accepted - Krishi Connect',
                        msg,
                        settings.EMAIL_HOST_USER,
                        [order.user.email],
                        fail_silently=True
                    )
                except Exception:
                    pass
                    
            messages.success(request, f'Order #{order.id} accepted.')
            
        elif action == 'ship':
            order.status = 'Shipped'
            # Generate OTP
            otp = str(random.randint(100000, 999999))
            order.delivery_otp = otp
            order.save()
            
            # Create Notification for Consumer
            notification_message = f'Your order #{order.id} has been shipped. Please provide this OTP to the farmer upon delivery: {otp}'
            Notification.objects.create(
                user=order.user,
                order=order,
                message=notification_message
            )

            # Send OTP to Consumer
            if order.user.email:
                try:
                    send_mail(
                        f'Order #{order.id} Shipped - Delivery OTP',
                        notification_message,
                        settings.EMAIL_HOST_USER,
                        [order.user.email],
                        fail_silently=True
                    )
                except Exception:
                    pass
            messages.success(request, f'Order #{order.id} shipped. OTP sent to consumer.')
            
        elif action == 'deliver':
            entered_otp = request.POST.get('otp')
            if entered_otp == order.delivery_otp:
                order.status = 'Delivered'
                order.save()
                Notification.objects.create(
                    user=order.user,
                    order=order,
                    message=f'Your order #{order.id} has been successfully delivered. Thank you for shopping with us!'
                )
                messages.success(request, f'Order #{order.id} marked as Delivered.')
            else:
                messages.error(request, 'Invalid OTP. Delivery verification failed.')
        
        elif action == 'reject':
            order.status = 'Cancelled'
            order.save()
            
            refund_note = ""
            if order.payment_method == 'Online' and order.transaction_id:
                try:
                    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                    client.payment.refund(order.transaction_id, {
                        "amount": int(round(order.total_amount * 100))
                    })
                    order.refund_status = 'Completed'
                    refund_note = " A refund has been processed for your online payment."
                except Exception as e:
                    print(f"Razorpay Refund Error: {e}")
                    order.refund_status = 'Failed'
                    refund_note = f" Refund failed: {str(e)}"
            elif order.payment_method == 'Online':
                 order.refund_status = 'Initiated'
                 refund_note = " A refund has been initiated for your online payment."
            
            order.save()
            
            # Create Notification
            notification_message = f'We regret to inform you that your order #{order.id} has been rejected by the farmer.{refund_note}'
            Notification.objects.create(
                user=order.user,
                order=order,
                message=notification_message
            )
            if order.user.email:
                try:
                    send_mail(
                        f'Order #{order.id} Rejected - Krishi Connect',
                        f'{notification_message}\n\nWe apologize for the inconvenience.\n\nRegards,\nKrishi Connect Team',
                        settings.EMAIL_HOST_USER,
                        [order.user.email],
                        fail_silently=True
                    )
                except Exception:
                    pass
            messages.warning(request, f'Order #{order.id} rejected.')
            
        elif action == 'mark_refunded':
            if order.refund_status == 'Initiated':
                order.refund_status = 'Completed'
                order.save()
                Notification.objects.create(
                    user=order.user,
                    order=order,
                    message=f'Refund for Order #{order.id} has been completed.'
                )
                messages.success(request, f'Order #{order.id} marked as Refunded.')
    
    return redirect(request.META.get('HTTP_REFERER', 'farmer:farmer_dashboard'))

@login_required
def download_sales_report(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sales_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Order ID', 'Date', 'Product', 'Consumer', 'Quantity (kg)', 'Price (INR)', 'Total (INR)', 'Status'])

    # Start with the base queryset
    sales_items = OrderItem.objects.filter(product__farmer=request.user).select_related('order', 'product', 'order__user')

    # Apply filters from GET parameters
    status_filter = request.GET.get('status')
    if status_filter:
        sales_items = sales_items.filter(order__status=status_filter)

    start_date = request.GET.get('start_date')
    if start_date:
        sales_items = sales_items.filter(order__created_at__date__gte=start_date)

    end_date = request.GET.get('end_date')
    if end_date:
        sales_items = sales_items.filter(order__created_at__date__lte=end_date)
    
    sales_items = sales_items.order_by('-order__created_at')

    for item in sales_items:
        consumer_name = item.order.user.get_full_name() or item.order.user.username
        total = item.price * item.quantity
        writer.writerow([
            item.order.id,
            item.order.created_at.strftime('%Y-%m-%d %H:%M'),
            item.product.name,
            consumer_name,
            item.quantity,
            item.price,
            total,
            item.order.status
        ])

    return response

@login_required
def plant_disease_prediction(request):
    result = {}
    uploaded_image_data = None
    language = 'en'

    if request.method == 'POST':
        if request.POST.get('action') == 'translate':
            text_to_translate = request.POST.get('text')
            target_lang = request.POST.get('target_lang', 'hi')
            if not text_to_translate:
                 return JsonResponse({'status': 'error', 'message': 'No text provided'})
            
            try:
                url = "https://translate.googleapis.com/translate_a/single"
                params = {
                    "client": "gtx",
                    "sl": "en",
                    "tl": target_lang,
                    "dt": "t",
                    "q": text_to_translate
                }
                resp = requests.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    # data[0] contains the translations. Each element is [translated, original, ...]
                    translated_text = "".join([item[0] for item in data[0] if item[0]])
                    return JsonResponse({'status': 'success', 'translated_text': translated_text})
                return JsonResponse({'status': 'error', 'message': 'Translation API failed'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)})

        image = request.FILES.get('image')
        # Use the API Key from config
        api_key = API_KEY.strip()
        language = request.POST.get('language', 'en')

        headers = {
            "Api-Key": api_key,
            "Content-Type": "application/json"
        }
        try:
            if image:
                image_bytes = image.read()
                # Convert image to base64 for API and for re-displaying in template
                image_data = base64.b64encode(image_bytes).decode('utf-8')
                uploaded_image_data = f"data:{image.content_type};base64,{image_data}"

                payload = {
                    "images": [image_data],
                    "similar_images": True
                }
                
                # Call Identification API
                ident_url = "https://plant.id/api/v3/identification"
                ident_params = {
                    "details": "common_names,taxonomy,description,url",
                    "language": "en"
                }
                ident_response = requests.post(ident_url, json=payload, headers=headers, params=ident_params)

                health_url = "https://plant.id/api/v3/health_assessment"
                health_params = {
                    "details": "local_name,description,url,treatment,cause",
                    "language": language
                }
                health_response = requests.post(health_url, json=payload, headers=headers, params=health_params)

                usage_url = "https://plant.id/api/v3/usage"
                usage_response = requests.get(usage_url, headers=headers)
                usage_stats = usage_response.json() if usage_response.status_code == 200 else None
                if usage_stats:
                    print(f"Model Usage: {usage_stats}")

                if ident_response.status_code == 429 or health_response.status_code == 429:
                    result = {
                        "status": "error",
                        "message": "Daily Model usage limit exceeded. Please try again later."
                    }
                elif ident_response.status_code == 201 and health_response.status_code == 201:
                    # Create history entry
                    history_entry = PredictionHistory(farmer=request.user)
                    history_entry.image.save(image.name, ContentFile(image_bytes), save=False)
                    
                    # Process Identification
                    ident_data = ident_response.json()
                    classification = ident_data.get("result", {}).get("classification", {})
                    if classification.get("suggestions"):
                        top_plant = classification["suggestions"][0]
                        plant_details = top_plant.get("details", {})
                        
                        plant_description = plant_details.get("description")
                        if isinstance(plant_description, dict):
                            plant_description = plant_description.get("value")
                        
                        # Determine display name (prefer first common name if available)
                        common_names = [n for n in (plant_details.get("common_names") or []) if n]
                        plant_display_name = common_names[0] if common_names else top_plant.get("name")

                        # Save to model instance
                        history_entry.plant_name = plant_display_name
                        history_entry.plant_probability = top_plant.get('probability', 0) * 100
                        history_entry.plant_common_names = ", ".join(str(name) for name in common_names)
                        history_entry.plant_description = plant_description
                        history_entry.plant_url = plant_details.get("url")

                        result["plant"] = {
                            "name": plant_display_name,
                            "common_names": common_names,
                            "description": plant_description,
                            "url": plant_details.get("url")
                        }

                    # Process Health
                    health_data = health_response.json()
                    health_result = health_data.get("result", {})
                    is_healthy = health_result.get("is_healthy", {})
                    history_entry.is_healthy = is_healthy.get('binary')
                    history_entry.health_probability = is_healthy.get('probability', 0) * 100

                    result["health"] = {
                        "is_healthy": history_entry.is_healthy,
                        "probability": f"{history_entry.health_probability:.2f}%"
                    }

                    if not result["health"]["is_healthy"]:
                        diseases = health_result.get("disease", {}).get("suggestions", [])
                        if diseases:
                            top_disease = diseases[0]
                            disease_details = top_disease.get("details", {})
                            disease_desc = disease_details.get("description")
                            if isinstance(disease_desc, dict):
                                disease_desc = disease_desc.get("value")
                            
                            # Determine disease display name (prefer local_name)
                            disease_local_name = disease_details.get("local_name")
                            disease_display_name = disease_local_name if disease_local_name and disease_local_name.strip() else top_disease.get("name")

                            history_entry.disease_name = disease_display_name
                            history_entry.disease_probability = top_disease.get('probability', 0) * 100
                            history_entry.disease_description = disease_desc
                            history_entry.disease_treatment = disease_details.get("treatment", {})

                            result["disease"] = {
                                "name": history_entry.disease_name,
                                "probability": f"{history_entry.disease_probability:.2f}%",
                                "description": disease_desc,
                                "treatment": disease_details.get("treatment", {})}
                    result["status"] = "success"
                    if usage_stats:
                        result["usage"] = usage_stats
                else:
                    # General error handling
                    result = {
                        "status": "error",
                        "message": f"API Error: Identification({ident_response.status_code}) / Health({health_response.status_code})"
                    }
            else:
                result = {
                    "status": "error",
                    "message": "Please upload an image for analysis."
                }
        except requests.exceptions.RequestException as e:
            result = {
                "status": "error",
                "message": f"Connection failed: {str(e)}"
            }

    return render(request, 'disease_prediction.html', {'result': result, 'uploaded_image': uploaded_image_data, 'selected_language': language})

@login_required
def prediction_history(request):
    history = PredictionHistory.objects.filter(farmer=request.user)
    history_list = PredictionHistory.objects.filter(farmer=request.user)
    paginator = Paginator(history_list, 10)  # Show 10 items per page
    page_number = request.GET.get('page')
    history = paginator.get_page(page_number)
    return render(request, 'prediction_history.html', {'history': history})

@login_required
def followers_list(request):
    if not hasattr(request.user, 'userprofile') or request.user.userprofile.user_type != 'farmer':
        messages.error(request, "You are not authorized to view this page.")
        return redirect('home')

    farmer_profile = request.user.userprofile
    followers = farmer_profile.followers.all().select_related('userprofile')

    if request.method == 'POST':
        message_text = request.POST.get('message')
        if message_text:
            # Create notifications in a batch
            notifications_to_create = [
                Notification(
                    user=follower,
                    message=f"A message from farmer {request.user.get_full_name() or request.user.username}: {message_text}"
                )
                for follower in followers
            ]
            if notifications_to_create:
                Notification.objects.bulk_create(notifications_to_create)
                messages.success(request, f'Broadcast message sent to {len(notifications_to_create)} followers!')
            else:
                messages.warning(request, 'You have no followers to send a message to.')
        else:
            messages.error(request, 'Message cannot be empty.')
        return redirect('farmer:followers_list')

    paginator = Paginator(followers, 10)  # 10 followers per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'farmer_followers.html', {'followers_page': page_obj})

def reply_to_consumer(request):
    if request.method == 'POST':
        try:
            consumer_id = request.POST.get('consumer_id')
            reply_message = request.POST.get('message')
            original_notification_id = request.POST.get('notification_id')

            if not consumer_id or not reply_message:
                messages.error(request, "Missing information to send reply.")
                return redirect(request.META.get('HTTP_REFERER', 'farmer:farmer_dashboard'))

            consumer = get_object_or_404(User, id=consumer_id)
            
            # Prevent the farmer from replying to themselves if data gets corrupted
            if consumer == request.user:
                messages.error(request, "You cannot send a reply to yourself.")
                return redirect(request.META.get('HTTP_REFERER', 'farmer:farmer_dashboard'))
            
            Notification.objects.create(
                user=consumer,
                sender=request.user,
                message=f"Reply from {request.user.get_full_name() or request.user.username}: {reply_message}"
            )

            # Mark the original notification as read
            try:
                original_notification = Notification.objects.get(id=original_notification_id, user=request.user)
                # Delete the original inquiry so it disappears from the farmer's notification list
                original_notification.delete()
            except Notification.DoesNotExist:
                pass # Not critical if it fails

            messages.success(request, f"Reply sent to {consumer.get_full_name() or consumer.username}.")
        except Exception as e:
            messages.error(request, f"Error sending reply: {e}")
        
        return redirect(request.META.get('HTTP_REFERER', 'farmer:farmer_dashboard'))
    
    return redirect('farmer:farmer_dashboard')

@login_required
def govt_schemes(request):
    if request.method == 'POST':
        if request.POST.get('action') == 'translate':
            text_to_translate = request.POST.get('text')
            target_lang = request.POST.get('target_lang', 'hi') 
            if not text_to_translate:
                 return JsonResponse({'status': 'error', 'message': 'No text provided'})
            try:
                url = "https://translate.googleapis.com/translate_a/single"
                params = {
                    "client": "gtx",
                    "sl": "en",
                    "tl": target_lang,
                    "dt": "t",
                    "q": text_to_translate
                }
                resp = requests.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    # data[0] contains the translations. Each element is [translated, original, ...]
                    translated_text = "".join([item[0] for item in data[0] if item[0]])
                    return JsonResponse({'status': 'success', 'translated_text': translated_text})
                return JsonResponse({'status': 'error', 'message': 'Translation API failed'})
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)})

    schemes = GovernmentScheme.objects.all().order_by('-added_on')
    return render(request, 'govt_schemes.html', {'schemes': schemes})
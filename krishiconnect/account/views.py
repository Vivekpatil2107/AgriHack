
from django.http import HttpResponse ,HttpRequest
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from .models import UserProfile
import random
from django.core.mail import send_mail
from django.conf import settings

# Create your views here.

def login(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password']

        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
        except User.DoesNotExist:
            user = None

        if user is not None:
            auth_login(request, user)
            try:
                if user.userprofile.user_type == 'farmer':
                    return redirect('farmer:farmer_dashboard')
                elif user.userprofile.user_type == 'consumer':
                    return redirect('consumer:consumer_dashboard')
            except UserProfile.DoesNotExist:
                pass
            return redirect('home')
        else:
            messages.info(request, 'Invalid Username or Password')
            return redirect('login')
    return render(request, 'login.html')

# Signup view with OTP verification
def signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        confirm_password = request.POST['confirm_password']
        role = request.POST.get('role')

        if role not in dict(UserProfile.USER_TYPE_CHOICES):
            messages.info(request, 'Invalid role selected')
            return redirect('signup')

        if password == confirm_password:
            if User.objects.filter(username=username).exists():
                messages.info(request, 'Username Taken')
                return redirect('signup')
            elif User.objects.filter(email=email).exists():
                messages.info(request, 'Email Taken')
                return redirect('signup')
            else:
                # Store user details in session instead of creating user immediately
                request.session['signup_data'] = {
                    'username': username,
                    'email': email,
                    'password': password,
                    'role': role
                }

            
                otp = random.randint(100000, 999999)
                subject = 'Account Verification OTP'
                message = f'Your OTP for account verification is {otp} from KrishiConnect, the farmers empowerment platform.'
                email_from = settings.EMAIL_HOST_USER
                recipient_list = [email]
                
                try:
                    send_mail(subject, message, email_from, recipient_list)
                except Exception as e:
                    messages.info(request, 'Error sending email. Please try again.')
                    return redirect('signup')

                request.session['otp'] = otp
                return redirect('verify_otp')
        else:
            messages.info(request, 'Password not matching')
            return redirect('signup')
    return render(request, 'signup.html')

def verify_otp(request):
    if request.method == 'POST':
        otp = request.POST.get('otp')
        session_otp = request.session.get('otp')
        signup_data = request.session.get('signup_data')

        if session_otp and str(otp) == str(session_otp) and signup_data:
            try:
                # verified
                user = User.objects.create_user(
                    username=signup_data['username'],
                    password=signup_data['password'],
                    email=signup_data['email']
                )
                user.is_active = True
                user.save()
                UserProfile.objects.create(user=user, user_type=signup_data['role'])

                del request.session['otp']
                del request.session['signup_data']
                return redirect('login')
            except Exception as e:
                messages.info(request, 'Error creating user. Please signup again.')
                return redirect('signup')
        elif not signup_data:
            messages.info(request, 'Session expired. Please signup again.')
            return redirect('signup')
        else:
            messages.info(request, 'Invalid OTP')
            return redirect('verify_otp')
    return render(request, 'verify_otp.html')

def logout(request):
    auth_logout(request)
    return redirect('home')

def forgot_password(request):
    if request.method == 'POST':
        email = request.POST['email']
        try:
            user = User.objects.get(email=email)
            
            
            otp = random.randint(100000, 999999)
            subject = 'Password Reset OTP'
            message = f'Your OTP for password reset is {otp} from KrishiConnect,the farmers empowerment platform.'
            email_from = settings.EMAIL_HOST_USER
            recipient_list = [email]
            
            try:
                send_mail(subject, message, email_from, recipient_list)
            except Exception as e:
                messages.info(request, 'Error sending email. Please try again.')
                return redirect('forgot_password')

            request.session['otp'] = otp
            request.session['user_id'] = user.id
            return redirect('verify_forgot_password_otp')
        except User.DoesNotExist:
            messages.info(request, 'Email not found')
            return redirect('forgot_password')
    return render(request, 'forgot_password.html')

# Verify OTP 
def verify_forgot_password_otp(request):
    if request.method == 'POST':
        otp = request.POST.get('otp')
        session_otp = request.session.get('otp')
        
        if session_otp and str(otp) == str(session_otp):
            request.session['reset_verified'] = True
            return redirect('reset_password')
        else:
            messages.info(request, 'Invalid OTP')
            return redirect('verify_forgot_password_otp')
    return render(request, 'verify_otp.html')

# Resending OTP
def resend_otp(request):
    if 'signup_data' in request.session:
        email = request.session['signup_data']['email']
        redirect_url = 'verify_otp'
    elif 'user_id' in request.session:
        try:
            user = User.objects.get(id=request.session['user_id'])
            email = user.email
            redirect_url = 'verify_forgot_password_otp'
        except User.DoesNotExist:
            messages.info(request, 'User not found.')
            return redirect('login')
    else:
        messages.info(request, 'Session expired. Please start over.')
        return redirect('login')

    otp = random.randint(100000, 999999)
    subject = 'Resend OTP - Krishi Connect'
    message = f'Your new OTP is {otp} from krishiconnect, the farmers empowerment platform.'
    email_from = settings.EMAIL_HOST_USER
    recipient_list = [email]

    try:
        send_mail(subject, message, email_from, recipient_list)
        request.session['otp'] = otp
        messages.info(request, f'OTP resent successfully to {email}.')
    except Exception as e:
        messages.info(request, 'Error sending email. Please try again.')
    
    return redirect(redirect_url)

def reset_password(request):
    if not request.session.get('reset_verified'):
        return redirect('login')
        
    if request.method == 'POST':
        password = request.POST['password']
        confirm_password = request.POST['confirm_password']
        user_id = request.session.get('user_id')
        
        if password == confirm_password:
            try:
                user = User.objects.get(id=user_id)
                user.set_password(password)
                user.save()
                
                # Cleanup session
                if 'otp' in request.session: del request.session['otp']
                if 'user_id' in request.session: del request.session['user_id']
                if 'reset_verified' in request.session: del request.session['reset_verified']
                
                messages.info(request, 'Password reset successful. Please login.')
                return redirect('login')
            except User.DoesNotExist:
                messages.info(request, 'User error.')
                return redirect('login')
        else:
            messages.info(request, 'Passwords do not match')
            return redirect('reset_password')
            
    return render(request, 'reset_password.html')

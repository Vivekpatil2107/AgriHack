import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

# Import our custom ML chatbot logic
# from .chatbot_logic import get_response, get_all_patterns

def home(request):
    """Renders the home page."""
    all_patterns = []  # get_all_patterns()
    return render(request, 'index.html', {'all_patterns': json.dumps(all_patterns)})

@csrf_exempt
def chat_message(request):
    """API endpoint to handle messages."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            user_message = data.get('message')

            if not user_message:
                return JsonResponse({'error': 'Message is empty'}, status=400)

            # Predict the response using our local Naive Bayes model
            bot_response = "Chatbot temporarily unavailable"  # get_response(user_message)

            return JsonResponse({'response': bot_response})

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)

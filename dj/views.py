from django.http import JsonResponse
from .models import User
import traceback
from django.views.decorators.csrf import csrf_exempt
import json
def api_users(request):
    try:
        users = list(User.objects.values('id', 'email', 'role'))
        return JsonResponse({'users': users})
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


@csrf_exempt
def api_login(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            password = data.get('password')

            user = User.objects.filter(email=email).first()
            if user and user.password == password:
                return JsonResponse({'success': True})

            return JsonResponse({'success': False, 'error': 'Nieprawidłowy e-mail lub hasło'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)

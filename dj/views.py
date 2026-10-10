from django.http import JsonResponse
from .models import User
import traceback

def api_users(request):
    try:
        users = list(User.objects.values('id', 'email', 'role'))
        return JsonResponse({'users': users})
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)
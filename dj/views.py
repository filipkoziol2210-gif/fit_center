from django.http import JsonResponse
from .models import User

def api_users(request):
    users = list(User.objects.values('id', 'email', 'role'))
    return JsonResponse({'users': users})
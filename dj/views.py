from django.http import JsonResponse
from django.db import connection
from django.views.decorators.csrf import csrf_exempt
import json
import traceback

def api_users(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, email, role FROM nazwa_tabeli_uzytkownikow")
            columns = [col[0] for col in cursor.description]
            users = [dict(zip(columns, row)) for row in cursor.fetchall()]
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

            with connection.cursor() as cursor:
                cursor.execute("SELECT id, email, password_hash, role FROM users WHERE email = %s", [email])
                row = cursor.fetchone()

                if row:
                    db_password = row[2]
                    if db_password == password:
                        return JsonResponse({'success': True})

            return JsonResponse({'success': False, 'error': 'Nieprawidłowy e-mail lub hasło'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)
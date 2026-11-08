from django.http import JsonResponse
from django.db import connection
from django.views.decorators.csrf import csrf_exempt
import json
import traceback


def api_users(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, email, role FROM users")
            columns = [col[0] for col in cursor.description]
            users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return JsonResponse({'users': users})
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


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
                        return JsonResponse({'success': True, 'user_id': row[0], 'role': row[3]})

            return JsonResponse({'success': False, 'error': 'Nieprawidłowy e-mail lub hasło'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_register(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            password = data.get('password')

            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE email = %s", [email])
                existing_user = cursor.fetchone()

                if existing_user:
                    return JsonResponse({'success': False, 'error': 'Użytkownik o takim e-mailu już istnieje'},
                                        status=400)

                cursor.execute(
                    "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
                    [email, password, 'user']
                )
                user_id = cursor.fetchone()[0]
                connection.commit()

            return JsonResponse({'success': True, 'user_id': user_id})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_profile(request):
    user_id = request.GET.get('user_id') or json.loads(request.body or '{}').get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Brak identyfikatora użytkownika'}, status=400)

    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT height_cm, target_calories, target_protein_g, target_carbs_g, target_fat_g FROM user_profiles WHERE user_id = %s",
                    [user_id])
                row = cursor.fetchone()
                if not row:
                    return JsonResponse({'profile': None})
                cols = [col[0] for col in cursor.description]
                return JsonResponse({'profile': dict(zip(cols, row))})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'PUT':
        try:
            data = json.loads(request.body)
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_profiles (user_id, height_cm, target_calories, target_protein_g, target_carbs_g, target_fat_g, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                    height_cm = EXCLUDED.height_cm,
                    target_calories = EXCLUDED.target_calories,
                    target_protein_g = EXCLUDED.target_protein_g,
                    target_carbs_g = EXCLUDED.target_carbs_g,
                    target_fat_g = EXCLUDED.target_fat_g,
                    updated_at = CURRENT_TIMESTAMP
                """, [user_id, data.get('height_cm'), data.get('target_calories'), data.get('target_protein_g'),
                      data.get('target_carbs_g'), data.get('target_fat_g')])
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_body_measurements(request):
    user_id = request.GET.get('user_id') or json.loads(request.body or '{}').get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Brak identyfikatora użytkownika'}, status=400)

    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, measurement_date, weight_kg, body_fat_percentage, notes FROM body_measurements WHERE user_id = %s ORDER BY measurement_date DESC",
                    [user_id])
                cols = [col[0] for col in cursor.description]
                data = [dict(zip(cols, row)) for row in cursor.fetchall()]
            return JsonResponse({'measurements': data})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO body_measurements (user_id, measurement_date, weight_kg, body_fat_percentage, notes) VALUES (%s, %s, %s, %s, %s)",
                    [user_id, data.get('measurement_date'), data.get('weight_kg'), data.get('body_fat_percentage'),
                     data.get('notes')]
                )
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_workouts(request):
    user_id = request.GET.get('user_id') or json.loads(request.body or '{}').get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Brak identyfikatora użytkownika'}, status=400)

    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, name, start_time, end_time, calories_burned, notes FROM workouts WHERE user_id = %s ORDER BY start_time DESC",
                    [user_id])
                cols = [col[0] for col in cursor.description]
                workouts = [dict(zip(cols, row)) for row in cursor.fetchall()]
            return JsonResponse({'workouts': workouts})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO workouts (user_id, name, start_time, end_time, calories_burned, notes) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    [user_id, data.get('name'), data.get('start_time'), data.get('end_time'),
                     data.get('calories_burned'), data.get('notes')]
                )
                workout_id = cursor.fetchone()[0]
                connection.commit()
            return JsonResponse({'success': True, 'workout_id': workout_id})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_workout_sets(request):
    if request.method == 'GET':
        try:
            workout_id = request.GET.get('workout_id')
            if not workout_id:
                return JsonResponse({'error': 'Brak identyfikatora treningu'}, status=400)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, workout_id, exercise_id, set_order, reps, weight, rpe FROM workout_sets WHERE workout_id = %s ORDER BY set_order ASC",
                    [workout_id])
                cols = [col[0] for col in cursor.description]
                sets = [dict(zip(cols, row)) for row in cursor.fetchall()]
            return JsonResponse({'workout_sets': sets})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO workout_sets (workout_id, exercise_id, set_order, reps, weight, rpe) VALUES (%s, %s, %s, %s, %s, %s)",
                    [data.get('workout_id'), data.get('exercise_id'), data.get('set_order'), data.get('reps'),
                     data.get('weight'), data.get('rpe')]
                )
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_exercises(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, target_muscle, equipment_type FROM exercises ORDER BY name ASC")
            cols = [col[0] for col in cursor.description]
            exercises = [dict(zip(cols, row)) for row in cursor.fetchall()]
        return JsonResponse({'exercises': exercises})
    except Exception as e:
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)


@csrf_exempt
def api_calories(request):
    user_id = request.GET.get('user_id') or json.loads(request.body or '{}').get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Brak identyfikatora użytkownika'}, status=400)

    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT f.id, f.name, f.calories_100g as calories 
                    FROM foods f 
                    JOIN meal_entries me ON f.id = me.food_id 
                    JOIN meals m ON me.meal_id = m.id 
                    WHERE m.user_id = %s
                """, [user_id])
                cols = [col[0] for col in cursor.description]
                items = [dict(zip(cols, row)) for row in cursor.fetchall()]
            return JsonResponse({'items': items})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name')
            calories = data.get('calories')

            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO meals (user_id, consumption_date, meal_type) VALUES (%s, CURRENT_DATE, 'snack') RETURNING id",
                    [user_id]
                )
                meal_id = cursor.fetchone()[0]

                cursor.execute(
                    "INSERT INTO foods (name, calories_100g, protein_100g, carbs_100g, fats_100g) VALUES (%s, %s, 0, 0, 0) RETURNING id",
                    [name, calories]
                )
                food_id = cursor.fetchone()[0]

                cursor.execute(
                    "INSERT INTO meal_entries (meal_id, food_id, weight_grams) VALUES (%s, %s, 100)",
                    [meal_id, food_id]
                )
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'DELETE':
        try:
            item_id = request.GET.get('id') or json.loads(request.body or '{}').get('id')
            with connection.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM meals WHERE id IN (
                        SELECT m.id FROM meals m 
                        JOIN meal_entries me ON m.id = me.meal_id 
                        WHERE me.food_id = %s AND m.user_id = %s
                    )
                """, [item_id, user_id])
                cursor.execute("DELETE FROM foods WHERE id = %s", [item_id])
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_meals(request):
    user_id = request.GET.get('user_id') or json.loads(request.body or '{}').get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Brak identyfikatora użytkownika'}, status=400)

    type_mapping = {
        "Śniadanie": "breakfast",
        "Obiad": "lunch",
        "Kolacja": "dinner",
        "Przekąski": "snack"
    }
    reverse_mapping = {v: k for k, v in type_mapping.items()}

    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT m.id, f.name, f.brand as description, m.meal_type 
                    FROM meals m
                    LEFT JOIN meal_entries me ON m.id = me.meal_id
                    LEFT JOIN foods f ON me.food_id = f.id
                    WHERE m.user_id = %s
                """, [user_id])
                rows = cursor.fetchall()
                meals = []
                for row in rows:
                    meals.append({
                        'id': row[0],
                        'name': row[1] or '',
                        'description': row[2] or '',
                        'type': reverse_mapping.get(row[3], 'Śniadanie')
                    })
            return JsonResponse({'meals': meals})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name')
            description = data.get('description', '')
            ui_type = data.get('type', 'Śniadanie')
            db_type = type_mapping.get(ui_type, 'breakfast')

            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO meals (user_id, consumption_date, meal_type) VALUES (%s, CURRENT_DATE, %s) RETURNING id",
                    [user_id, db_type]
                )
                meal_id = cursor.fetchone()[0]

                cursor.execute(
                    "INSERT INTO foods (name, brand, calories_100g, protein_100g, carbs_100g, fats_100g) VALUES (%s, %s, 0, 0, 0, 0) RETURNING id",
                    [name, description]
                )
                food_id = cursor.fetchone()[0]

                cursor.execute(
                    "INSERT INTO meal_entries (meal_id, food_id, weight_grams) VALUES (%s, %s, 100)",
                    [meal_id, food_id]
                )
                connection.commit()
            return JsonResponse({'success': True, 'id': meal_id})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'DELETE':
        try:
            meal_id = request.GET.get('id') or json.loads(request.body or '{}').get('id')
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM meals WHERE id = %s AND user_id = %s", [meal_id, user_id])
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
def api_macros(request):
    user_id = request.GET.get('user_id') or json.loads(request.body or '{}').get('user_id')
    if not user_id:
        return JsonResponse({'error': 'Brak identyfikatora użytkownika'}, status=400)

    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT target_protein_g, target_fat_g, target_carbs_g FROM user_profiles WHERE user_id = %s",
                    [user_id])
                row = cursor.fetchone()
                if not row:
                    return JsonResponse({'protein': 0, 'fat': 0, 'carbs': 0})
                return JsonResponse({'protein': row[0] or 0, 'fat': row[1] or 0, 'carbs': row[2] or 0})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            protein = data.get('protein', 0)
            fat = data.get('fat', 0)
            carbs = data.get('carbs', 0)

            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_profiles (user_id, target_protein_g, target_fat_g, target_carbs_g)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                    target_protein_g = EXCLUDED.target_protein_g,
                    target_fat_g = EXCLUDED.target_fat_g,
                    target_carbs_g = EXCLUDED.target_carbs_g
                """, [user_id, protein, fat, carbs])
                connection.commit()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
    return JsonResponse({'error': 'Method not allowed'}, status=405)
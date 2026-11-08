import json
import logging
import math
from functools import wraps

from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
MEAL_TYPE_INPUT = {
    "Śniadanie": "breakfast", "Obiad": "lunch",
    "Kolacja": "dinner", "Przekąski": "snack",
    "breakfast": "breakfast", "lunch": "lunch",
    "dinner": "dinner", "snack": "snack",
}
MEAL_TYPE_LABEL = {
    "breakfast": "Śniadanie", "lunch": "Obiad",
    "dinner": "Kolacja", "snack": "Przekąski",
}


def _json(request):
    try:
        value = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Niepoprawny JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Żądanie musi zawierać obiekt JSON.")
    return value


def _error(message, status=400):
    return JsonResponse({"success": False, "error": message}, status=status)


def _server_error(message):
    logger.exception("Błąd API diety")
    return _error(message, 500)


def _user_id(request):
    try:
        value = request.session.get("user_id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def require_diet_user(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if _user_id(request) is None:
            return _error("Sesja wygasła lub użytkownik nie jest zalogowany.", 401)
        return view(request, *args, **kwargs)
    return wrapped


def _number(value, field, minimum=0):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Pole {field} musi być liczbą.") from exc
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"Pole {field} musi być liczbą nie mniejszą niż {minimum}.")
    return number


def _entry_totals(food, grams):
    factor = grams / 100.0
    return {
        "calories": float(food["calories_100g"]) * factor,
        "protein": float(food["protein_100g"]) * factor,
        "carbs": float(food["carbs_100g"]) * factor,
        "fat": float(food["fats_100g"]) * factor,
    }


@require_http_methods(["GET", "POST"])
@require_diet_user
def api_foods(request):
    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, name, brand, calories_100g, protein_100g,
                           carbs_100g, fats_100g
                    FROM foods
                    ORDER BY name, brand NULLS FIRST, id
                """)
                columns = [c[0] for c in cursor.description]
                foods = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"foods": foods})
        except Exception:
            return _server_error("Nie udało się pobrać katalogu produktów.")

    try:
        data = _json(request)
        name = str(data.get("name") or "").strip()
        brand = str(data.get("brand") or "").strip() or None
        if not name:
            return _error("Nazwa produktu jest wymagana.")
        calories = _number(data.get("calories_100g"), "calories_100g")
        protein = _number(data.get("protein_100g", 0), "protein_100g")
        carbs = _number(data.get("carbs_100g", 0), "carbs_100g")
        fats = _number(data.get("fats_100g", data.get("fat_100g", 0)), "fats_100g")
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO foods
                        (name, brand, calories_100g, protein_100g, carbs_100g, fats_100g)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, [name, brand, calories, protein, carbs, fats])
                food_id = cursor.fetchone()[0]
        return JsonResponse({"success": True, "id": food_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się dodać produktu do katalogu.")


@require_http_methods(["GET", "POST", "DELETE"])
@require_diet_user
def api_meals(request):
    user_id = _user_id(request)

    if request.method == "GET":
        date_filter = request.GET.get("date")
        try:
            with connection.cursor() as cursor:
                sql = """
                    SELECT m.id, m.consumption_date, m.meal_type,
                           me.id AS entry_id, me.weight_grams,
                           f.id AS food_id, f.name, f.brand,
                           f.calories_100g, f.protein_100g,
                           f.carbs_100g, f.fats_100g
                    FROM meals m
                    LEFT JOIN meal_entries me ON me.meal_id = m.id
                    LEFT JOIN foods f ON f.id = me.food_id
                    WHERE m.user_id = %s
                """
                params = [user_id]
                if date_filter:
                    sql += " AND m.consumption_date = %s"
                    params.append(date_filter)
                sql += " ORDER BY m.consumption_date DESC, m.id DESC, me.id"
                cursor.execute(sql, params)
                rows = cursor.fetchall()

            grouped = {}
            for row in rows:
                meal_id = row[0]
                if meal_id not in grouped:
                    grouped[meal_id] = {
                        "id": meal_id, "date": row[1].isoformat(),
                        "type": MEAL_TYPE_LABEL.get(row[2], row[2]),
                        "meal_type": row[2], "foods": [],
                        "totals": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
                    }
                if row[5] is None:
                    continue
                food = {
                    "entry_id": row[3], "id": row[5], "name": row[6],
                    "brand": row[7] or "", "weight_grams": row[4],
                    "calories_100g": row[8], "protein_100g": row[9],
                    "carbs_100g": row[10], "fats_100g": row[11],
                }
                totals = _entry_totals(food, row[4])
                food.update(totals)
                grouped[meal_id]["foods"].append(food)
                for key, value in totals.items():
                    grouped[meal_id]["totals"][key] += value

            meals = list(grouped.values())
            for meal in meals:
                meal["name"] = ", ".join(f["name"] for f in meal["foods"])
            return JsonResponse({"meals": meals})
        except Exception:
            return _server_error("Nie udało się pobrać dziennika posiłków.")

    if request.method == "POST":
        try:
            data = _json(request)
            meal_type = MEAL_TYPE_INPUT.get(data.get("type", "breakfast"))
            if meal_type not in MEAL_TYPES:
                return _error("Nieprawidłowa kategoria posiłku.")
            consumption_date = data.get("date")
            items = data.get("foods")
            if not isinstance(items, list) or not items:
                return _error("Posiłek musi zawierać co najmniej jeden produkt.")
            normalized = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Każdy produkt musi być obiektem.")
                try:
                    food_id = int(item.get("food_id", item.get("id")))
                except (TypeError, ValueError) as exc:
                    raise ValueError("Nieprawidłowy identyfikator produktu.") from exc
                grams = _number(item.get("weight_grams"), "weight_grams", 1)
                if not grams.is_integer():
                    raise ValueError("Gramatura musi być liczbą całkowitą.")
                normalized.append((food_id, int(grams)))

            with transaction.atomic():
                with connection.cursor() as cursor:
                    food_ids = list({item[0] for item in normalized})
                    cursor.execute(
                        "SELECT id FROM foods WHERE id = ANY(%s)",
                        [food_ids],
                    )
                    found = {row[0] for row in cursor.fetchall()}
                    missing = set(food_ids) - found
                    if missing:
                        return _error("Jeden lub więcej produktów nie istnieje.", 404)
                    if consumption_date:
                        cursor.execute("""
                            INSERT INTO meals (user_id, consumption_date, meal_type)
                            VALUES (%s, %s, %s) RETURNING id
                        """, [user_id, consumption_date, meal_type])
                    else:
                        cursor.execute("""
                            INSERT INTO meals (user_id, consumption_date, meal_type)
                            VALUES (%s, CURRENT_DATE, %s) RETURNING id
                        """, [user_id, meal_type])
                    meal_id = cursor.fetchone()[0]
                    for food_id, grams in normalized:
                        cursor.execute("""
                            INSERT INTO meal_entries (meal_id, food_id, weight_grams)
                            VALUES (%s, %s, %s)
                        """, [meal_id, food_id, grams])
            return JsonResponse({"success": True, "id": meal_id}, status=201)
        except ValueError as exc:
            return _error(str(exc))
        except Exception:
            return _server_error("Nie udało się zapisać posiłku.")

    meal_id = request.GET.get("id")
    if not meal_id:
        return _error("Brak identyfikatora posiłku.")
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM meals WHERE id = %s AND user_id = %s RETURNING id",
                    [meal_id, user_id],
                )
                if not cursor.fetchone():
                    return _error("Nie znaleziono posiłku.", 404)
                cursor.execute("DELETE FROM meal_entries WHERE meal_id = %s", [meal_id])
        return JsonResponse({"success": True})
    except Exception:
        return _server_error("Nie udało się usunąć posiłku.")


@require_http_methods(["GET", "DELETE"])
@require_diet_user
def api_calories(request):
    user_id = _user_id(request)
    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(f.calories_100g * me.weight_grams / 100.0), 0),
                           COUNT(me.id)
                    FROM meals m
                    LEFT JOIN meal_entries me ON me.meal_id = m.id
                    LEFT JOIN foods f ON f.id = me.food_id
                    WHERE m.user_id = %s AND m.consumption_date = CURRENT_DATE
                """, [user_id])
                total, count = cursor.fetchone()
                cursor.execute("""
                    SELECT me.id, f.name, me.weight_grams,
                           f.calories_100g * me.weight_grams / 100.0 AS calories,
                           f.protein_100g * me.weight_grams / 100.0 AS protein,
                           f.carbs_100g * me.weight_grams / 100.0 AS carbs,
                           f.fats_100g * me.weight_grams / 100.0 AS fat,
                           m.meal_type
                    FROM meals m
                    JOIN meal_entries me ON me.meal_id = m.id
                    JOIN foods f ON f.id = me.food_id
                    WHERE m.user_id = %s AND m.consumption_date = CURRENT_DATE
                    ORDER BY m.id, me.id
                """, [user_id])
                columns = [c[0] for c in cursor.description]
                items = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"totalCalories": total, "count": count, "items": items})
        except Exception:
            return _server_error("Nie udało się obliczyć dziennego bilansu.")
    entry_id = request.GET.get("id")
    if not entry_id:
        return _error("Brak identyfikatora wpisu.")
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM meal_entries me
                    USING meals m
                    WHERE me.meal_id = m.id AND me.id = %s AND m.user_id = %s
                    RETURNING me.id, me.meal_id
                """, [entry_id, user_id])
                row = cursor.fetchone()
                if not row:
                    return _error("Nie znaleziono wpisu.", 404)
                meal_id = row[1]
                cursor.execute("""
                    DELETE FROM meals m
                    WHERE m.id = %s AND m.user_id = %s
                      AND NOT EXISTS (SELECT 1 FROM meal_entries e WHERE e.meal_id = m.id)
                """, [meal_id, user_id])
        return JsonResponse({"success": True})
    except Exception:
        return _server_error("Nie udało się usunąć wpisu.")


@require_http_methods(["GET", "POST"])
@require_diet_user
def api_macros(request):
    user_id = _user_id(request)
    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(p.target_protein_g, 0),
                           COALESCE(p.target_fat_g, 0),
                           COALESCE(p.target_carbs_g, 0),
                           COALESCE(SUM(f.protein_100g * me.weight_grams / 100.0), 0),
                           COALESCE(SUM(f.fats_100g * me.weight_grams / 100.0), 0),
                           COALESCE(SUM(f.carbs_100g * me.weight_grams / 100.0), 0),
                           COALESCE(SUM(f.calories_100g * me.weight_grams / 100.0), 0)
                    FROM (SELECT %s::integer AS user_id) u
                    LEFT JOIN user_profiles p ON p.user_id = u.user_id
                    LEFT JOIN meals m ON m.user_id = u.user_id
                        AND m.consumption_date = CURRENT_DATE
                    LEFT JOIN meal_entries me ON me.meal_id = m.id
                    LEFT JOIN foods f ON f.id = me.food_id
                    GROUP BY p.target_protein_g, p.target_fat_g, p.target_carbs_g
                """, [user_id])
                row = cursor.fetchone()
            return JsonResponse({
                "protein": row[0], "fat": row[1], "carbs": row[2],
                "consumedProtein": row[3], "consumedFat": row[4],
                "consumedCarbs": row[5], "consumedCalories": row[6],
            })
        except Exception:
            return _server_error("Nie udało się pobrać celów i spożycia makro.")

    try:
        data = _json(request)
        protein = _number(data.get("protein"), "protein")
        fat = _number(data.get("fat"), "fat")
        carbs = _number(data.get("carbs"), "carbs")
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_profiles
                        (user_id, target_protein_g, target_fat_g, target_carbs_g)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        target_protein_g = EXCLUDED.target_protein_g,
                        target_fat_g = EXCLUDED.target_fat_g,
                        target_carbs_g = EXCLUDED.target_carbs_g,
                        updated_at = CURRENT_TIMESTAMP
                """, [user_id, protein, fat, carbs])
        return JsonResponse({"success": True})
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać celów makro.")

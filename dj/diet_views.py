import json
import logging
from functools import wraps

from django.db import IntegrityError, connection, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _read_json(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Niepoprawny format JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Treść żądania musi być obiektem JSON.")
    return data


def _error(message, status=400):
    return JsonResponse({"success": False, "error": message}, status=status)


def _server_error(message):
    logger.exception("Błąd modułu diety")
    return _error(message, status=500)


def _session_user_id(request):
    try:
        value = request.session.get("user_id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def require_session(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if _session_user_id(request) is None:
            return _error("Sesja wygasła lub użytkownik nie jest zalogowany.", status=401)
        return view_func(request, *args, **kwargs)
    return wrapped


def _number(value, field_name, *, default=None, minimum=0):
    if value in (None, ""):
        if default is not None:
            return default
        raise ValueError(f"Pole {field_name} jest wymagane.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Pole {field_name} musi być liczbą.") from exc
    if not (parsed == parsed and abs(parsed) != float("inf")):
        raise ValueError(f"Pole {field_name} musi być poprawną liczbą.")
    if parsed < minimum:
        raise ValueError(f"Pole {field_name} nie może być mniejsze niż {minimum}.")
    return parsed


def _nutrition_payload(data, *, require_calories=False):
    calories = _number(data.get("calories"), "calories", default=None if require_calories else 0)
    protein = _number(data.get("protein"), "protein", default=0)
    carbs = _number(data.get("carbs"), "carbs", default=0)
    fats = _number(data.get("fat", data.get("fats")), "fat", default=0)
    grams = _number(data.get("weight_grams"), "weight_grams", default=100, minimum=1)
    if grams != int(grams):
        raise ValueError("Masa produktu musi być liczbą całkowitą.")
    return calories, protein, carbs, fats, int(grams)


def _insert_food_entry(cursor, *, user_id, meal_type, name, brand, nutrition):
    calories, protein, carbs, fats, grams = nutrition
    cursor.execute(
        """
        INSERT INTO meals (user_id, consumption_date, meal_type)
        VALUES (%s, CURRENT_DATE, %s)
        RETURNING id
        """,
        [user_id, meal_type],
    )
    meal_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO foods
            (name, brand, calories_100g, protein_100g, carbs_100g, fats_100g)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        [name, brand or None, calories, protein, carbs, fats],
    )
    food_id = cursor.fetchone()[0]
    cursor.execute(
        """
        INSERT INTO meal_entries (meal_id, food_id, weight_grams)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        [meal_id, food_id, grams],
    )
    return meal_id, food_id, cursor.fetchone()[0]


@require_http_methods(["GET", "POST", "DELETE"])
@require_session
def api_calories(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT me.id, f.id AS food_id, f.name, me.weight_grams,
                           (f.calories_100g * me.weight_grams / 100.0) AS calories,
                           (f.protein_100g * me.weight_grams / 100.0) AS protein,
                           (f.carbs_100g * me.weight_grams / 100.0) AS carbs,
                           (f.fats_100g * me.weight_grams / 100.0) AS fat,
                           m.consumption_date, m.meal_type
                    FROM meal_entries me
                    JOIN meals m ON m.id = me.meal_id
                    JOIN foods f ON f.id = me.food_id
                    WHERE m.user_id = %s AND m.consumption_date = CURRENT_DATE
                    ORDER BY m.id, me.id
                    """,
                    [user_id],
                )
                columns = [column[0] for column in cursor.description]
                items = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"items": items})
        except Exception:
            return _server_error("Nie udało się pobrać dzisiejszego bilansu kalorii.")

    if request.method == "POST":
        try:
            data = _read_json(request)
            name = str(data.get("name", "")).strip()
            if not name:
                return _error("Podaj nazwę produktu.")
            nutrition = _nutrition_payload(data, require_calories=True)
            with transaction.atomic():
                with connection.cursor() as cursor:
                    meal_id, food_id, entry_id = _insert_food_entry(
                        cursor, user_id=user_id, meal_type="snack",
                        name=name, brand=data.get("brand", ""), nutrition=nutrition,
                    )
            calories, protein, carbs, fats, grams = nutrition
            return JsonResponse({
                "success": True, "id": entry_id, "meal_id": meal_id, "food_id": food_id,
                "name": name, "weight_grams": grams,
                "calories": calories * grams / 100,
                "protein": protein * grams / 100,
                "carbs": carbs * grams / 100,
                "fat": fats * grams / 100,
            }, status=201)
        except ValueError as exc:
            return _error(str(exc))
        except IntegrityError:
            return _error("Nie udało się zapisać produktu z powodu konfliktu danych.", status=409)
        except Exception:
            return _server_error("Nie udało się dodać produktu.")

    entry_id = request.GET.get("id")
    if not entry_id:
        try:
            entry_id = _read_json(request).get("id")
        except ValueError as exc:
            return _error(str(exc))
    if not entry_id:
        return _error("Brak identyfikatora wpisu.")

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT me.meal_id, me.food_id
                    FROM meal_entries me
                    JOIN meals m ON m.id = me.meal_id
                    WHERE me.id = %s AND m.user_id = %s
                    """,
                    [entry_id, user_id],
                )
                row = cursor.fetchone()
                if not row:
                    return _error("Nie znaleziono wpisu.", status=404)
                meal_id, food_id = row
                cursor.execute("DELETE FROM meal_entries WHERE id = %s", [entry_id])
                cursor.execute(
                    """
                    DELETE FROM meals m
                    WHERE m.id = %s AND m.user_id = %s
                      AND NOT EXISTS (SELECT 1 FROM meal_entries me WHERE me.meal_id = m.id)
                    """,
                    [meal_id, user_id],
                )
                cursor.execute(
                    """
                    DELETE FROM foods f
                    WHERE f.id = %s
                      AND NOT EXISTS (SELECT 1 FROM meal_entries me WHERE me.food_id = f.id)
                    """,
                    [food_id],
                )
        return JsonResponse({"success": True})
    except Exception:
        return _server_error("Nie udało się usunąć wpisu.")


@require_http_methods(["GET", "POST", "DELETE"])
@require_session
def api_meals(request):
    user_id = _session_user_id(request)
    type_mapping = {
        "Śniadanie": "breakfast",
        "Obiad": "lunch",
        "Kolacja": "dinner",
        "Przekąski": "snack",
        "breakfast": "breakfast",
        "lunch": "lunch",
        "dinner": "dinner",
        "snack": "snack",
    }
    reverse_mapping = {
        "breakfast": "Śniadanie", "lunch": "Obiad",
        "dinner": "Kolacja", "snack": "Przekąski",
    }

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.id, m.consumption_date, m.meal_type,
                           me.id AS entry_id, me.weight_grams,
                           f.id AS food_id, f.name, f.brand,
                           f.calories_100g, f.protein_100g, f.carbs_100g, f.fats_100g
                    FROM meals m
                    LEFT JOIN meal_entries me ON me.meal_id = m.id
                    LEFT JOIN foods f ON f.id = me.food_id
                    WHERE m.user_id = %s
                    ORDER BY m.consumption_date DESC, m.id DESC, me.id
                    """,
                    [user_id],
                )
                rows = cursor.fetchall()

            grouped = {}
            for row in rows:
                meal_id = row[0]
                if meal_id not in grouped:
                    grouped[meal_id] = {
                        "id": meal_id, "date": row[1],
                        "type": reverse_mapping.get(row[2], "Śniadanie"),
                        "name": "", "description": "", "foods": [],
                    }
                if row[5] is not None:
                    food = {
                        "entry_id": row[3], "id": row[5], "name": row[6],
                        "brand": row[7] or "", "weight_grams": row[4],
                        "calories_100g": row[8], "protein_100g": row[9],
                        "carbs_100g": row[10], "fat_100g": row[11],
                        "calories": row[8] * row[4] / 100,
                        "protein": row[9] * row[4] / 100,
                        "carbs": row[10] * row[4] / 100,
                        "fat": row[11] * row[4] / 100,
                    }
                    grouped[meal_id]["foods"].append(food)

            meals = list(grouped.values())
            for meal in meals:
                meal["name"] = ", ".join(food["name"] for food in meal["foods"])
                meal["description"] = ", ".join(food["brand"] for food in meal["foods"] if food["brand"])
            return JsonResponse({"meals": meals})
        except Exception:
            return _server_error("Nie udało się pobrać dziennika posiłków.")

    if request.method == "POST":
        try:
            data = _read_json(request)
            name = str(data.get("name", "")).strip()
            description = str(data.get("description") or "").strip()
            ui_type = data.get("type", "Śniadanie")
            meal_type = type_mapping.get(ui_type)
            if not name:
                return _error("Podaj nazwę produktu lub posiłku.")
            if not meal_type:
                return _error("Nieprawidłowa kategoria posiłku.")
            nutrition = _nutrition_payload(data, require_calories=False)
            with transaction.atomic():
                with connection.cursor() as cursor:
                    meal_id, food_id, entry_id = _insert_food_entry(
                        cursor, user_id=user_id, meal_type=meal_type,
                        name=name, brand=description, nutrition=nutrition,
                    )
            return JsonResponse({
                "success": True, "id": meal_id, "food_id": food_id,
                "entry_id": entry_id,
            }, status=201)
        except ValueError as exc:
            return _error(str(exc))
        except IntegrityError:
            return _error("Nie udało się zapisać posiłku z powodu konfliktu danych.", status=409)
        except Exception:
            return _server_error("Nie udało się zapisać posiłku.")

    meal_id = request.GET.get("id")
    if not meal_id:
        try:
            meal_id = _read_json(request).get("id")
        except ValueError as exc:
            return _error(str(exc))
    if not meal_id:
        return _error("Brak identyfikatora posiłku.")

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM meals WHERE id = %s AND user_id = %s",
                    [meal_id, user_id],
                )
                if not cursor.fetchone():
                    return _error("Nie znaleziono posiłku.", status=404)
                cursor.execute(
                    "SELECT food_id FROM meal_entries WHERE meal_id = %s",
                    [meal_id],
                )
                food_ids = [row[0] for row in cursor.fetchall()]
                cursor.execute("DELETE FROM meal_entries WHERE meal_id = %s", [meal_id])
                cursor.execute(
                    "DELETE FROM meals WHERE id = %s AND user_id = %s",
                    [meal_id, user_id],
                )
                for food_id in food_ids:
                    cursor.execute(
                        """
                        DELETE FROM foods f
                        WHERE f.id = %s
                          AND NOT EXISTS (SELECT 1 FROM meal_entries me WHERE me.food_id = f.id)
                        """,
                        [food_id],
                    )
        return JsonResponse({"success": True})
    except Exception:
        return _server_error("Nie udało się usunąć posiłku.")


@require_http_methods(["GET", "POST"])
@require_session
def api_macros(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COALESCE(p.target_protein_g, 0),
                        COALESCE(p.target_fat_g, 0),
                        COALESCE(p.target_carbs_g, 0),
                        COALESCE(SUM(f.protein_100g * me.weight_grams / 100.0), 0),
                        COALESCE(SUM(f.fats_100g * me.weight_grams / 100.0), 0),
                        COALESCE(SUM(f.carbs_100g * me.weight_grams / 100.0), 0),
                        COALESCE(SUM(f.calories_100g * me.weight_grams / 100.0), 0)
                    FROM (SELECT %s::integer AS user_id) current_user
                    LEFT JOIN user_profiles p ON p.user_id = current_user.user_id
                    LEFT JOIN meals m ON m.user_id = current_user.user_id
                        AND m.consumption_date = CURRENT_DATE
                    LEFT JOIN meal_entries me ON me.meal_id = m.id
                    LEFT JOIN foods f ON f.id = me.food_id
                    GROUP BY p.target_protein_g, p.target_fat_g, p.target_carbs_g
                    """,
                    [user_id],
                )
                row = cursor.fetchone()
            return JsonResponse({
                "protein": row[0], "fat": row[1], "carbs": row[2],
                "consumedProtein": row[3], "consumedFat": row[4],
                "consumedCarbs": row[5], "consumedCalories": row[6],
            })
        except Exception:
            return _server_error("Nie udało się pobrać celów i spożycia makro.")

    try:
        data = _read_json(request)
        protein = _number(data.get("protein"), "protein")
        fat = _number(data.get("fat"), "fat")
        carbs = _number(data.get("carbs"), "carbs")
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_profiles
                        (user_id, target_protein_g, target_fat_g, target_carbs_g)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        target_protein_g = EXCLUDED.target_protein_g,
                        target_fat_g = EXCLUDED.target_fat_g,
                        target_carbs_g = EXCLUDED.target_carbs_g,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [user_id, protein, fat, carbs],
                )
        return JsonResponse({"success": True})
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać celów makro.")

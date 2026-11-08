import json
import logging
import math
from functools import wraps

from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _user_id(request):
    try:
        value = request.session.get("user_id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _error(message, status=400):
    return JsonResponse({"success": False, "error": message}, status=status)


def _number(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Pole {field} musi być liczbą.") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Pole {field} musi być liczbą nieujemną.")
    return number


def _read_json(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Niepoprawny JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Żądanie musi zawierać obiekt JSON.")
    return data


def _require_session(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if _user_id(request) is None:
            return _error("Sesja wygasła lub użytkownik nie jest zalogowany.", 401)
        return view(request, *args, **kwargs)
    return wrapped


@require_http_methods(["GET", "POST"])
@_require_session
def api_macros(request):
    user_id = _user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        COALESCE(p.target_protein_g, 0),
                        COALESCE(p.target_fat_g, 0),
                        COALESCE(p.target_carbs_g, 0),
                        COALESCE(
                            p.target_calories,
                            ROUND((
                                COALESCE(p.target_protein_g, 0) * 4
                                + COALESCE(p.target_fat_g, 0) * 9
                                + COALESCE(p.target_carbs_g, 0) * 4
                            )::numeric)::integer,
                            0
                        ),
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
                    GROUP BY p.target_protein_g, p.target_fat_g,
                             p.target_carbs_g, p.target_calories
                """, [user_id])
                row = cursor.fetchone()

            return JsonResponse({
                "protein": row[0],
                "fat": row[1],
                "carbs": row[2],
                "targetCalories": row[3],
                "consumedProtein": row[4],
                "consumedFat": row[5],
                "consumedCarbs": row[6],
                "consumedCalories": row[7],
            })
        except Exception:
            logger.exception("Błąd pobierania makro")
            return _error("Nie udało się pobrać celów i spożycia makro.", 500)

    try:
        data = _read_json(request)
        protein = _number(data.get("protein"), "protein")
        fat = _number(data.get("fat"), "fat")
        carbs = _number(data.get("carbs"), "carbs")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_profiles (
                        user_id, target_calories, target_protein_g,
                        target_fat_g, target_carbs_g, updated_at
                    )
                    VALUES (
                        %s,
                        ROUND((%s * 4 + %s * 9 + %s * 4)::numeric)::integer,
                        %s, %s, %s, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (user_id) DO UPDATE SET
                        target_calories = EXCLUDED.target_calories,
                        target_protein_g = EXCLUDED.target_protein_g,
                        target_fat_g = EXCLUDED.target_fat_g,
                        target_carbs_g = EXCLUDED.target_carbs_g,
                        updated_at = CURRENT_TIMESTAMP
                """, [user_id, protein, fat, carbs, protein, fat, carbs])

        target_calories = round(protein * 4 + fat * 9 + carbs * 4)
        return JsonResponse({
            "success": True,
            "targetCalories": target_calories,
        })
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        logger.exception("Błąd zapisywania makro")
        return _error("Nie udało się zapisać celów makro.", 500)

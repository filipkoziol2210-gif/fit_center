import json
import logging
import secrets
from functools import wraps
from django.middleware.csrf import get_token
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, connection, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST, require_http_methods

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wspólne funkcje pomocnicze
# ---------------------------------------------------------------------------


def _read_json(request):
    """Odczytuje JSON z request.body i zgłasza ValueError przy błędnych danych."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Niepoprawny format JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError("Treść żądania musi być obiektem JSON.")
    return data


def _error(message, status=400):
    return JsonResponse({"success": False, "error": message}, status=status)


def _server_error(message="Wystąpił wewnętrzny błąd serwera."):
    logger.exception("Błąd endpointu API")
    return _error(message, status=500)


def _session_user_id(request):
    """Identyfikator pochodzi wyłącznie z sesji, nigdy z parametru user_id."""
    value = request.session.get("user_id")
    try:
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


def _number(value, field_name, *, optional=False, minimum=None):
    if value in (None, "") and optional:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Pole {field_name} musi być liczbą.")

    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise ValueError(f"Pole {field_name} musi być poprawną liczbą.")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"Pole {field_name} nie może być mniejsze niż {minimum}.")
    return parsed


def _set_session(request, user_id, role):
    # Usuwa poprzednią sesję, aby nie przenosić danych między kontami.
    request.session.flush()
    request.session["user_id"] = int(user_id)
    request.session["role"] = role
    request.session.set_expiry(60 * 60 * 24 * 14)  # 14 dni


# ---------------------------------------------------------------------------
# CSRF, rejestracja, logowanie i wylogowanie
# ---------------------------------------------------------------------------


@require_GET
@ensure_csrf_cookie
def api_csrf(request):
    return JsonResponse({
        "success": True,
        "csrfToken": get_token(request)
    })


@require_GET
def api_session(request):
    """Zwraca stan zalogowania na podstawie cookie sesji."""
    user_id = _session_user_id(request)
    if user_id is None:
        return JsonResponse({"authenticated": False})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT email, role FROM users WHERE id = %s LIMIT 1",
                [user_id],
            )
            row = cursor.fetchone()

        if not row:
            request.session.flush()
            return JsonResponse({"authenticated": False})

        return JsonResponse({
            "authenticated": True,
            "email": row[0],
            "role": row[1],
        })
    except Exception:
        return _server_error("Nie udało się sprawdzić sesji użytkownika.")


@require_GET
def api_users(request):
    """Lista użytkowników jest dostępna wyłącznie dla administratora."""
    if _session_user_id(request) is None:
        return _error("Brak autoryzacji.", status=401)
    if request.session.get("role") != "admin":
        return _error("Brak uprawnień.", status=403)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, email, role FROM users ORDER BY id")
            columns = [column[0] for column in cursor.description]
            users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return JsonResponse({"users": users})
    except Exception:
        return _server_error("Nie udało się pobrać użytkowników.")


@require_POST
@csrf_protect
def api_register(request):
    try:
        data = _read_json(request)
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password")

        if not email or "@" not in email:
            return _error("Podaj poprawny adres e-mail.")
        if not isinstance(password, str) or len(password) < 8:
            return _error("Hasło musi mieć co najmniej 8 znaków.")

        password_hash = make_password(password)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    [email],
                )
                if cursor.fetchone():
                    return _error("Użytkownik o takim e-mailu już istnieje.", status=409)

                cursor.execute(
                    """
                    INSERT INTO users (email, password_hash, role)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    [email, password_hash, "user"],
                )
                user_id = cursor.fetchone()[0]

        _set_session(request, user_id, "user")
        return JsonResponse({"success": True, "user_id": user_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except IntegrityError:
        return _error("Użytkownik o takim e-mailu już istnieje.", status=409)
    except Exception:
        return _server_error("Nie udało się utworzyć konta.")


@require_POST
@csrf_protect
def api_login(request):
    try:
        data = _read_json(request)
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password")

        if not email or not isinstance(password, str) or not password:
            return _error("Podaj e-mail i hasło.")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, email, password_hash, role FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                [email],
            )
            row = cursor.fetchone()

        if not row:
            return _error("Nieprawidłowy e-mail lub hasło.", status=401)

        user_id, _db_email, stored_password, role = row
        stored_password = str(stored_password or "")
        password_is_valid = check_password(password, stored_password)

        # Migracja starych kont: wcześniej aplikacja zapisywała hasła tekstem jawnym.
        # Po poprawnym logowaniu hasło jest natychmiast zastępowane hashem Django.
        if not password_is_valid and secrets.compare_digest(stored_password, password):
            password_is_valid = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    [make_password(password), user_id],
                )

        if not password_is_valid:
            return _error("Nieprawidłowy e-mail lub hasło.", status=401)

        _set_session(request, user_id, role)
        return JsonResponse({"success": True, "user_id": user_id, "role": role})
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zalogować.")


@require_POST
@csrf_protect
@require_session
def api_logout(request):
    request.session.flush()
    return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# Profil i pomiary ciała
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "PUT"])
@require_session
def api_profile(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT height_cm, target_calories, target_protein_g,
                           target_carbs_g, target_fat_g
                    FROM user_profiles
                    WHERE user_id = %s
                    """,
                    [user_id],
                )
                row = cursor.fetchone()
                if not row:
                    return JsonResponse({"profile": None})
                columns = [column[0] for column in cursor.description]
                return JsonResponse({"profile": dict(zip(columns, row))})
        except Exception:
            return _server_error("Nie udało się pobrać profilu.")

    try:
        data = _read_json(request)
        height_cm = _number(data.get("height_cm"), "height_cm", optional=True, minimum=0)
        target_calories = _number(data.get("target_calories"), "target_calories", optional=True, minimum=0)
        target_protein = _number(data.get("target_protein_g"), "target_protein_g", optional=True, minimum=0)
        target_carbs = _number(data.get("target_carbs_g"), "target_carbs_g", optional=True, minimum=0)
        target_fat = _number(data.get("target_fat_g"), "target_fat_g", optional=True, minimum=0)

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_profiles (
                        user_id, height_cm, target_calories, target_protein_g,
                        target_carbs_g, target_fat_g, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        height_cm = EXCLUDED.height_cm,
                        target_calories = EXCLUDED.target_calories,
                        target_protein_g = EXCLUDED.target_protein_g,
                        target_carbs_g = EXCLUDED.target_carbs_g,
                        target_fat_g = EXCLUDED.target_fat_g,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [user_id, height_cm, target_calories, target_protein, target_carbs, target_fat],
                )
        return JsonResponse({"success": True})
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać profilu.")


@require_http_methods(["GET", "POST"])
@require_session
def api_body_measurements(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, measurement_date, weight_kg, body_fat_percentage, notes
                    FROM body_measurements
                    WHERE user_id = %s
                    ORDER BY measurement_date DESC, id DESC
                    """,
                    [user_id],
                )
                columns = [column[0] for column in cursor.description]
                measurements = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"measurements": measurements})
        except Exception:
            return _server_error("Nie udało się pobrać pomiarów.")

    try:
        data = _read_json(request)
        measurement_date = data.get("measurement_date")
        if not measurement_date:
            return _error("Podaj datę pomiaru.")
        weight = _number(data.get("weight_kg"), "weight_kg", minimum=0.01)
        body_fat = _number(data.get("body_fat_percentage"), "body_fat_percentage", optional=True, minimum=0)
        if body_fat is not None and body_fat > 100:
            return _error("Procent tkanki tłuszczowej nie może przekraczać 100.")
        notes = str(data.get("notes") or "").strip()

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO body_measurements
                        (user_id, measurement_date, weight_kg, body_fat_percentage, notes)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    [user_id, measurement_date, weight, body_fat, notes],
                )
                measurement_id = cursor.fetchone()[0]
        return JsonResponse({"success": True, "id": measurement_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać pomiaru.")


# ---------------------------------------------------------------------------
# Treningi, serie i lista ćwiczeń
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
@require_session
def api_workouts(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, name, start_time, end_time, calories_burned, notes
                    FROM workouts
                    WHERE user_id = %s
                    ORDER BY start_time DESC, id DESC
                    """,
                    [user_id],
                )
                columns = [column[0] for column in cursor.description]
                workouts = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"workouts": workouts})
        except Exception:
            return _server_error("Nie udało się pobrać treningów.")

    try:
        data = _read_json(request)
        name = str(data.get("name", "")).strip()
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        if not name or not start_time or not end_time:
            return _error("Nazwa, czas rozpoczęcia i czas zakończenia są wymagane.")
        calories_burned = _number(data.get("calories_burned"), "calories_burned", optional=True, minimum=0)
        notes = str(data.get("notes") or "").strip()

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO workouts
                        (user_id, name, start_time, end_time, calories_burned, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    [user_id, name, start_time, end_time, calories_burned, notes],
                )
                workout_id = cursor.fetchone()[0]
        return JsonResponse({"success": True, "workout_id": workout_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać treningu.")


@require_http_methods(["GET", "POST"])
@require_session
def api_workout_sets(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        workout_id = request.GET.get("workout_id")
        if not workout_id:
            return _error("Brak identyfikatora treningu.")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ws.id, ws.workout_id, ws.exercise_id, ws.set_order,
                           ws.reps, ws.weight, ws.rpe
                    FROM workout_sets ws
                    INNER JOIN workouts w ON w.id = ws.workout_id
                    WHERE ws.workout_id = %s AND w.user_id = %s
                    ORDER BY ws.set_order ASC, ws.id ASC
                    """,
                    [workout_id, user_id],
                )
                columns = [column[0] for column in cursor.description]
                sets = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"workout_sets": sets})
        except Exception:
            return _server_error("Nie udało się pobrać serii treningowych.")

    try:
        data = _read_json(request)
        workout_id = data.get("workout_id")
        exercise_id = data.get("exercise_id")
        set_order = data.get("set_order")
        reps = data.get("reps")
        weight = _number(data.get("weight"), "weight", optional=True, minimum=0)
        rpe = _number(data.get("rpe"), "rpe", optional=True, minimum=0)

        if not all(value is not None for value in (workout_id, exercise_id, set_order, reps)):
            return _error("Trening, ćwiczenie, numer serii i liczba powtórzeń są wymagane.")
        try:
            set_order = int(set_order)
            reps = int(reps)
        except (TypeError, ValueError):
            return _error("Numer serii i liczba powtórzeń muszą być liczbami całkowitymi.")
        if set_order < 1 or reps < 0:
            return _error("Numer serii musi być dodatni, a powtórzenia nie mogą być ujemne.")
        if rpe is not None and rpe > 10:
            return _error("RPE musi mieścić się w zakresie 0–10.")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM workouts WHERE id = %s AND user_id = %s",
                    [workout_id, user_id],
                )
                if not cursor.fetchone():
                    return _error("Nie znaleziono treningu.", status=404)
                cursor.execute(
                    """
                    INSERT INTO workout_sets
                        (workout_id, exercise_id, set_order, reps, weight, rpe)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    [workout_id, exercise_id, set_order, reps, weight, rpe],
                )
                set_id = cursor.fetchone()[0]
        return JsonResponse({"success": True, "id": set_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać serii treningowej.")


@require_GET
@require_session
def api_exercises(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, target_muscle, equipment_type
                FROM exercises
                ORDER BY name ASC
                """
            )
            columns = [column[0] for column in cursor.description]
            exercises = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return JsonResponse({"exercises": exercises})
    except Exception:
        return _server_error("Nie udało się pobrać listy ćwiczeń.")


# ---------------------------------------------------------------------------
# Kalorie i dziennik posiłków
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST", "DELETE"])
@require_session
def api_calories(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        f.id,
                        f.name,
                        (
                            COALESCE(f.calories_100g, 0)::numeric
                            * COALESCE(me.weight_grams, 100)::numeric / 100
                        )::float AS calories
                    FROM foods f
                    INNER JOIN meal_entries me ON me.food_id = f.id
                    INNER JOIN meals m ON m.id = me.meal_id
                    WHERE m.user_id = %s
                    ORDER BY m.consumption_date DESC, m.id DESC, f.id DESC
                    """,
                    [user_id],
                )
                columns = [column[0] for column in cursor.description]
                items = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return JsonResponse({"items": items})
        except Exception:
            return _server_error("Nie udało się pobrać produktów i kalorii.")

    if request.method == "POST":
        try:
            data = _read_json(request)
            name = str(data.get("name", "")).strip()
            calories = _number(data.get("calories"), "calories", minimum=0)
            if not name:
                return _error("Podaj nazwę produktu.")

            # W tym uproszczonym formularzu podana wartość oznacza kcal / 100 g.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO meals (user_id, consumption_date, meal_type)
                        VALUES (%s, CURRENT_DATE, 'snack')
                        RETURNING id
                        """,
                        [user_id],
                    )
                    meal_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO foods
                            (name, calories_100g, protein_100g, carbs_100g, fats_100g)
                        VALUES (%s, %s, 0, 0, 0)
                        RETURNING id
                        """,
                        [name, calories],
                    )
                    food_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO meal_entries (meal_id, food_id, weight_grams)
                        VALUES (%s, %s, 100)
                        """,
                        [meal_id, food_id],
                    )
            return JsonResponse({"success": True, "id": food_id}, status=201)
        except ValueError as exc:
            return _error(str(exc))
        except Exception:
            return _server_error("Nie udało się dodać produktu.")

    # DELETE: usuwa wpis użytkownika, nie narusza innych posiłków ani cudzych danych.
    item_id = request.GET.get("id")
    if not item_id:
        try:
            item_id = _read_json(request).get("id")
        except ValueError as exc:
            return _error(str(exc))
    if not item_id:
        return _error("Brak identyfikatora produktu.")

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT me.meal_id
                    FROM meal_entries me
                    INNER JOIN meals m ON m.id = me.meal_id
                    WHERE me.food_id = %s AND m.user_id = %s
                    """,
                    [item_id, user_id],
                )
                meal_ids = [row[0] for row in cursor.fetchall()]
                if not meal_ids:
                    return _error("Nie znaleziono produktu.", status=404)

                cursor.execute(
                    """
                    DELETE FROM meal_entries me
                    USING meals m
                    WHERE me.meal_id = m.id
                      AND me.food_id = %s
                      AND m.user_id = %s
                    """,
                    [item_id, user_id],
                )

                for meal_id in meal_ids:
                    cursor.execute(
                        """
                        DELETE FROM meals m
                        WHERE m.id = %s
                          AND m.user_id = %s
                          AND NOT EXISTS (
                              SELECT 1 FROM meal_entries me WHERE me.meal_id = m.id
                          )
                        """,
                        [meal_id, user_id],
                    )

                cursor.execute(
                    """
                    DELETE FROM foods f
                    WHERE f.id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM meal_entries me WHERE me.food_id = f.id
                      )
                    """,
                    [item_id],
                )
        return JsonResponse({"success": True})
    except Exception:
        return _server_error("Nie udało się usunąć produktu.")


@require_http_methods(["GET", "POST", "DELETE"])
@require_session
def api_meals(request):
    user_id = _session_user_id(request)
    type_mapping = {
        "Śniadanie": "breakfast",
        "Obiad": "lunch",
        "Kolacja": "dinner",
        "Przekąski": "snack",
    }
    reverse_mapping = {value: key for key, value in type_mapping.items()}

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        m.id,
                        COALESCE(food_item.name, '') AS name,
                        COALESCE(food_item.brand, '') AS description,
                        m.meal_type
                    FROM meals m
                    LEFT JOIN LATERAL (
                        SELECT f.name, f.brand
                        FROM meal_entries me
                        INNER JOIN foods f ON f.id = me.food_id
                        WHERE me.meal_id = m.id
                        ORDER BY f.id ASC
                        LIMIT 1
                    ) AS food_item ON TRUE
                    WHERE m.user_id = %s
                    ORDER BY m.consumption_date DESC, m.id DESC
                    """,
                    [user_id],
                )
                rows = cursor.fetchall()
                meals = [
                    {
                        "id": row[0],
                        "name": row[1] or "",
                        "description": row[2] or "",
                        "type": reverse_mapping.get(row[3], "Śniadanie"),
                    }
                    for row in rows
                ]
            return JsonResponse({"meals": meals})
        except Exception:
            return _server_error("Nie udało się pobrać dziennika posiłków.")

    if request.method == "POST":
        try:
            data = _read_json(request)
            name = str(data.get("name", "")).strip()
            description = str(data.get("description") or "").strip()
            ui_type = data.get("type", "Śniadanie")

            if not name:
                return _error("Podaj nazwę posiłku.")
            if ui_type not in type_mapping:
                return _error("Nieprawidłowa kategoria posiłku.")
            db_type = type_mapping[ui_type]

            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO meals (user_id, consumption_date, meal_type)
                        VALUES (%s, CURRENT_DATE, %s)
                        RETURNING id
                        """,
                        [user_id, db_type],
                    )
                    meal_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO foods
                            (name, brand, calories_100g, protein_100g, carbs_100g, fats_100g)
                        VALUES (%s, %s, 0, 0, 0, 0)
                        RETURNING id
                        """,
                        [name, description],
                    )
                    food_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO meal_entries (meal_id, food_id, weight_grams)
                        VALUES (%s, %s, 100)
                        """,
                        [meal_id, food_id],
                    )
            return JsonResponse({"success": True, "id": meal_id}, status=201)
        except ValueError as exc:
            return _error(str(exc))
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
                    """
                    SELECT me.food_id
                    FROM meal_entries me
                    INNER JOIN meals m ON m.id = me.meal_id
                    WHERE m.id = %s AND m.user_id = %s
                    """,
                    [meal_id, user_id],
                )
                food_ids = [row[0] for row in cursor.fetchall()]

                if not food_ids:
                    # Posiłek może istnieć nawet bez wpisów w meal_entries.
                    cursor.execute(
                        "SELECT id FROM meals WHERE id = %s AND user_id = %s",
                        [meal_id, user_id],
                    )
                    if not cursor.fetchone():
                        return _error("Nie znaleziono posiłku.", status=404)

                # Najpierw usuwamy rekordy zależne, dopiero potem rekord posiłku.
                cursor.execute("DELETE FROM meal_entries WHERE meal_id = %s", [meal_id])
                cursor.execute(
                    "DELETE FROM meals WHERE id = %s AND user_id = %s RETURNING id",
                    [meal_id, user_id],
                )
                deleted_meal = cursor.fetchone()
                if not deleted_meal:
                    return _error("Nie znaleziono posiłku.", status=404)

                for food_id in food_ids:
                    cursor.execute(
                        """
                        DELETE FROM foods f
                        WHERE f.id = %s
                          AND NOT EXISTS (
                              SELECT 1 FROM meal_entries me WHERE me.food_id = f.id
                          )
                        """,
                        [food_id],
                    )
        return JsonResponse({"success": True})
    except Exception:
        return _server_error("Nie udało się usunąć posiłku.")


# ---------------------------------------------------------------------------
# Cele makroskładników użytkownika
# ---------------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
@require_session
def api_macros(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT target_protein_g, target_fat_g, target_carbs_g
                    FROM user_profiles
                    WHERE user_id = %s
                    """,
                    [user_id],
                )
                row = cursor.fetchone()
            if not row:
                return JsonResponse({"protein": 0, "fat": 0, "carbs": 0})
            return JsonResponse({
                "protein": row[0] or 0,
                "fat": row[1] or 0,
                "carbs": row[2] or 0,
            })
        except Exception:
            return _server_error("Nie udało się pobrać celów makro.")

    try:
        data = _read_json(request)
        protein = _number(data.get("protein", 0), "protein", minimum=0)
        fat = _number(data.get("fat", 0), "fat", minimum=0)
        carbs = _number(data.get("carbs", 0), "carbs", minimum=0)

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
                        target_carbs_g = EXCLUDED.target_carbs_g
                    """,
                    [user_id, protein, fat, carbs],
                )
        return JsonResponse({"success": True})
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać celów makro.")

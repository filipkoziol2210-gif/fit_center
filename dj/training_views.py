import json
import logging

from django.db import connection, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from .views import _error, _number, _read_json, _server_error, _session_user_id, require_session

logger = logging.getLogger(__name__)


def _ensure_routine_tables():
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_routines (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_routine_exercises (
                id BIGSERIAL PRIMARY KEY,
                routine_id BIGINT NOT NULL REFERENCES training_routines(id) ON DELETE CASCADE,
                exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
                exercise_order INTEGER NOT NULL,
                target_sets INTEGER NOT NULL DEFAULT 3,
                target_reps INTEGER NOT NULL DEFAULT 10,
                UNIQUE (routine_id, exercise_order)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_routines_user
            ON training_routines(user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_routine_exercises_routine
            ON training_routine_exercises(routine_id)
        """)


def _serialize_workout(cursor, workout_row):
    workout_id = workout_row[0]
    cursor.execute("""
        SELECT
            ws.id,
            ws.exercise_id,
            e.name,
            e.target_muscle,
            e.equipment_type,
            ws.set_order,
            ws.reps,
            ws.weight,
            ws.rpe
        FROM workout_sets ws
        INNER JOIN exercises e ON e.id = ws.exercise_id
        WHERE ws.workout_id = %s
        ORDER BY e.name ASC, ws.set_order ASC, ws.id ASC
    """, [workout_id])

    sets = []
    for row in cursor.fetchall():
        sets.append({
            "id": row[0],
            "exercise_id": row[1],
            "exercise_name": row[2],
            "target_muscle": row[3],
            "equipment_type": row[4],
            "set_order": row[5],
            "reps": row[6],
            "weight": float(row[7]) if row[7] is not None else None,
            "rpe": float(row[8]) if row[8] is not None else None,
        })

    exercises = []
    by_exercise = {}
    for item in sets:
        key = item["exercise_id"]
        if key not in by_exercise:
            by_exercise[key] = {
                "exercise_id": key,
                "exercise_name": item["exercise_name"],
                "target_muscle": item["target_muscle"],
                "equipment_type": item["equipment_type"],
                "sets": [],
            }
            exercises.append(by_exercise[key])
        by_exercise[key]["sets"].append(item)

    return {
        "id": workout_row[0],
        "name": workout_row[1],
        "start_time": workout_row[2],
        "end_time": workout_row[3],
        "calories_burned": workout_row[4],
        "notes": workout_row[5],
        "sets": sets,
        "exercises": exercises,
        "total_sets": len(sets),
        "total_volume": round(sum(
            (float(item["weight"]) if item["weight"] is not None else 0) * int(item["reps"])
            for item in sets
        ), 2),
    }


@require_http_methods(["GET", "POST", "DELETE"])
@require_session
def api_workouts(request):
    user_id = _session_user_id(request)

    if request.method == "GET":
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, name, start_time, end_time, calories_burned, notes
                    FROM workouts
                    WHERE user_id = %s
                    ORDER BY start_time DESC, id DESC
                """, [user_id])
                rows = cursor.fetchall()
                workouts = [_serialize_workout(cursor, row) for row in rows]
            return JsonResponse({"workouts": workouts})
        except Exception:
            return _server_error("Nie udało się pobrać historii treningów.")

    if request.method == "DELETE":
        workout_id = request.GET.get("id")
        if not workout_id:
            return _error("Brak identyfikatora treningu.")
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM workouts WHERE id = %s AND user_id = %s",
                        [workout_id, user_id],
                    )
                    if not cursor.fetchone():
                        return _error("Nie znaleziono treningu.", status=404)
                    cursor.execute("DELETE FROM workout_sets WHERE workout_id = %s", [workout_id])
                    cursor.execute(
                        "DELETE FROM workouts WHERE id = %s AND user_id = %s",
                        [workout_id, user_id],
                    )
            return JsonResponse({"success": True})
        except Exception:
            return _server_error("Nie udało się usunąć treningu.")

    try:
        data = _read_json(request)
        name = str(data.get("name") or "").strip()
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        notes = str(data.get("notes") or "").strip()
        calories_burned = _number(
            data.get("calories_burned"),
            "calories_burned",
            optional=True,
            minimum=0,
        )
        raw_sets = data.get("sets", [])
        if not isinstance(raw_sets, list):
            return _error("Pole sets musi być tablicą.")
        if not name:
            return _error("Nazwa treningu jest wymagana.")
        if not start_time or not end_time:
            return _error("Czas rozpoczęcia i zakończenia są wymagane.")
        if not raw_sets:
            return _error("Trening musi zawierać co najmniej jedną serię.")

        clean_sets = []
        seen_exercises = set()

        with connection.cursor() as cursor:
            for index, item in enumerate(raw_sets, start=1):
                try:
                    exercise_id = int(item.get("exercise_id"))
                    reps = int(item.get("reps"))
                    set_order = int(item.get("set_order", index))
                except (TypeError, ValueError):
                    return _error("Ćwiczenie, powtórzenia i numer serii muszą być liczbami.")

                if reps < 1 or set_order < 1:
                    return _error("Powtórzenia i numer serii muszą być dodatnie.")

                weight = _number(item.get("weight"), "weight", optional=True, minimum=0)
                rpe = _number(item.get("rpe"), "rpe", optional=True, minimum=0)
                if rpe is not None and rpe > 10:
                    return _error("RPE musi mieścić się w zakresie 0–10.")

                cursor.execute("SELECT id FROM exercises WHERE id = %s", [exercise_id])
                if not cursor.fetchone():
                    return _error("Wybrane ćwiczenie nie istnieje w bazie.", status=400)

                seen_exercises.add(exercise_id)
                clean_sets.append((exercise_id, set_order, reps, weight, rpe))

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO workouts
                        (user_id, name, start_time, end_time, calories_burned, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, [user_id, name, start_time, end_time, calories_burned, notes])
                workout_id = cursor.fetchone()[0]

                for exercise_id, set_order, reps, weight, rpe in clean_sets:
                    cursor.execute("""
                        INSERT INTO workout_sets
                            (workout_id, exercise_id, set_order, reps, weight, rpe)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, [workout_id, exercise_id, set_order, reps, weight, rpe])

        return JsonResponse({"success": True, "workout_id": workout_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać treningu wraz z seriami.")


@require_GET
@require_session
def api_exercises(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, name, target_muscle, equipment_type
                FROM exercises
                ORDER BY name ASC
            """)
            columns = [column[0] for column in cursor.description]
            exercises = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return JsonResponse({"exercises": exercises})
    except Exception:
        return _server_error("Nie udało się pobrać listy ćwiczeń.")


@require_http_methods(["GET", "POST", "DELETE"])
@require_session
def api_routines(request):
    user_id = _session_user_id(request)

    try:
        _ensure_routine_tables()

        if request.method == "GET":
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT r.id, r.name, r.created_at
                    FROM training_routines r
                    WHERE r.user_id = %s
                    ORDER BY r.created_at DESC, r.id DESC
                """, [user_id])
                routines = []
                for routine_id, name, created_at in cursor.fetchall():
                    cursor.execute("""
                        SELECT
                            re.exercise_id,
                            e.name,
                            e.target_muscle,
                            e.equipment_type,
                            re.exercise_order,
                            re.target_sets,
                            re.target_reps
                        FROM training_routine_exercises re
                        INNER JOIN exercises e ON e.id = re.exercise_id
                        WHERE re.routine_id = %s
                        ORDER BY re.exercise_order ASC
                    """, [routine_id])
                    exercises = [{
                        "exercise_id": row[0],
                        "exercise_name": row[1],
                        "target_muscle": row[2],
                        "equipment_type": row[3],
                        "exercise_order": row[4],
                        "target_sets": row[5],
                        "target_reps": row[6],
                    } for row in cursor.fetchall()]
                    routines.append({
                        "id": routine_id,
                        "name": name,
                        "created_at": created_at,
                        "exercises": exercises,
                    })
            return JsonResponse({"routines": routines})

        if request.method == "DELETE":
            routine_id = request.GET.get("id")
            if not routine_id:
                return _error("Brak identyfikatora rutyny.")
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM training_routines WHERE id = %s AND user_id = %s RETURNING id",
                    [routine_id, user_id],
                )
                if not cursor.fetchone():
                    return _error("Nie znaleziono rutyny.", status=404)
            return JsonResponse({"success": True})

        data = _read_json(request)
        name = str(data.get("name") or "").strip()
        items = data.get("exercises", [])
        if not name:
            return _error("Nazwa rutyny jest wymagana.")
        if not isinstance(items, list) or not items:
            return _error("Rutyna musi zawierać co najmniej jedno ćwiczenie.")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM training_routines WHERE user_id = %s AND name = %s",
                    [user_id, name],
                )
                if cursor.fetchone():
                    return _error("Rutyna o tej nazwie już istnieje.")

                cursor.execute("""
                    INSERT INTO training_routines (user_id, name)
                    VALUES (%s, %s)
                    RETURNING id
                """, [user_id, name])
                routine_id = cursor.fetchone()[0]

                for order, item in enumerate(items, start=1):
                    try:
                        exercise_id = int(item.get("exercise_id"))
                        target_sets = int(item.get("target_sets", 3))
                        target_reps = int(item.get("target_reps", 10))
                    except (TypeError, ValueError):
                        return _error("Parametry rutyny muszą być liczbami.")
                    if target_sets < 1 or target_reps < 1:
                        return _error("Serie i powtórzenia muszą być dodatnie.")

                    cursor.execute(
                        "SELECT id FROM exercises WHERE id = %s",
                        [exercise_id],
                    )
                    if not cursor.fetchone():
                        return _error("Ćwiczenie nie istnieje w bazie.", status=400)

                    cursor.execute("""
                        INSERT INTO training_routine_exercises
                            (routine_id, exercise_id, exercise_order, target_sets, target_reps)
                        VALUES (%s, %s, %s, %s, %s)
                    """, [routine_id, exercise_id, order, target_sets, target_reps])

        return JsonResponse({"success": True, "routine_id": routine_id}, status=201)
    except ValueError as exc:
        return _error(str(exc))
    except Exception:
        return _server_error("Nie udało się zapisać rutyny.")


@require_GET
@require_session
def api_workout_sets(request):
    workout_id = request.GET.get("workout_id")
    if not workout_id:
        return _error("Brak identyfikatora treningu.")
    user_id = _session_user_id(request)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT ws.id, ws.workout_id, ws.exercise_id, e.name,
                       ws.set_order, ws.reps, ws.weight, ws.rpe
                FROM workout_sets ws
                INNER JOIN workouts w ON w.id = ws.workout_id
                INNER JOIN exercises e ON e.id = ws.exercise_id
                WHERE ws.workout_id = %s AND w.user_id = %s
                ORDER BY ws.set_order ASC, ws.id ASC
            """, [workout_id, user_id])
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return JsonResponse({"workout_sets": rows})
    except Exception:
        return _server_error("Nie udało się pobrać serii treningowych.")

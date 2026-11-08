from django.urls import path
from .views import (
    api_users, api_login, api_register,
    api_profile, api_body_measurements,
    api_workouts, api_workout_sets, api_exercises,
    api_calories, api_meals, api_macros
)

urlpatterns = [
    path('api/users/', api_users, name='api_users'),
    path('api/login/', api_login, name='api_login'),
    path('api/register/', api_register, name='api_register'),
    path('api/profile/', api_profile, name='api_profile'),
    path('api/body-measurements/', api_body_measurements, name='api_body_measurements'),
    path('api/workouts/', api_workouts, name='api_workouts'),
    path('api/workout-sets/', api_workout_sets, name='api_workout_sets'),
    path('api/exercises/', api_exercises, name='api_exercises'),
    path('api/calories/', api_calories, name='api_calories'),
    path('api/meals/', api_meals, name='api_meals'),
    path('api/macros/', api_macros, name='api_macros'),
]
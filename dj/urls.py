from django.urls import path

from . import views, diet_views, diet_macro_views

urlpatterns = [
    path("api/csrf/", views.api_csrf, name="api_csrf"),
    path("api/session/", views.api_session, name="api_session"),
    path("api/users/", views.api_users, name="api_users"),
    path("api/register/", views.api_register, name="api_register"),
    path("api/login/", views.api_login, name="api_login"),
    path("api/logout/", views.api_logout, name="api_logout"),
    path("api/profile/", views.api_profile, name="api_profile"),
    path("api/body-measurements/", views.api_body_measurements, name="api_body_measurements"),
    path("api/workouts/", views.api_workouts, name="api_workouts"),
    path("api/workout-sets/", views.api_workout_sets, name="api_workout_sets"),
    path("api/exercises/", views.api_exercises, name="api_exercises"),
    path("api/calories/", diet_views.api_calories, name="api_calories"),
    path("api/meals/", diet_views.api_meals, name="api_meals"),
    path("api/foods/", diet_views.api_foods, name="api_foods"),
    path("api/macros/", diet_macro_views.api_macros, name="api_macros"),
]

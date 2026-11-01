from django.urls import path
from .views import api_users, api_login, api_register

urlpatterns = [
    path('api/users/', api_users, name='api_users'),
    path('api/login/', api_login, name='api_login'),
    path('api/register/', api_register, name='api_register'),
]
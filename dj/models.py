from django.db import models

class User(models.Model):
    email = models.EmailField(unique=True)
    password_hash = models.TextField()
    role = models.CharField(max_length=20, default='user')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'
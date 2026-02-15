from django.urls import path
from . import views

urlpatterns = [
    path('webhook/', views.messenger_webhook, name='messenger_webhook'),
]
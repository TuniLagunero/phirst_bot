from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Change 'admin.site.name' to 'admin.site.urls'
    path('admin/', admin.site.urls),
    path('messenger/', include('bot_engine.urls')),
]
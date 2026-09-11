from django.contrib import admin
from django.urls import path
from myapp.views import DashboardView  # <-- Direct myapp madhun import

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', DashboardView.as_view(), name='dashboard'),
]
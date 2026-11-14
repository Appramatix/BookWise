from django.contrib import admin
from django.urls import path

from reservations import views

admin.site.site_header = "BookWise Admin"
admin.site.site_title = "BookWise Admin"
admin.site.index_title = "Manage rooms, equipment, and reservations"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='dashboard'),
]
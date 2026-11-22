from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from reservations import views

admin.site.site_header = "BookWise Admin"
admin.site.site_title = "BookWise Admin"
admin.site.index_title = "Manage rooms, equipment, and reservations"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('rooms/<int:pk>/', views.resource_detail, name='resource_detail'),
    path('reserve/', views.reserve, name='reserve'),
    path('my-reservations/', views.my_reservations, name='my_reservations'),
    path('reservations/<int:pk>/cancel/', views.cancel_reservation, name='cancel'),
    path('reservations/<int:pk>/check-in/', views.check_in, name='check_in'),
    path('approvals/', views.approvals, name='approvals'),
    path('reservations/<int:pk>/approve/', views.approve_reservation, name='approve'),
    path('reservations/<int:pk>/reject/', views.reject_reservation, name='reject'),
    path('reservations/<int:pk>/staff-cancel/', views.staff_cancel, name='staff_cancel'),
    path('maintenance/', views.maintenance, name='maintenance'),
    path('maintenance/<int:pk>/end/', views.end_maintenance, name='end_maintenance'),
    path('activity-log/', views.activity_log, name='activity_log'),
]
from django.contrib import admin
from .models import Profile, Resource, Reservation, ActivityLog

admin.site.register(Profile)
admin.site.register(Resource)
admin.site.register(Reservation)
admin.site.register(ActivityLog)
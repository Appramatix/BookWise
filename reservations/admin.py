from django.contrib import admin

from .models import ActivityLog, Profile, Reservation, Resource


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role')
    list_filter = ('role',)
    search_fields = ('user__username',)


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'location', 'capacity', 'is_active')
    list_filter = ('type', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name', 'location')


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('resource', 'user', 'start_time', 'end_time', 'status')
    list_filter = ('status', 'resource')
    search_fields = ('user__username', 'resource__name', 'purpose')
    date_hierarchy = 'start_time'
    list_per_page = 20
    actions = ['mark_checked_in', 'mark_completed', 'mark_cancelled']

    @admin.action(description="Mark selected as checked in")
    def mark_checked_in(self, request, queryset):
        queryset.update(status='checked_in')

    @admin.action(description="Mark selected as completed")
    def mark_completed(self, request, queryset):
        queryset.update(status='completed')

    @admin.action(description="Cancel selected reservations")
    def mark_cancelled(self, request, queryset):
        queryset.update(status='cancelled')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        verb = 'Updated' if change else 'Created'
        ActivityLog.objects.create(
            user=request.user,
            reservation=obj,
            action=f"{verb} reservation for {obj.resource}",
        )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action')
    list_filter = ('user',)
    search_fields = ('action',)
    date_hierarchy = 'timestamp'
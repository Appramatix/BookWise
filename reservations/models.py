from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

class Profile(models.Model):
    ROLES = [('admin', 'Admin'), ('staff', 'Staff'), ('borrower', 'Borrower')]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLES, default='borrower')

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Resource(models.Model):
    TYPES = [('room', 'Room'), ('equipment', 'Equipment')]
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=10, choices=TYPES)
    location = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Reservation(models.Model):
    STATUSES = [
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked in'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No-show'),
    ]
    ACTIVE = ['confirmed', 'checked_in']

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='reservations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    purpose = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default='confirmed')
    created_at = models.DateTimeField(auto_now_add=True)

    def conflicts(self):
        """Active reservations for the same resource that overlap this one."""
        return Reservation.objects.filter(
            resource=self.resource,
            status__in=self.ACTIVE,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(pk=self.pk)

    def clean(self):
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError("End time must be after the start time.")
            if self.conflicts().exists():
                raise ValidationError("This resource is already reserved for that time.")

    def __str__(self):
        return f"{self.resource} | {self.start_time:%b %d, %I:%M %p}"


class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
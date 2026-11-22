from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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


class MaintenanceWindow(models.Model):
    """A period when a room or equipment can't be used (repair, redesign, etc.).
    An empty end_time means "until further notice"."""
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='maintenance')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']

    @classmethod
    def overlapping(cls, resource, start, end):
        """Maintenance on this resource that overlaps the period start..end."""
        return cls.objects.filter(resource=resource, start_time__lt=end).filter(
            models.Q(end_time__isnull=True) | models.Q(end_time__gt=start)
        )

    def __str__(self):
        return f"{self.resource} | {self.reason}"


class Reservation(models.Model):
    STATUSES = [
        ('pending', 'Pending'),
        ('confirmed', 'Approved'),
        ('checked_in', 'Checked in'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
        ('no_show', 'No-show'),
    ]
    # Only approved bookings hold a slot. Pending requests never block anyone.
    ACTIVE = ['confirmed', 'checked_in']

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='reservations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    purpose = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default='pending')
    decision_note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def conflicts(self):
        """Approved reservations for the same resource that overlap this one."""
        return Reservation.objects.filter(
            resource=self.resource,
            status__in=self.ACTIVE,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(pk=self.pk)

    def clean(self):
        if self.start_time and self.end_time and self.resource_id:
            if self.end_time <= self.start_time:
                raise ValidationError("End time must be after the start time.")
            if self.status in ('pending', 'confirmed', 'checked_in'):
                if self.conflicts().exists():
                    raise ValidationError("This resource is already reserved for that time.")
                window = MaintenanceWindow.overlapping(
                    self.resource, self.start_time, self.end_time
                ).first()
                if window:
                    since = timezone.localtime(window.start_time)
                    if window.end_time:
                        until = timezone.localtime(window.end_time)
                        period = f"from {since:%b %d, %I:%M %p} to {until:%b %d, %I:%M %p}"
                    else:
                        period = f"from {since:%b %d, %I:%M %p} until further notice"
                    raise ValidationError(
                        f"{self.resource} is under maintenance {period} ({window.reason})."
                    )

    def __str__(self):
        return f"{self.resource} | {self.start_time:%b %d, %I:%M %p}"


class ActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
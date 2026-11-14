from django.shortcuts import render
from django.utils import timezone

from .models import Resource, Reservation


def dashboard(request):
    now = timezone.now()
    cards = []
    for r in Resource.objects.filter(is_active=True):
        current = r.reservations.filter(
            status__in=Reservation.ACTIVE, start_time__lte=now, end_time__gt=now
        ).first()
        if current is None:
            status, icon, label = 'free', '✓', 'Free'
        elif current.status == 'checked_in':
            status, icon, label = 'inuse', '⏱', 'In use'
        else:
            status, icon, label = 'booked', '✕', 'Booked'
        cards.append({'resource': r, 'current': current,
                      'status': status, 'icon': icon, 'label': label})
    return render(request, 'dashboard.html', {'cards': cards, 'now': now})
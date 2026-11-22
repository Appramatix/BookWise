from datetime import timedelta

from django.utils import timezone

from .models import MaintenanceWindow, Reservation


def suggest_slots(resource, start, end, count=3):
    """Return up to `count` free slots of the same length, starting at or after `start`."""
    duration = end - start
    horizon = start + timedelta(days=1)
    limit = horizon + duration
    far_future = start + timedelta(days=3650)  # stands in for "no end date"

    busy = [
        (b.start_time, b.end_time)
        for b in Reservation.objects.filter(
            resource=resource,
            status__in=Reservation.ACTIVE,
            end_time__gt=start,
            start_time__lt=limit,
        )
    ]
    busy += [
        (m.start_time, m.end_time or far_future)
        for m in MaintenanceWindow.overlapping(resource, start, limit)
    ]
    busy.sort()

    slots = []
    candidate = start
    for _ in range(50):
        if len(slots) >= count or candidate > horizon:
            break
        candidate_end = candidate + duration
        clash = next((b for b in busy if b[0] < candidate_end and b[1] > candidate), None)
        if clash:
            candidate = clash[1]
        else:
            slots.append({
                'start': candidate,
                'end': candidate_end,
                'start_value': timezone.localtime(candidate).strftime('%Y-%m-%dT%H:%M'),
                'end_value': timezone.localtime(candidate_end).strftime('%Y-%m-%dT%H:%M'),
            })
            candidate = candidate_end
    return slots
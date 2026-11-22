from datetime import datetime, time, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import MaintenanceForm, ReservationForm
from .models import ActivityLog, MaintenanceWindow, Profile, Reservation, Resource
from .services import suggest_slots

CHECK_IN_WINDOW = timedelta(minutes=15)
OPEN_STATUSES = ['pending', 'confirmed', 'checked_in']
TIMELINE_START_HOUR = 8
TIMELINE_END_HOUR = 18


def log(user, action, reservation=None):
    ActivityLog.objects.create(user=user, action=action, reservation=reservation)


def staff_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def back_to(request, default):
    """Go back to the page the form came from (if it's a safe address), else to `default`."""
    nxt = request.POST.get('next', '')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(default)


def reservations_hit_by(window, statuses):
    """Reservations that overlap a maintenance window (which may have no end date)."""
    qs = Reservation.objects.filter(
        resource=window.resource,
        status__in=statuses,
        end_time__gt=window.start_time,
    )
    if window.end_time:
        qs = qs.filter(start_time__lt=window.end_time)
    return qs


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        Profile.objects.get_or_create(user=user)  # new accounts are borrowers
        login(request, user)
        messages.success(request, f"Welcome to BookWise, {user.username}!")
        return redirect('dashboard')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def dashboard(request):
    now = timezone.now()
    cards = []
    for r in Resource.objects.filter(is_active=True):
        maint = (
            r.maintenance.filter(start_time__lte=now)
            .filter(Q(end_time__isnull=True) | Q(end_time__gt=now))
            .first()
        )
        next_maint = r.maintenance.filter(start_time__gt=now).order_by('start_time').first()
        current = (
            r.reservations.filter(
                status__in=Reservation.ACTIVE, start_time__lte=now, end_time__gt=now
            )
            .select_related('user')
            .first()
        )
        if maint:
            status, icon, label = 'maint', '🔧', 'Under maintenance'
        elif current is None:
            status, icon, label = 'free', '✓', 'Free'
        elif current.status == 'checked_in':
            status, icon, label = 'inuse', '⏱', 'In use'
        else:
            status, icon, label = 'booked', '✕', 'Booked'
        cards.append({
            'resource': r, 'current': current, 'maint': maint, 'next_maint': next_maint,
            'status': status, 'icon': icon, 'label': label,
        })

    pending_count = 0
    if request.user.is_staff:
        pending_count = Reservation.objects.filter(status='pending', end_time__gte=now).count()

    return render(request, 'dashboard.html', {
        'cards': cards, 'now': now, 'pending_count': pending_count,
    })


# ---------- Room page ----------

def hour_label(h):
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


@login_required
def resource_detail(request, pk):
    resource = get_object_or_404(Resource, pk=pk, is_active=True)
    now = timezone.now()
    today = timezone.localdate()
    is_staff = request.user.is_staff

    try:
        day = datetime.strptime(request.GET.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        day = today

    day_start = timezone.make_aware(datetime.combine(day, time.min))
    day_end = day_start + timedelta(days=1)

    # Status right now
    maint_now = (
        resource.maintenance.filter(start_time__lte=now)
        .filter(Q(end_time__isnull=True) | Q(end_time__gt=now))
        .first()
    )
    current = (
        resource.reservations.filter(
            status__in=Reservation.ACTIVE, start_time__lte=now, end_time__gt=now
        )
        .select_related('user')
        .first()
    )
    if maint_now:
        status, icon, label = 'maint', '🔧', 'Under maintenance'
    elif current is None:
        status, icon, label = 'free', '✓', 'Free'
    elif current.status == 'checked_in':
        status, icon, label = 'inuse', '⏱', 'In use'
    else:
        status, icon, label = 'booked', '✕', 'Booked'

    # The chosen day
    bookings = list(
        Reservation.objects.filter(
            resource=resource, status__in=Reservation.ACTIVE,
            start_time__lt=day_end, end_time__gt=day_start,
        ).select_related('user').order_by('start_time')
    )
    windows = list(MaintenanceWindow.overlapping(resource, day_start, day_end))

    pending = []
    if is_staff:
        pending = list(
            Reservation.objects.filter(
                resource=resource, status='pending',
                start_time__lt=day_end, end_time__gt=day_start,
            ).select_related('user').order_by('start_time')
        )
        for p in pending:
            p.blocked_by = p.conflicts().first()

    # Timeline bar
    total = (TIMELINE_END_HOUR - TIMELINE_START_HOUR) * 3600
    tl_start = day_start + timedelta(hours=TIMELINE_START_HOUR)
    tl_end = day_start + timedelta(hours=TIMELINE_END_HOUR)

    def block(start, end, kind, label_text, detail):
        s, e = max(start, tl_start), min(end, tl_end)
        if e <= s:
            return None
        return {
            'left': (s - tl_start).total_seconds() / total * 100,
            'width': (e - s).total_seconds() / total * 100,
            'kind': kind, 'label': label_text, 'detail': detail,
        }

    blocks = []
    for b in bookings:
        item = block(
            b.start_time, b.end_time,
            'inuse' if b.status == 'checked_in' else 'booked',
            b.user.username if is_staff else 'Booked',
            f"{timezone.localtime(b.start_time):%I:%M %p} – {timezone.localtime(b.end_time):%I:%M %p}",
        )
        if item:
            blocks.append(item)
    for w in windows:
        item = block(w.start_time, w.end_time or day_end, 'maint', 'Maintenance', w.reason)
        if item:
            blocks.append(item)

    ticks = [
        {'left': (h - TIMELINE_START_HOUR) / (TIMELINE_END_HOUR - TIMELINE_START_HOUR) * 100,
         'label': hour_label(h)}
        for h in range(TIMELINE_START_HOUR, TIMELINE_END_HOUR + 1, 2)
    ]
    now_pct = None
    if day == today and tl_start <= now <= tl_end:
        now_pct = (now - tl_start).total_seconds() / total * 100

    # Staff-only numbers
    stats = None
    history = []
    if is_staff:
        stats = {
            'last7': Reservation.objects.filter(
                resource=resource, status__in=Reservation.ACTIVE + ['completed'],
                start_time__gte=now - timedelta(days=7), start_time__lte=now,
            ).count(),
            'upcoming': Reservation.objects.filter(
                resource=resource, status__in=Reservation.ACTIVE, start_time__gt=now
            ).count(),
            'pending': Reservation.objects.filter(
                resource=resource, status='pending', end_time__gte=now
            ).count(),
        }
        history = list(resource.maintenance.filter(end_time__lte=now).order_by('-end_time')[:5])

    return render(request, 'resource_detail.html', {
        'resource': resource, 'day': day, 'is_today': day == today,
        'prev_day': (day - timedelta(days=1)).isoformat(),
        'next_day': (day + timedelta(days=1)).isoformat(),
        'today_str': today.isoformat(),
        'status': status, 'icon': icon, 'label': label,
        'maint_now': maint_now, 'current': current,
        'blocks': blocks, 'ticks': ticks, 'now_pct': now_pct,
        'bookings': bookings, 'pending': pending, 'windows': windows,
        'stats': stats, 'history': history,
        'start_label': hour_label(TIMELINE_START_HOUR), 'end_label': hour_label(TIMELINE_END_HOUR),
    })


@login_required
def reserve(request):
    suggestions = []
    conflict_info = None

    if request.method == 'POST':
        form = ReservationForm(request.POST)
        if form.is_valid():
            reservation = form.save(commit=False)
            reservation.user = request.user
            reservation.status = 'pending'
            reservation.save()
            log(request.user, f"Requested {reservation.resource}", reservation)
            messages.success(
                request,
                f"Request sent for {reservation.resource} on "
                f"{timezone.localtime(reservation.start_time):%b %d, %I:%M %p}. "
                f"An admin will review it soon."
            )
            return redirect('my_reservations')

        data = form.cleaned_data
        resource, start, end = data.get('resource'), data.get('start_time'), data.get('end_time')
        if resource and start and end and end > start:
            probe = Reservation(resource=resource, start_time=start, end_time=end)
            clashes = probe.conflicts()
            if clashes.exists():
                first = clashes.order_by('start_time').first()
                conflict_info = (
                    f"{resource} is already approved for someone else from "
                    f"{timezone.localtime(first.start_time):%I:%M %p} to "
                    f"{timezone.localtime(first.end_time):%I:%M %p}."
                )
                suggestions = suggest_slots(resource, start, end)
    else:
        initial = {k: request.GET.get(k) for k in ('resource',) if request.GET.get(k)}
        if request.GET.get('start'):
            initial['start_time'] = request.GET['start']
        if request.GET.get('end'):
            initial['end_time'] = request.GET['end']
        form = ReservationForm(initial=initial)

    return render(request, 'reserve.html', {
        'form': form,
        'suggestions': suggestions,
        'conflict_info': conflict_info,
    })


@login_required
def my_reservations(request):
    now = timezone.now()
    mine = Reservation.objects.filter(user=request.user).select_related('resource')
    upcoming = list(
        mine.filter(status__in=OPEN_STATUSES, end_time__gte=now).order_by('start_time')
    )
    for r in upcoming:
        r.can_check_in = (
            r.status == 'confirmed' and r.start_time - CHECK_IN_WINDOW <= now < r.end_time
        )
    upcoming_ids = [r.pk for r in upcoming]
    past = mine.exclude(pk__in=upcoming_ids).order_by('-start_time')[:30]
    return render(request, 'my_reservations.html', {'upcoming': upcoming, 'past': past})


@login_required
@require_POST
def cancel_reservation(request, pk):
    r = get_object_or_404(Reservation, pk=pk, user=request.user)
    if r.status in ('pending', 'confirmed'):
        was_pending = r.status == 'pending'
        r.status = 'cancelled'
        r.save(update_fields=['status'])
        log(request.user, f"Cancelled {'request' if was_pending else 'reservation'} for {r.resource}", r)
        messages.success(request, "Request cancelled." if was_pending else "Cancelled. The slot is free again.")
    else:
        messages.error(request, "This reservation can't be cancelled anymore.")
    return redirect('my_reservations')


@login_required
@require_POST
def check_in(request, pk):
    r = get_object_or_404(Reservation, pk=pk, user=request.user)
    now = timezone.now()
    if r.status == 'confirmed' and r.start_time - CHECK_IN_WINDOW <= now < r.end_time:
        r.status = 'checked_in'
        r.save(update_fields=['status'])
        log(request.user, f"Checked in to {r.resource}", r)
        messages.success(request, f"Checked in. Enjoy {r.resource}!")
    else:
        messages.error(request, "Check-in opens 15 minutes before the start time.")
    return redirect('my_reservations')


# ---------- Approvals (staff and admin only) ----------

@staff_required
def approvals(request):
    now = timezone.now()
    pending = list(
        Reservation.objects.filter(status='pending', end_time__gte=now)
        .select_related('resource', 'user')
        .order_by('start_time')
    )
    for r in pending:
        r.competing = sum(
            1 for o in pending
            if o.pk != r.pk and o.resource_id == r.resource_id
            and o.start_time < r.end_time and o.end_time > r.start_time
        )
        r.blocked_by = r.conflicts().first()
    return render(request, 'approvals.html', {'pending': pending})


@staff_required
@require_POST
def approve_reservation(request, pk):
    r = get_object_or_404(Reservation, pk=pk)
    if r.status != 'pending':
        messages.error(request, "This request was already handled.")
        return back_to(request, 'approvals')

    clash = r.conflicts().first()
    if clash:
        messages.error(
            request,
            f"Can't approve: {r.resource} is already approved from "
            f"{timezone.localtime(clash.start_time):%I:%M %p} to "
            f"{timezone.localtime(clash.end_time):%I:%M %p}."
        )
        return back_to(request, 'approvals')

    r.status = 'confirmed'
    r.decision_note = ''
    r.save(update_fields=['status', 'decision_note'])
    log(request.user, f"Approved {r.user}'s reservation for {r.resource}", r)

    rivals = Reservation.objects.filter(
        resource=r.resource, status='pending',
        start_time__lt=r.end_time, end_time__gt=r.start_time,
    ).exclude(pk=r.pk)
    declined = 0
    for other in rivals:
        other.status = 'rejected'
        other.decision_note = "Another request for this time was approved."
        other.save(update_fields=['status', 'decision_note'])
        log(request.user, f"Auto-declined {other.user}'s request for {other.resource}", other)
        declined += 1

    extra = f" {declined} competing request{'s' if declined != 1 else ''} declined." if declined else ""
    messages.success(request, f"Approved {r.user}'s request for {r.resource}.{extra}")
    return back_to(request, 'approvals')


@staff_required
@require_POST
def reject_reservation(request, pk):
    r = get_object_or_404(Reservation, pk=pk)
    if r.status != 'pending':
        messages.error(request, "This request was already handled.")
        return back_to(request, 'approvals')

    reason = request.POST.get('reason', '').strip()[:200] or "Declined by admin."
    r.status = 'rejected'
    r.decision_note = reason
    r.save(update_fields=['status', 'decision_note'])
    log(request.user, f"Rejected {r.user}'s request for {r.resource}", r)
    messages.success(request, f"Rejected {r.user}'s request.")
    return back_to(request, 'approvals')


# ---------- Maintenance (staff and admin only) ----------

@staff_required
def maintenance(request):
    now = timezone.now()
    initial = {'start_time': timezone.localtime(now)}
    if request.GET.get('resource'):
        initial['resource'] = request.GET['resource']
    form = MaintenanceForm(request.POST or None, initial=initial)

    if request.method == 'POST' and form.is_valid():
        window = form.save(commit=False)
        window.created_by = request.user
        window.save()
        log(request.user, f"Scheduled maintenance for {window.resource}: {window.reason}")

        declined = 0
        for p in reservations_hit_by(window, ['pending']):
            p.status = 'rejected'
            p.decision_note = f"Unavailable: {window.reason}"[:200]
            p.save(update_fields=['status', 'decision_note'])
            log(request.user, f"Auto-declined {p.user}'s request for {p.resource} (maintenance)", p)
            declined += 1
        approved = reservations_hit_by(window, Reservation.ACTIVE).count()

        messages.success(
            request,
            f"{window.resource} is now unavailable until further notice. "
            f"Mark it as available when the work is done."
        )
        if declined:
            messages.info(request, f"{declined} pending request{'s' if declined != 1 else ''} declined automatically.")
        if approved:
            messages.warning(
                request,
                f"{approved} approved booking{'s' if approved != 1 else ''} overlap this period. "
                f"Review {'them' if approved != 1 else 'it'} below."
            )
        return redirect('maintenance')

    active = []
    open_windows = (
        MaintenanceWindow.objects.select_related('resource')
        .filter(Q(end_time__isnull=True) | Q(end_time__gt=now))
        .order_by('start_time')
    )
    for w in open_windows:
        w.is_current = w.start_time <= now
        w.affected = list(reservations_hit_by(w, Reservation.ACTIVE).select_related('user'))
        active.append(w)
    history = (
        MaintenanceWindow.objects.select_related('resource')
        .filter(end_time__lte=now).order_by('-end_time')[:10]
    )

    return render(request, 'maintenance.html', {'form': form, 'active': active, 'history': history})


@staff_required
@require_POST
def end_maintenance(request, pk):
    w = get_object_or_404(MaintenanceWindow, pk=pk)
    now = timezone.now()
    if w.start_time > now:
        w.delete()
        log(request.user, f"Removed scheduled maintenance for {w.resource}")
        messages.success(request, f"Removed the scheduled maintenance for {w.resource}.")
    elif w.end_time is None or w.end_time > now:
        w.end_time = now
        w.save(update_fields=['end_time'])
        log(request.user, f"Ended maintenance for {w.resource}")
        messages.success(request, f"{w.resource} is available again.")
    return redirect('maintenance')


@staff_required
@require_POST
def staff_cancel(request, pk):
    r = get_object_or_404(Reservation, pk=pk)
    if r.status in ('confirmed', 'checked_in'):
        r.status = 'cancelled'
        r.decision_note = "Cancelled by staff because the resource is unavailable."
        r.save(update_fields=['status', 'decision_note'])
        log(request.user, f"Cancelled {r.user}'s booking for {r.resource}", r)
        messages.success(request, f"Cancelled {r.user}'s booking for {r.resource}.")
    else:
        messages.error(request, "That booking can't be cancelled.")
    return redirect('maintenance')


# ---------- Activity log (staff and admin only) ----------

def log_style(action):
    a = action.lower()
    if a.startswith('approved'):
        return '✅', 'approved'
    if a.startswith(('rejected', 'auto-declined')):
        return '✕', 'rejected'
    if a.startswith('requested'):
        return '📝', 'requested'
    if a.startswith('cancelled'):
        return '🚫', 'cancelled'
    if a.startswith('checked in'):
        return '⏱', 'checkin'
    if a.startswith(('scheduled maintenance', 'ended maintenance', 'removed scheduled')):
        return '🔧', 'maint'
    return '•', 'other'


@staff_required
def activity_log(request):
    period = request.GET.get('period', 'week')
    q = request.GET.get('q', '').strip()
    now = timezone.localtime()

    entries = ActivityLog.objects.select_related('user')
    if period == 'today':
        entries = entries.filter(timestamp__gte=now.replace(hour=0, minute=0, second=0, microsecond=0))
    elif period == 'week':
        entries = entries.filter(timestamp__gte=now - timedelta(days=7))
    if q:
        entries = entries.filter(Q(action__icontains=q) | Q(user__username__icontains=q))

    items = []
    for e in entries[:200]:
        icon, kind = log_style(e.action)
        items.append({'entry': e, 'icon': icon, 'kind': kind})

    return render(request, 'activity_log.html', {'items': items, 'period': period, 'q': q})

# ---------- Room page ----------

TIMELINE_START_HOUR = 8
TIMELINE_END_HOUR = 18


def hour_label(h):
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


@login_required
def resource_detail(request, pk):
    resource = get_object_or_404(Resource, pk=pk, is_active=True)
    now = timezone.now()
    today = timezone.localdate()
    is_staff = request.user.is_staff

    try:
        day = datetime.strptime(request.GET.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        day = today

    day_start = timezone.make_aware(datetime.combine(day, time.min))
    day_end = day_start + timedelta(days=1)

    # Status right now
    maint_now = (
        resource.maintenance.filter(start_time__lte=now)
        .filter(Q(end_time__isnull=True) | Q(end_time__gt=now))
        .first()
    )
    current = (
        resource.reservations.filter(
            status__in=Reservation.ACTIVE, start_time__lte=now, end_time__gt=now
        )
        .select_related('user')
        .first()
    )
    if maint_now:
        status, icon, label = 'maint', '🔧', 'Under maintenance'
    elif current is None:
        status, icon, label = 'free', '✓', 'Free'
    elif current.status == 'checked_in':
        status, icon, label = 'inuse', '⏱', 'In use'
    else:
        status, icon, label = 'booked', '✕', 'Booked'

    # The chosen day
    bookings = list(
        Reservation.objects.filter(
            resource=resource, status__in=Reservation.ACTIVE,
            start_time__lt=day_end, end_time__gt=day_start,
        ).select_related('user').order_by('start_time')
    )
    windows = list(MaintenanceWindow.overlapping(resource, day_start, day_end))

    pending = []
    if is_staff:
        pending = list(
            Reservation.objects.filter(
                resource=resource, status='pending',
                start_time__lt=day_end, end_time__gt=day_start,
            ).select_related('user').order_by('start_time')
        )
        for p in pending:
            p.blocked_by = p.conflicts().first()

    # Timeline bar
    total = (TIMELINE_END_HOUR - TIMELINE_START_HOUR) * 3600
    tl_start = day_start + timedelta(hours=TIMELINE_START_HOUR)
    tl_end = day_start + timedelta(hours=TIMELINE_END_HOUR)

    def block(start, end, kind, label_text, detail):
        s, e = max(start, tl_start), min(end, tl_end)
        if e <= s:
            return None
        return {
            'left': (s - tl_start).total_seconds() / total * 100,
            'width': (e - s).total_seconds() / total * 100,
            'kind': kind, 'label': label_text, 'detail': detail,
        }

    blocks = []
    for b in bookings:
        item = block(
            b.start_time, b.end_time,
            'inuse' if b.status == 'checked_in' else 'booked',
            b.user.username if is_staff else 'Booked',
            f"{timezone.localtime(b.start_time):%I:%M %p} – {timezone.localtime(b.end_time):%I:%M %p}",
        )
        if item:
            blocks.append(item)
    for w in windows:
        item = block(w.start_time, w.end_time or day_end, 'maint', 'Maintenance', w.reason)
        if item:
            blocks.append(item)

    ticks = [
        {'left': (h - TIMELINE_START_HOUR) / (TIMELINE_END_HOUR - TIMELINE_START_HOUR) * 100,
         'label': hour_label(h)}
        for h in range(TIMELINE_START_HOUR, TIMELINE_END_HOUR + 1, 2)
    ]
    now_pct = None
    if day == today and tl_start <= now <= tl_end:
        now_pct = (now - tl_start).total_seconds() / total * 100

    # Staff-only numbers
    stats = None
    history = []
    if is_staff:
        stats = {
            'last7': Reservation.objects.filter(
                resource=resource, status__in=Reservation.ACTIVE + ['completed'],
                start_time__gte=now - timedelta(days=7), start_time__lte=now,
            ).count(),
            'upcoming': Reservation.objects.filter(
                resource=resource, status__in=Reservation.ACTIVE, start_time__gt=now
            ).count(),
            'pending': Reservation.objects.filter(
                resource=resource, status='pending', end_time__gte=now
            ).count(),
        }
        history = list(resource.maintenance.filter(end_time__lte=now).order_by('-end_time')[:5])

    return render(request, 'resource_detail.html', {
        'resource': resource, 'day': day, 'is_today': day == today,
        'prev_day': (day - timedelta(days=1)).isoformat(),
        'next_day': (day + timedelta(days=1)).isoformat(),
        'today_str': today.isoformat(),
        'status': status, 'icon': icon, 'label': label,
        'maint_now': maint_now, 'current': current,
        'blocks': blocks, 'ticks': ticks, 'now_pct': now_pct,
        'bookings': bookings, 'pending': pending, 'windows': windows,
        'stats': stats, 'history': history,
        'start_label': hour_label(TIMELINE_START_HOUR), 'end_label': hour_label(TIMELINE_END_HOUR),
    })
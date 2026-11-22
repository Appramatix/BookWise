from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import MaintenanceWindow, Reservation, Resource

DT_FORMAT = '%Y-%m-%dT%H:%M'


class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ['resource', 'start_time', 'end_time', 'purpose']
        widgets = {
            'start_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DT_FORMAT),
            'end_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DT_FORMAT),
            'purpose': forms.TextInput(attrs={'placeholder': 'e.g. Group study, thesis defense'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['resource'].queryset = Resource.objects.filter(is_active=True)
        self.fields['resource'].empty_label = "Choose a room or equipment"
        for name in ('start_time', 'end_time'):
            self.fields[name].input_formats = [DT_FORMAT]

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        if start and start < timezone.now() - timedelta(minutes=5):
            raise forms.ValidationError("The start time is in the past. Please pick a later time.")
        return cleaned


class MaintenanceForm(forms.ModelForm):
    """No end time: maintenance lasts until staff mark the resource as available."""

    class Meta:
        model = MaintenanceWindow
        fields = ['resource', 'start_time', 'reason']
        labels = {'start_time': 'Unavailable from'}
        widgets = {
            'start_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DT_FORMAT),
            'reason': forms.TextInput(attrs={'placeholder': 'e.g. Aircon repair, repainting'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['resource'].queryset = Resource.objects.filter(is_active=True)
        self.fields['resource'].empty_label = "Choose a room or equipment"
        self.fields['start_time'].input_formats = [DT_FORMAT]
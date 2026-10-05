from django import forms
from django.conf import settings

from . import timeutils
from .models import Event
from .services import process_cover
from storage import get_storage


class EventForm(forms.ModelForm):
    expires_on = forms.DateField(
        required=False, label="Photos can be shared until the end of",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    pin = forms.CharField(
        required=False, label="Viewing PIN (optional)", min_length=4, max_length=8,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "inputmode": "numeric"}),
        help_text="4 to 8 digits. Guests must enter it to see the gallery. Leave blank to keep the current setting.")
    clear_pin = forms.BooleanField(required=False, label="Remove the viewing PIN")
    cover = forms.FileField(required=False, label="Cover image (JPG, PNG or WEBP, up to 10 MB)",
                            widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))

    class Meta:
        model = Event
        fields = ("name", "event_type", "event_date", "location", "description",
                  "allow_uploads", "allow_downloads", "moderation_enabled",
                  "max_upload_size_mb", "max_photos_per_upload")
        widgets = {"event_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "description": forms.Textarea(attrs={"rows": 3})}

    field_order = ("name", "event_type", "event_date", "expires_on", "location", "description", "cover",
                   "allow_uploads", "allow_downloads", "moderation_enabled",
                   "max_upload_size_mb", "max_photos_per_upload", "pin", "clear_pin")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cover_bytes = None
        self._orig_expires = self.instance.expires_at if self.instance.pk else None
        self.fields["expires_on"].help_text = (
            f"Leave blank to expire {settings.DEFAULT_EVENT_EXPIRY_DAYS} days after the event date.")
        # UUID primary keys are assigned at instantiation, so pk is set before the row exists.
        if self.instance._state.adding:
            self.fields["clear_pin"].widget = forms.HiddenInput()
        elif self.instance.expires_at:
            self.fields["expires_on"].initial = timeutils.local_date(self.instance.expires_at)

    def clean_pin(self):
        pin = self.cleaned_data.get("pin", "")
        if pin and not pin.isdigit():
            raise forms.ValidationError("The PIN must contain digits only.")
        return pin

    def clean_cover(self):
        f = self.cleaned_data.get("cover")
        if f and hasattr(f, "read"):
            try:
                self._cover_bytes = process_cover(f)
            except ValueError as exc:
                raise forms.ValidationError(str(exc))
        return f

    def clean(self):
        data = super().clean()
        event_date = data.get("event_date")
        if not event_date:
            return data
        expires_on = data.get("expires_on")
        if expires_on and expires_on < event_date:
            self.add_error("expires_on", "The expiry date cannot be before the event date.")
            return data
        expires_at = timeutils.end_of_day(expires_on) if expires_on else timeutils.default_expires_at(event_date)
        if timeutils.local_date(expires_at) < timeutils.local_today():
            self.add_error("expires_on", "The expiry date must not be in the past.")
        self._expires_at = expires_at
        return data

    def save(self, owner=None):
        event = super().save(commit=False)
        if owner is not None:
            event.owner = owner
        event.expires_at = self._expires_at
        if self._orig_expires and self._orig_expires != event.expires_at:
            event.warned_thresholds = ""
            event.expiry_marked_at = None
        if self.cleaned_data.get("clear_pin"):
            event.clear_pin()
        if self.cleaned_data.get("pin"):
            event.set_pin(self.cleaned_data["pin"])
        if self._cover_bytes:
            event.cover_image = f"events/{event.id}/cover.jpg"
            get_storage().put(event.cover_image, self._cover_bytes, "image/jpeg")
        event.save()
        return event

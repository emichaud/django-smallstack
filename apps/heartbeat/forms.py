"""Forms for the heartbeat app."""

from django import forms


class SLAForm(forms.Form):
    """Form for resetting the SLA epoch and configuring targets."""

    started_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={
            "type": "datetime-local",
            "class": "vTextField",
        }),
        help_text="Start tracking uptime from this date/time.",
    )
    service_target = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        initial=99.9,
        widget=forms.NumberInput(attrs={
            "class": "vTextField",
            "step": "0.01",
        }),
        help_text="Internal goal (e.g. 99.9%)",
    )
    service_minimum = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        initial=99.5,
        widget=forms.NumberInput(attrs={
            "class": "vTextField",
            "step": "0.01",
        }),
        help_text="Public threshold (e.g. 99.5%)",
    )
    note = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "vTextField",
            "placeholder": "e.g. After server migration",
        }),
        help_text="Optional note for this reset.",
    )

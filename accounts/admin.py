from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django import forms

from .models import User, PasswordResetToken, EmailVerificationToken


class UserChangeForm(forms.ModelForm):
    """Expose the hashed password as read-only so saves don't rehash it."""

    password = ReadOnlyPasswordHashField()

    class Meta:
        model = User
        fields = "__all__"


class UserCreationForm(forms.ModelForm):
    """Create a new user with a validated password."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm

    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "is_superuser", "can_author", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser", "can_author", "phone_verified")
    search_fields = ("email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone", "avatar_url")}),
        ("Identity providers", {"fields": ("google_id", "facebook_id", "ghl_contact_id", "phone_verified")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "can_author", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "password1", "password2"),
        }),
    )


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at")
    list_filter = ("used_at",)
    search_fields = ("user__email",)
    readonly_fields = [f.name for f in PasswordResetToken._meta.fields]


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at")
    search_fields = ("user__email",)
    readonly_fields = [f.name for f in EmailVerificationToken._meta.fields]

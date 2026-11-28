# admin.py
import mimetypes
import uuid
from urllib.parse import urlparse

from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from .services.precon_assets import (
    precon_asset_storage_configured,
    upload_precon_asset,
)
from .models import (
    AccessToken,
    Agent,
    AgentServiceArea,
    AIAssistLog,
    Attachment,
    Author,
    CensusFSA,
    CommunityListing,
    Content,
    ContentMeta,
    EstateAmenity,
    EstateContentSection,
    EstateDepositInstallment,
    EstateDepositPlan,
    EstateDocument,
    EstateDocumentIntent,
    EstateIncentive,
    EstatePrice,
    EstateProject,
    EstateProperty,
    EstatePropertyImage,
    EstateSourceSnapshot,
    EstateUnitType,
    ListingFirstSeen,
    ListingSubmission,
    ListingSubmissionMedia,
    ListingSyncStatus,
    ListingViewEvent,
    MapAggregateCell,
    Media,
    NewsletterDelivery,
    OpenHouse,
    PreComFloorPlanIntent,
    PreComProperty,
    PreconActivityEvent,
    Property,
    PropertyEmbedding,
    PropertyInquiry,
    PropertyNote,
    PropertySnapshot,
    PropertySoldProxy,
    Room,
    SavedSearch,
    SearchEvent,
    Taxonomy,
    UserAlertPreference,
    UserFavorite,
    UserFeedback,
    UserFollowedArea,
    UserHistory,
    UserPropertyInteraction,
    UserToured,
    WebPushSubscription,
)
from .admin_ui import SectionedAdminMixin


def infer_attachment_mime_type(url):
    """Return a sensible MIME type for an externally-hosted attachment URL.

    Attachments are links rather than uploaded files, so the URL extension is
    the only reliable information available without downloading remote content.
    Unknown links (including many Google Drive share links) are deliberately
    kept as generic documents; the frontend can still open them normally.
    """
    path = urlparse(url or "").path
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type or "application/octet-stream"


PRECON_META_KEY_GUIDE = (
    ("developer", "Builder or developer name", "Empire Communities"),
    ("city", "City (after address)", "Vaughan"),
    ("neighbourhood", "Neighbourhood / community", "VMC"),
    ("province", "Province / state", "ON"),
    ("location_display", "Location label shown to visitors", "Vaughan Metropolitan Centre"),
    ("occupancy_year", "Estimated occupancy / completion year", "2028"),
    ("ownership_type", "Freehold, condominium, or other", "Freehold"),
    ("property_types", "Comma-separated home types", "Townhomes, Detached Homes"),
    ("stories", "Number of stories", "3"),
    ("basement", "Basement finish / type", "Finished"),
    ("maintenance_fees", "Monthly maintenance fees where applicable", "$450/mo"),
    ("signing_amount", "Amount due on signing", "$5,000"),
    ("price_display", "Marketing price shown to visitors", "From $699,900"),
    ("bedrooms_min", "Lowest bedroom count", "2"),
    ("bedrooms_max", "Highest bedroom count", "4"),
    ("bathrooms_min", "Lowest bathroom count", "2"),
    ("bathrooms_max", "Highest bathroom count", "3"),
    ("area_min", "Smallest interior area", "1200"),
    ("area_max", "Largest interior area", "2400"),
    ("area_unit", "Unit shown beside area", "sq. ft."),
    ("garage_count", "Garage spaces", "1"),
    ("incentives", "Benefits separated with |", "$10,000 décor credit|Free assignment"),
    ("amenities", "Amenities separated with |", "Parks nearby|Minutes to GO"),
    ("floor_plan_url", "External floor-plan link", "https://example.com/floor-plans.pdf"),
    ("deposit_structure", "Simple deposit steps separated with ;", "$10K on signing;$10K in 30 days"),
    ("deposit_plans_json", "Detailed deposit plan (JSON)", '[{"title":"Standard deposit","installments":[{"milestone":"On signing","amount":"$10,000"}]}]'),
    ("community_highlights_json", "Community highlights (JSON list)", '["Parks and trails","Near transit"]'),
    ("interior_features_json", "Interior features (JSON list)", '["9 ft ceilings","Quartz counters"]'),
    ("exterior_features_json", "Exterior features (JSON list)", '["Private balcony","Brick exterior"]'),
    ("nearby_places_json", "Nearby places (JSON list)", '[{"name":"GO Station","category":"Transit","travel_time":"10 min"}]'),
    ("buyer_information_json", "Buyer information (JSON list)", '[{"label":"Assignment","value":"Permitted"}]'),
    ("home_collections_json", "Home collections (JSON list)", '[{"name":"The Aspen","home_type":"Townhome","bedrooms":"3","bathrooms":"2.5","area":"1,800 sq. ft.","starting_price":"From $799,900"}]'),
    ("purchase_notes_json", "Purchase notes (JSON list)", '["Prices and availability are subject to change."]'),
    ("seo_title", "Browser/SEO page title", "Example Townhomes | Estate-4u"),
)


class PreConMetaKeyInput(forms.TextInput):
    """Text input with suggestions, without blocking imported/custom metadata."""

    def render(self, name, value, attrs=None, renderer=None):
        input_id = (attrs or {}).get("id") or name.replace("-", "_")
        suggestion_id = f"{input_id}-precon-meta-key-suggestions"
        attrs = {
            **(attrs or {}),
            "list": suggestion_id,
            "data-precon-meta-key": "true",
        }
        input_html = super().render(name, value, attrs, renderer)
        options = format_html_join(
            "",
            '<option value="{}" label="{} — {}"></option>',
            ((key, label, example) for key, label, example in PRECON_META_KEY_GUIDE),
        )
        return format_html(
            '{}<datalist id="{}">{}</datalist>',
            input_html,
            suggestion_id,
            options,
        )


class ContentMetaAdminForm(forms.ModelForm):
    """Document the metadata contract used by the public pre-con project page."""

    class Meta:
        model = ContentMeta
        fields = "__all__"
        widgets = {
            "key": PreConMetaKeyInput(attrs={"placeholder": "Choose or type a field name"}),
            "value": forms.Textarea(attrs={"class": "precon-meta-value", "placeholder": "Choose a key to see its expected value"}),
        }
        help_texts = {
            "key": "Choose a suggested PreCon field, or type a custom/legacy key.",
            "value": "Examples and JSON formats are shown when a suggested key is selected.",
        }

    class Media:
        js = ("admin/js/precon-meta-guide.js",)


def precon_meta_guide_html():
    rows = format_html_join(
        "",
        "<tr><td><code>{}</code></td><td>{}</td><td><code>{}</code></td></tr>",
        PRECON_META_KEY_GUIDE,
    )
    return format_html(
        "<details open><summary><strong>PreCon project fields</strong> — select a key below; custom keys remain supported.</summary>"
        "<table><thead><tr><th>Key</th><th>Shown as</th><th>Example value</th></tr></thead>"
        "<tbody>{}</tbody></table></details>",
        rows,
    )


class PreConAssetFileInput(forms.ClearableFileInput):
    """A file input that also accepts files dropped onto it in Django admin."""

    class Media:
        css = {"all": ("admin/css/precon-asset-upload.css",)}
        js = ("admin/js/precon-asset-upload.js",)


class AttachmentAdminForm(forms.ModelForm):
    """Accept a pasted link or upload a Cloudinary-hosted pre-con asset."""

    upload = forms.FileField(
        required=False,
        label="Upload to Cloudinary",
        widget=PreConAssetFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp,image/gif,application/pdf",
                "class": "precon-asset-upload",
            }
        ),
        help_text="Drag an image or PDF here, or click to choose a file. Uploaded files are stored in Cloudinary.",
    )

    class Meta:
        model = Attachment
        fields = "__all__"
        widgets = {
            "mime_type": forms.TextInput(
                attrs={
                    "placeholder": "Detected automatically when blank",
                }
            ),
        }
        help_texts = {
            "url": "Paste an external asset or floor-plan link. Leave blank when uploading a file above.",
            "mime_type": (
                "Leave blank to detect from the link (for example image/jpeg or "
                "application/pdf). Enter a value only to override detection. "
                "Google Drive and extensionless links are saved as generic documents."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["url"].required = False
        self.fields["mime_type"].required = False
        self._uploaded_asset_url = None

    @staticmethod
    def _validate_upload(upload):
        max_bytes = settings.PRECON_ASSET_MAX_UPLOAD_MB * 1024 * 1024
        if upload.size > max_bytes:
            raise ValidationError(
                f"Files must be {settings.PRECON_ASSET_MAX_UPLOAD_MB} MB or smaller."
            )

        supplied_type = str(getattr(upload, "content_type", "") or "").lower()
        inferred_type = infer_attachment_mime_type(getattr(upload, "name", ""))
        mime_type = supplied_type if supplied_type.startswith("image/") or supplied_type == "application/pdf" else inferred_type
        if not (mime_type.startswith("image/") or mime_type == "application/pdf"):
            raise ValidationError("Upload a JPEG, PNG, WebP, GIF, or PDF file.")
        return mime_type

    def clean(self):
        cleaned_data = super().clean()
        upload = cleaned_data.get("upload")
        url = cleaned_data.get("url")

        if not upload and not url and not self.instance.url:
            raise ValidationError("Provide an external URL or upload an image or PDF.")

        if upload:
            if not precon_asset_storage_configured():
                self.add_error(
                    "upload",
                    "Cloudinary must be configured before uploading project assets. "
                    "Set CLOUDINARY_URL (or cloud name + API key + secret) in the "
                    "server environment or the admin Integrations console.",
                )
                return cleaned_data
            try:
                mime_type = self._validate_upload(upload)
            except ValidationError as exc:
                self.add_error("upload", exc.messages[0] if exc.messages else exc)
                return cleaned_data
            try:
                self._uploaded_asset_url = upload_precon_asset(
                    upload,
                    folder=f"precon/{self.instance.content_id or 'uploads'}",
                )
            except CloudinaryError:
                self.add_error("upload", "Cloudinary could not store this file. Please try again.")
                return cleaned_data
            except RuntimeError:
                self.add_error(
                    "upload",
                    "Cloudinary must be configured before uploading project assets.",
                )
                return cleaned_data
            cleaned_data["url"] = self._uploaded_asset_url
            cleaned_data["mime_type"] = mime_type

        if not cleaned_data.get("mime_type"):
            cleaned_data["mime_type"] = infer_attachment_mime_type(
                cleaned_data.get("url") or self.instance.url
            )
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self._uploaded_asset_url:
            instance.url = self._uploaded_asset_url
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0
    show_change_link = True
    classes = ("collapse",)
    ordering = ("room_type",)
    fields = (
        "room_type",
        "room_level",
        "room_length",
        "room_width",
        "room_dimensions",
        "room_description",
        "room_length_width_units",
    )

class MediaInline(admin.TabularInline):
    model = Media
    extra = 0
    show_change_link = True
    classes = ("collapse",)
    ordering = ("order", "id")
    fields = (
        "order",
        "is_preferred",
        "media_category",
        "media_url",
        "media_file",
    )

@admin.register(Property)
class PropertyAdmin(SectionedAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/mls/property_change_list.html"
    list_display = (
        'listing_key',
        'category_type',
        'is_featured',
        'featured_order',
        'is_high_return',
        'high_return_order',
        'list_price',
        'property_sub_type',
        'city',
        'state_or_province',
    )
    list_filter = ('category_type', 'is_featured', 'is_high_return', 'city', 'state_or_province')
    list_editable = ('is_featured', 'featured_order', 'is_high_return', 'high_return_order')
    search_fields = ('listing_key', 'city', 'street_name', 'public_remarks')
    inlines = [RoomInline, MediaInline]
    fieldsets = (
        (
            "Listing Core",
            {
                "fields": (
                    "listing_key",
                    "listing_id",
                    "category_type",
                    "property_sub_type",
                    "standard_status",
                    "is_featured",
                    "featured_order",
                    "featured_until",
                    "is_high_return",
                    "high_return_order",
                    "high_return_until",
                    "is_manual",
                )
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    "list_price",
                    "lease_amount",
                    "lease_amount_frequency",
                    "price_per_unit",
                    "lease_per_unit",
                    "association_fee",
                    "tax_annual_amount",
                )
            },
        ),
        (
            "Location",
            {
                "fields": (
                    "country",
                    "state_or_province",
                    "city",
                    "postal_code",
                    "street_name",
                    "street_number",
                    "latitude",
                    "longitude",
                    "directions",
                )
            },
        ),
        (
            "Property Specs",
            {
                "fields": (
                    "bedrooms_total",
                    "bathrooms_total_integer",
                    "living_area",
                    "year_built",
                    "stories",
                    "parking_total",
                )
            },
        ),
        (
            "Interior Features",
            {
                "fields": (
                    "appliances",
                    "cooling",
                    "heating",
                    "flooring",
                    "basement",
                    "fireplace_features",
                )
            },
        ),
        (
            "Exterior Features",
            {
                "fields": (
                    "roof",
                    "construction_materials",
                    "exterior_features",
                    "pool_features",
                    "waterfront_features",
                )
            },
        ),
        (
            "Lot / Land",
            {
                "classes": ("collapse",),
                "fields": (
                    "lot_size_area",
                    "lot_size_dimensions",
                    "zoning",
                    "frontage_length_numeric",
                )
            },
        ),
        (
            "Commercial",
            {
                "classes": ("collapse",),
                "fields": (
                    "business_type",
                    "current_use",
                    "possible_use",
                    "anchors_co_tenants",
                )
            },
        ),
        (
            "Media & AI",
            {
                "classes": ("collapse",),
                "fields": (
                    "photos_count",
                    "listing_url",
                    "ai_summary_markdown",
                )
            },
        ),
        (
            "System / Sync Metadata",
            {
                "classes": ("collapse",),
                "fields": (
                    "origin_system_name",
                    "photos_change_timestamp",
                    "ai_summary_payload_hash",
                    "modification_timestamp",
                ),
            },
        ),
    )
    ordering = ('-is_featured', 'listing_key')
    actions = ('delete_selected_properties',)

    @admin.action(description="Delete selected properties", permissions=["delete"])
    def delete_selected_properties(self, request, queryset):
        deleted_count, _ = queryset.delete()
        self.message_user(request, f"Deleted {deleted_count} property records.")

class RoomAdmin(SectionedAdminMixin, admin.ModelAdmin):
    list_display = ('property_display', 'room_type', 'room_length', 'room_width', 'room_level', 'room_dimensions')
    list_filter = ('room_level', 'room_length_width_units')
    search_fields = ('room_type', 'room_level', 'room_description', 'property__listing_key', 'property__city')
    autocomplete_fields = ('property',)
    list_select_related = ('property',)
    ordering = ('property', 'room_type')

    @admin.display(description="Property", ordering="property__listing_key")
    def property_display(self, obj):
        return f"{obj.property.listing_key} · {obj.property.city or ''}"

class MediaAdmin(SectionedAdminMixin, admin.ModelAdmin):
    list_display = ('property_display', 'media_url', 'media_category', 'order', 'is_preferred')
    list_filter = ('is_preferred', 'media_category')
    search_fields = ('media_category', 'media_url', 'property__listing_key', 'property__city')
    autocomplete_fields = ('property',)
    list_select_related = ('property',)
    list_editable = ('order', 'is_preferred')
    ordering = ('property', 'order', 'id')

    @admin.display(description="Property", ordering="property__listing_key")
    def property_display(self, obj):
        return f"{obj.property.listing_key} · {obj.property.city or ''}"

class UserFeedbackAdmin(SectionedAdminMixin, admin.ModelAdmin):
    list_display = ("feedback_type", "status", "email", "name", "page_url", "created_at")
    list_filter = ("feedback_type", "status", "created_at")
    list_editable = ("status",)
    search_fields = ("name", "email", "message", "page_url")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)


@admin.register(PropertyInquiry)
class PropertyInquiryAdmin(SectionedAdminMixin, admin.ModelAdmin):
    list_display = (
        "created_at",
        "first_name",
        "last_name",
        "email",
        "intent",
        "status",
        "user_display",
        "project_display",
        "is_vip_list",
        "newsletter_opt_in",
        "ghl_synced_at",
        "email_sent_at",
    )
    list_filter = ("status", "intent", "is_vip_list", "newsletter_opt_in", "created_at", "ghl_synced_at")
    list_editable = ("status",)
    search_fields = (
        "first_name",
        "last_name",
        "email",
        "phone",
        "message",
        "preferred_locations",
        "listing_key",
        "user__email",
        "user__first_name",
        "user__last_name",
        "project__title",
        "project__developer",
    )
    autocomplete_fields = ("project",)
    list_select_related = ("user", "project")
    date_hierarchy = "created_at"

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title if obj.project_id else "—"
    readonly_fields = (
        "created_at",
        "updated_at",
        "ghl_contact_id",
        "ghl_synced_at",
        "email_sent_at",
        "last_error",
        "user",
        "ip_address",
        "user_agent",
    )
    fieldsets = (
        ("Contact", {"fields": ("user", "first_name", "last_name", "email", "phone")}),
        (
            "Inquiry",
            {
                "fields": (
                    "intent",
                    "message",
                    "preferred_locations",
                    "property_types",
                    "budget_min",
                    "budget_max",   
                    "bedrooms_min",
                    "bathrooms_min",
                    "timeline",
                    "page_url",
                )
            },
        ),
        ("Workflow", {"fields": ("status",)}),
        (
            "Delivery",
            {
                "fields": (
                    "ghl_contact_id",
                    "ghl_synced_at",
                    "email_sent_at",
                    "last_error",
                )
            },
        ),
        ("Visitor", {"classes": ("collapse",), "fields": ("ip_address", "user_agent")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )



admin.site.register(Room, RoomAdmin)
admin.site.register(Media, MediaAdmin)
admin.site.register(UserFeedback, UserFeedbackAdmin)


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("wp_id", "login", "display_name", "email")
    search_fields = ("login", "display_name", "email", "first_name", "last_name")
    ordering = ("display_name",)


@admin.register(Taxonomy)
class TaxonomyAdmin(admin.ModelAdmin):
    list_display = ("wp_id", "taxonomy", "name", "slug", "parent")
    list_filter = ("taxonomy",)
    search_fields = ("name", "slug")
    ordering = ("taxonomy", "name")


class ContentMetaInline(admin.TabularInline):
    model = ContentMeta
    form = ContentMetaAdminForm
    extra = 1
    fields = ("key", "value")
    verbose_name = "Project detail"
    verbose_name_plural = "Project details (metadata)"


class AttachmentInline(admin.TabularInline):
    model = Attachment
    form = AttachmentAdminForm
    extra = 1
    fields = ("title", "upload", "url", "mime_type")


class PreComPropertyInline(admin.StackedInline):
    """Keep a pre-con project's structured fields beside its content."""

    model = PreComProperty
    extra = 0
    max_num = 1
    fields = (
        "price",
        "bedrooms",
        "bathrooms",
        "garages",
        "area",
        "lot_size",
        "address",
        "latitude",
        "longitude",
        "sales_stage",
        "is_featured",
        "featured_order",
    )
    verbose_name = "Pre-construction project details"
    verbose_name_plural = "Pre-construction project details"


@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    list_display = ("wp_id", "content_type", "title", "slug", "status", "published_at", "author", "project_details_link")
    list_filter = ("content_type", "status")
    search_fields = ("title", "slug", "wp_id")
    autocomplete_fields = ("author",)
    filter_horizontal = ("taxonomies",)
    prepopulated_fields = {"slug": ("title",)}
    inlines = [PreComPropertyInline, ContentMetaInline, AttachmentInline]
    list_select_related = ("property", "author")
    ordering = ("-published_at", "-id")
    fieldsets = (
        ("Content", {
            "fields": (
                "wp_id",
                "content_type",
                "title",
                "slug",
                "status",
                "published_at",
                "author",
                "taxonomies",
            )
        }),
        ("Writing", {"fields": ("content", "excerpt")}),
    )

    class Media:
        # Ensure attachment upload styling/JS loads on the Content change form
        # (inlines alone do not always pull widget Media in every admin skin).
        css = {"all": ("admin/css/precon-asset-upload.css",)}
        js = ("admin/js/precon-asset-upload.js",)

    def save_related(self, request, form, formsets, change):
        """Warn editors when a published project cannot reach the public list."""
        super().save_related(request, form, formsets, change)
        content = form.instance
        if (
            content.content_type == Content.PROPERTY
            and content.status == Content.PUBLISH
            and not PreComProperty.objects.filter(content=content).exists()
        ):
            messages.warning(
                request,
                "This Property is published but has no Pre-construction project "
                "details. It will not appear on the public PreCon listings page "
                "until those details are added.",
            )

    @admin.display(description="Project details")
    def project_details_link(self, obj):
        if obj.content_type != Content.PROPERTY:
            return "—"
        try:
            property_id = obj.property.id
        except PreComProperty.DoesNotExist:
            return "Add below"
        return format_html(
            '<a class="button" href="../precomproperty/{}/change/">Edit project details</a>',
            property_id,
        )


@admin.register(ContentMeta)
class ContentMetaAdmin(admin.ModelAdmin):
    form = ContentMetaAdminForm
    list_display = ("content_display", "key", "value_preview")
    list_filter = ("key", "content__content_type", "content__status")
    search_fields = ("key", "value", "content__title", "content__slug", "content__wp_id")
    autocomplete_fields = ("content",)
    list_select_related = ("content",)
    ordering = ("content", "key")
    fieldsets = (
        (
            "Pre-construction project field guide",
            {"description": precon_meta_guide_html(), "fields": ("content", "key", "value")},
        ),
    )

    @admin.display(description="Content", ordering="content__title")
    def content_display(self, obj):
        return f"{obj.content.title} ({obj.content.content_type})"

    @admin.display(description="Value")
    def value_preview(self, obj):
        return (obj.value or "")[:120]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    form = AttachmentAdminForm
    fields = ("content", "title", "upload", "url", "mime_type")
    list_display = ("content_display", "title", "mime_type", "url")
    list_filter = ("mime_type", "content__content_type", "content__status")
    search_fields = ("url", "title", "mime_type", "content__title", "content__slug", "content__wp_id")
    autocomplete_fields = ("content",)
    list_select_related = ("content",)
    ordering = ("content", "id")

    @admin.display(description="Content", ordering="content__title")
    def content_display(self, obj):
        return f"{obj.content.title} ({obj.content.content_type})"


@admin.register(PreComProperty)
class PreComPropertyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "content",
        "price",
        "bedrooms",
        "bathrooms",
        "area",
        "latitude",
        "longitude",
        "sales_stage",
        "is_featured",
        "featured_order",
    )
    list_editable = ("is_featured", "featured_order")
    list_filter = ("is_featured", "sales_stage")
    search_fields = ("content__title", "content__slug", "content__wp_id", "address")
    autocomplete_fields = ("content",)
    list_select_related = ("content",)
    ordering = ("-id",)


@admin.register(PreComFloorPlanIntent)
class PreComFloorPlanIntentAdmin(admin.ModelAdmin):
    """Read-only agent view of high-intent floor-plan requests."""

    list_display = ("created_at", "project", "user", "phone", "source_url")
    list_filter = ("created_at",)
    search_fields = (
        "property__content__title",
        "property__content__slug",
        "user__email",
        "user__name",
        "user__phone",
    )
    list_select_related = ("property__content", "user")
    readonly_fields = ("property", "user", "source_url", "created_at")
    ordering = ("-created_at",)

    @admin.display(description="Project", ordering="property__content__title")
    def project(self, obj):
        return obj.property.content.title

    @admin.display(description="Phone", ordering="user__phone")
    def phone(self, obj):
        return obj.user.phone or "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")




@admin.register(EstateProperty)
class EstatePropertyAdmin(admin.ModelAdmin):
    list_display = (
        "listing_key",
        "property_title",
        "publish_status",
        "city",
        "list_price",
        "is_featured",
    )

    list_filter = (
        "publish_status",
        "is_featured",
        "city",
        "standard_status",
    )

    search_fields = (
        "listing_key",
        "listing_id",
        "property_title",
        "property_slug",
        "city",
        "unparsed_address",
    )

    readonly_fields = (
        "id",
        "listing_key",
        "modification_timestamp",
    )

    ordering = (
        "-modification_timestamp",
    )


class ListingSubmissionMediaInline(admin.TabularInline):
    model = ListingSubmissionMedia
    extra = 0
    readonly_fields = ("uploaded_at",)
    fields = ("media_type", "file", "display_order", "uploaded_at")


@admin.register(ListingSubmission)
class ListingSubmissionAdmin(admin.ModelAdmin):
    """Review submissions here before exposing any owner listing publicly."""

    inlines = (ListingSubmissionMediaInline,)
    list_display = (
        "id", "address_line_1", "city", "purpose", "project_name", "submitter_type", "status",
        "asking_price", "submitted_at", "reviewed_at",
    )
    list_filter = ("status", "purpose", "submitter_type", "province")
    search_fields = (
        "address_line_1", "address_line_2", "city", "postal_code", "project_name", "builder_name",
        "contact_name", "contact_email", "submitted_by__email",
    )
    readonly_fields = (
        "submitted_by", "submitted_at", "created_at", "updated_at", "reviewed_at",
        "submitted_ip", "submitted_user_agent",
    )
    # PreComProperty has thousands of rows; a raw id avoids a giant <select>.
    raw_id_fields = ("precon_property",)
    fieldsets = (
        ("Submission", {"fields": ("submitted_by", "submitter_type", "purpose", "status", "submitted_at", "submitted_ip", "submitted_user_agent", "created_at", "updated_at")}),
        ("Property", {"fields": (
            "address_line_1", "address_line_2", "city", "province", "postal_code", "country",
            "property_type", "ownership_title", "bedrooms", "bathrooms", "storeys", "floors",
            "parking", "locker", "maintenance_fees", "interior_area_sqft", "asking_price",
            "available_from", "description",
        )}),
        ("Assignment", {"classes": ("collapse",), "fields": (
            "project_name", "builder_name", "precon_property", "agreement_date", "occupancy_date",
            "original_purchase_price", "deposit_paid", "assignment_fee", "consent_to_advertise",
        )}),
        ("Private contact and declarations", {"fields": (
            "contact_name", "contact_email", "contact_phone", "ownership_confirmed",
            "publication_consent",
        )}),
        ("Review", {"fields": ("review_note", "reviewed_by", "reviewed_at")}),
    )
    actions = ("mark_under_review", "mark_needs_changes", "approve", "reject")

    def save_model(self, request, obj, form, change):
        if change and "status" in form.changed_data:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="Mark selected submissions under review")
    def mark_under_review(self, request, queryset):
        queryset.update(status=ListingSubmission.Status.UNDER_REVIEW, reviewed_by=request.user, reviewed_at=timezone.now())

    @admin.action(description="Request changes for selected submissions")
    def mark_needs_changes(self, request, queryset):
        queryset.update(status=ListingSubmission.Status.NEEDS_CHANGES, reviewed_by=request.user, reviewed_at=timezone.now())

    @admin.action(description="Approve selected submissions for public listing")
    def approve(self, request, queryset):
        queryset.update(status=ListingSubmission.Status.APPROVED, reviewed_by=request.user, reviewed_at=timezone.now())

    @admin.action(description="Reject selected submissions")
    def reject(self, request, queryset):
        queryset.update(status=ListingSubmission.Status.REJECTED, reviewed_by=request.user, reviewed_at=timezone.now())


class EstateUnitTypeInline(admin.TabularInline):
    model = EstateUnitType
    extra = 0
    fields = (
        "name",
        "description",
        "display_order",
    )


class EstatePriceInline(admin.TabularInline):
    model = EstatePrice
    extra = 0
    fields = (
        "unit_type",
        "display_text",
        "amount",
        "currency",
        "display_order",
    )


class EstateIncentiveInline(admin.TabularInline):
    model = EstateIncentive
    extra = 0
    fields = (
        "description",
        "display_order",
    )


class EstateAmenityInline(admin.TabularInline):
    model = EstateAmenity
    extra = 0
    fields = (
        "description",
        "display_order",
    )


class EstateDocumentInline(admin.TabularInline):
    model = EstateDocument
    extra = 0
    fields = (
        "label",
        "document_type",
        "source_url",
        "requires_phone_verification",
        "display_order",
    )
    

@admin.register(EstateProject)
class EstateProjectAdmin(admin.ModelAdmin):

    inlines = (
        EstateUnitTypeInline,
        EstatePriceInline,
        EstateIncentiveInline,
        EstateAmenityInline,
        EstateDocumentInline,
    )

    list_display = (
        "title",
        "developer",
        "city",
        "publication_status",
        "occupancy_year",
        "is_featured",
    )

    list_filter = (
        "publication_status",
        "is_featured",
        "province",
        "city",
    )

    search_fields = (
        "title",
        "developer",
        "address",
        "city",
        "source_id",
    )

    readonly_fields = (
        "source",
        "source_id",
        "source_updated_at",
        "created_at",
        "updated_at",
    )

    prepopulated_fields = {
        "slug": ("title",),
    }

    ordering = (
        "-is_featured",
        "title",
    )


class EstateDepositInstallmentInline(admin.TabularInline):
    model = EstateDepositInstallment
    extra = 0
    fields = (
        "milestone",
        "amount_text",
        "amount",
        "percentage",
        "display_order",
    )


@admin.register(EstateDepositPlan)
class EstateDepositPlanAdmin(admin.ModelAdmin):
    inlines = (
        EstateDepositInstallmentInline,
    )

    list_display = (
        "title",
        "project",
        "unit_type",
        "display_order",
    )
    list_filter = (
        "project",
    )
    search_fields = (
        "title",
        "project__title",
    )


from .models import AISearchLog  # noqa: E402


@admin.register(AISearchLog)
class AISearchLogAdmin(admin.ModelAdmin):
    """What people typed into AI search, what it became, and what it cost."""

    list_display = ("created_at", "query", "fallback", "cached", "model", "prompt_tokens", "completion_tokens", "latency_ms", "user")
    list_filter = ("fallback", "cached", "model", "created_at")
    search_fields = ("query", "user__email")
    list_select_related = ("user",)
    readonly_fields = [f.name for f in AISearchLog._meta.fields]
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


# --------------------------------------------------------------------------
# Sync / infrastructure
# --------------------------------------------------------------------------


@admin.register(AccessToken)
class AccessTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "access_token_expires_at", "refresh_token_expires_at")
    list_filter = ("access_token_expires_at", "refresh_token_expires_at")
    readonly_fields = ("access_token", "refresh_token", "access_token_expires_at", "refresh_token_expires_at")


@admin.register(ListingSyncStatus)
class ListingSyncStatusAdmin(admin.ModelAdmin):
    list_display = ("key", "last_successful_at", "listing_count", "updated_at")
    list_filter = ("last_successful_at", "updated_at")
    search_fields = ("key",)
    readonly_fields = ("updated_at",)
    ordering = ("-last_successful_at",)


@admin.register(MapAggregateCell)
class MapAggregateCellAdmin(admin.ModelAdmin):
    list_display = ("h3_index", "resolution", "property_count", "center_lat", "center_lng", "updated_at")
    list_filter = ("resolution", "updated_at")
    search_fields = ("h3_index",)
    readonly_fields = ("updated_at",)
    ordering = ("resolution", "h3_index")


@admin.register(CensusFSA)
class CensusFSAAdmin(admin.ModelAdmin):
    list_display = ("fsa", "updated_at")
    list_filter = ("updated_at",)
    search_fields = ("fsa",)
    readonly_fields = ("updated_at",)
    ordering = ("fsa",)


# --------------------------------------------------------------------------
# Property-related
# --------------------------------------------------------------------------


@admin.register(EstatePropertyImage)
class EstatePropertyImageAdmin(admin.ModelAdmin):
    list_display = ("id", "estate_property_display", "caption", "sort_order")
    list_filter = ("estate_property__city", "estate_property__publish_status")
    search_fields = (
        "caption",
        "estate_property__listing_key",
        "estate_property__property_title",
        "estate_property__city",
    )
    autocomplete_fields = ("estate_property",)
    list_select_related = ("estate_property",)
    ordering = ("sort_order", "id")

    @admin.display(description="Estate property", ordering="estate_property__listing_key")
    def estate_property_display(self, obj):
        p = obj.estate_property
        return f"{p.listing_key} — {p.property_title or p.city or ''}"


@admin.register(CommunityListing)
class CommunityListingAdmin(admin.ModelAdmin):
    list_display = ("community_name", "community_slug", "property_display", "badge", "rank", "is_published", "updated_at")
    list_filter = ("is_published", "community_slug", "badge", "created_at")
    list_editable = ("rank", "is_published")
    search_fields = (
        "community_name",
        "community_slug",
        "property__listing_key",
        "property__city",
        "property__street_name",
    )
    autocomplete_fields = ("property",)
    list_select_related = ("property",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("rank", "-updated_at")

    @admin.display(description="Property", ordering="property__listing_key")
    def property_display(self, obj):
        p = obj.property
        return f"{p.listing_key} · {p.city or ''}"


@admin.register(OpenHouse)
class OpenHouseAdmin(admin.ModelAdmin):
    list_display = ("open_house_key", "property_display", "date", "start_time", "end_time", "open_house_type", "status")
    list_filter = ("status", "open_house_type", "date")
    search_fields = (
        "open_house_key",
        "listing_id",
        "property__listing_key",
        "property__city",
        "property__street_name",
    )
    autocomplete_fields = ("property",)
    list_select_related = ("property",)
    date_hierarchy = "date"
    ordering = ("-date", "start_time")

    @admin.display(description="Property", ordering="property__listing_key")
    def property_display(self, obj):
        p = obj.property
        return f"{p.listing_key} · {p.city or ''}"


@admin.register(PropertySnapshot)
class PropertySnapshotAdmin(admin.ModelAdmin):
    list_display = ("listing_key", "list_price", "standard_status", "source_modification_timestamp", "created_at")
    list_filter = ("standard_status", "created_at", "source_modification_timestamp")
    search_fields = ("listing_key",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(ListingFirstSeen)
class ListingFirstSeenAdmin(admin.ModelAdmin):
    list_display = ("listing_key", "first_seen_at", "first_source_modification_timestamp")
    list_filter = ("first_seen_at",)
    search_fields = ("listing_key",)
    readonly_fields = ("first_seen_at",)
    ordering = ("-first_seen_at",)


@admin.register(PropertySoldProxy)
class PropertySoldProxyAdmin(admin.ModelAdmin):
    list_display = ("listing_key", "last_list_price", "sold_at_proxy", "city", "fsa", "bedrooms_total", "bathrooms_total_integer", "updated_at")
    list_filter = ("city", "fsa", "property_sub_type", "sold_at_proxy")
    search_fields = ("listing_key", "city", "unparsed_address", "fsa", "city_region")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "sold_at_proxy"
    ordering = ("-sold_at_proxy",)


@admin.register(PropertyEmbedding)
class PropertyEmbeddingAdmin(admin.ModelAdmin):
    list_display = ("property_display", "model", "dimensions", "updated_at")
    list_filter = ("model", "dimensions", "updated_at")
    search_fields = ("property__listing_key", "property__city", "model")
    autocomplete_fields = ("property",)
    list_select_related = ("property",)
    readonly_fields = ("property", "model", "dimensions", "text_hash", "vector", "updated_at")
    ordering = ("-updated_at",)

    @admin.display(description="Property", ordering="property__listing_key")
    def property_display(self, obj):
        p = obj.property
        return f"{p.listing_key} · {p.city or ''}"

    def has_add_permission(self, request):
        return False


# --------------------------------------------------------------------------
# User activity / preferences
# --------------------------------------------------------------------------


@admin.register(UserFavorite)
class UserFavoriteAdmin(admin.ModelAdmin):
    list_display = ("user_display", "property_key", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "property_key")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return f"{obj.user.email} ({obj.user.full_name})" if obj.user.full_name else obj.user.email


@admin.register(UserHistory)
class UserHistoryAdmin(admin.ModelAdmin):
    list_display = ("user_display", "property_key", "viewed_at")
    list_filter = ("viewed_at",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "property_key")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("viewed_at",)
    ordering = ("-viewed_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(UserToured)
class UserTouredAdmin(admin.ModelAdmin):
    list_display = ("user_display", "property_key", "toured_at")
    list_filter = ("toured_at",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "property_key")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("toured_at",)
    ordering = ("-toured_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(UserFollowedArea)
class UserFollowedAreaAdmin(admin.ModelAdmin):
    list_display = ("user_display", "area_label", "area_key", "area_kind", "created_at")
    list_filter = ("area_kind", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "area_key", "area_label")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(UserAlertPreference)
class UserAlertPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user_display",
        "email_enabled",
        "price_changes",
        "new_listings",
        "status_updates",
        "email_recommend",
        "email_watched_property",
        "email_watched_community",
        "email_watched_area",
        "push_watched_property",
        "updated_at",
    )
    list_filter = (
        "email_enabled",
        "price_changes",
        "new_listings",
        "status_updates",
        "email_recommend",
        "push_watched_property",
    )
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-updated_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ("user_display", "name", "alert_cadence", "last_run_at", "last_alert_sent_at", "last_result_count", "updated_at")
    list_filter = ("alert_cadence", "created_at", "last_alert_sent_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "name")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at", "last_run_at", "last_alert_sent_at")
    ordering = ("-updated_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(PropertyNote)
class PropertyNoteAdmin(admin.ModelAdmin):
    list_display = ("user_display", "listing_key", "updated_at", "created_at")
    list_filter = ("updated_at", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "listing_key", "body")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-updated_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user_display", "endpoint_preview", "user_agent", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "user__first_name", "user__last_name", "endpoint", "user_agent")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("endpoint", "p256dh", "auth", "created_at")
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email

    @admin.display(description="Endpoint")
    def endpoint_preview(self, obj):
        return (obj.endpoint or "")[:80]


# --------------------------------------------------------------------------
# Events & logs
# --------------------------------------------------------------------------


@admin.register(ListingViewEvent)
class ListingViewEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "listing_key", "user_display", "session_key", "ip_address")
    list_filter = ("created_at",)
    search_fields = ("listing_key", "user__email", "user__first_name", "user__last_name", "session_key", "ip_address")
    list_select_related = ("user",)
    readonly_fields = [f.name for f in ListingViewEvent._meta.fields]
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(UserPropertyInteraction)
class UserPropertyInteractionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "listing_key", "user_display", "source")
    list_filter = ("event_type", "source", "created_at")
    search_fields = ("listing_key", "user__email", "user__first_name", "user__last_name", "session_key")
    list_select_related = ("user",)
    readonly_fields = [f.name for f in UserPropertyInteraction._meta.fields]
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(SearchEvent)
class SearchEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "query", "city", "result_count", "user_display")
    list_filter = ("city", "created_at")
    search_fields = ("query", "city", "user__email", "user__first_name", "user__last_name", "session_key")
    list_select_related = ("user",)
    readonly_fields = [f.name for f in SearchEvent._meta.fields]
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(NewsletterDelivery)
class NewsletterDeliveryAdmin(admin.ModelAdmin):
    list_display = ("user_display", "digest_date", "status", "listing_count", "sent_at", "created_at")
    list_filter = ("status", "digest_date", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "digest_date"
    ordering = ("-digest_date",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


@admin.register(PreconActivityEvent)
class PreconActivityEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "project_display", "event", "user_display", "session_key")
    list_filter = ("event", "created_at")
    search_fields = (
        "project__content__title",
        "project__content__slug",
        "user__email",
        "user__first_name",
        "user__last_name",
        "session_key",
    )
    autocomplete_fields = ("project", "user")
    list_select_related = ("project__content", "user")
    readonly_fields = [f.name for f in PreconActivityEvent._meta.fields]
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Project", ordering="project__content__title")
    def project_display(self, obj):
        return obj.project.content.title if obj.project_id else "—"

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(AIAssistLog)
class AIAssistLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "question",
        "handoff",
        "fallback",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "user_display",
    )
    list_filter = ("handoff", "fallback", "model", "created_at")
    search_fields = ("question", "answer", "user__email", "user__first_name", "user__last_name")
    list_select_related = ("user",)
    readonly_fields = [f.name for f in AIAssistLog._meta.fields]
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------


class AgentServiceAreaInline(admin.TabularInline):
    model = AgentServiceArea
    extra = 0
    fields = ("kind", "key")


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    inlines = (AgentServiceAreaInline,)
    list_display = ("name", "email", "phone", "brokerage", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "brokerage", "created_at")
    list_editable = ("is_active",)
    search_fields = ("name", "email", "phone", "brokerage", "bio")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)


@admin.register(AgentServiceArea)
class AgentServiceAreaAdmin(admin.ModelAdmin):
    list_display = ("agent_display", "kind", "key")
    list_filter = ("kind",)
    search_fields = ("agent__name", "agent__email", "key")
    autocomplete_fields = ("agent",)
    list_select_related = ("agent",)
    ordering = ("agent", "kind", "key")

    @admin.display(description="Agent", ordering="agent__name")
    def agent_display(self, obj):
        return obj.agent.name


# --------------------------------------------------------------------------
# Estate (pre-con project) ancillaries
# --------------------------------------------------------------------------


@admin.register(EstateContentSection)
class EstateContentSectionAdmin(admin.ModelAdmin):
    list_display = ("project_display", "heading", "display_order", "parser_owned")
    list_filter = ("parser_owned", "project__city", "project__publication_status")
    search_fields = ("project__title", "project__developer", "heading", "html", "source_key")
    autocomplete_fields = ("project",)
    list_select_related = ("project",)
    ordering = ("project", "display_order", "id")

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title


@admin.register(EstateUnitType)
class EstateUnitTypeAdmin(admin.ModelAdmin):
    list_display = ("project_display", "name", "display_order", "parser_owned")
    list_filter = ("parser_owned", "project__city", "project__publication_status")
    search_fields = ("project__title", "project__developer", "name", "description", "source_key")
    autocomplete_fields = ("project",)
    list_select_related = ("project",)
    ordering = ("project", "display_order", "id")

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title


@admin.register(EstatePrice)
class EstatePriceAdmin(admin.ModelAdmin):
    list_display = ("project_display", "unit_type_display", "display_text", "amount", "currency", "display_order")
    list_filter = ("currency", "project__city", "project__publication_status")
    search_fields = ("project__title", "project__developer", "display_text", "unit_type__name", "source_key")
    autocomplete_fields = ("project", "unit_type")
    list_select_related = ("project", "unit_type")
    ordering = ("project", "display_order", "id")

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title

    @admin.display(description="Unit type", ordering="unit_type__name")
    def unit_type_display(self, obj):
        return obj.unit_type.name if obj.unit_type_id else "—"


@admin.register(EstateDepositInstallment)
class EstateDepositInstallmentAdmin(admin.ModelAdmin):
    list_display = ("plan_display", "milestone", "amount_text", "amount", "percentage", "display_order")
    list_filter = ("plan__project__city",)
    search_fields = ("plan__title", "plan__project__title", "milestone", "amount_text", "source_key")
    autocomplete_fields = ("plan",)
    list_select_related = ("plan", "plan__project")
    ordering = ("plan", "display_order", "id")

    @admin.display(description="Deposit plan", ordering="plan__title")
    def plan_display(self, obj):
        return f"{obj.plan.project.title} · {obj.plan.title}"


@admin.register(EstateIncentive)
class EstateIncentiveAdmin(admin.ModelAdmin):
    list_display = ("project_display", "description", "display_order", "parser_owned")
    list_filter = ("parser_owned", "project__city", "project__publication_status")
    search_fields = ("project__title", "project__developer", "description", "source_key")
    autocomplete_fields = ("project",)
    list_select_related = ("project",)
    ordering = ("project", "display_order", "id")

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title


@admin.register(EstateAmenity)
class EstateAmenityAdmin(admin.ModelAdmin):
    list_display = ("project_display", "description", "travel_time_minutes", "display_order", "parser_owned")
    list_filter = ("parser_owned", "project__city", "project__publication_status")
    search_fields = ("project__title", "project__developer", "description", "source_key")
    autocomplete_fields = ("project",)
    list_select_related = ("project",)
    ordering = ("project", "display_order", "id")

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title


@admin.register(EstateDocument)
class EstateDocumentAdmin(admin.ModelAdmin):
    list_display = ("project_display", "label", "document_type", "requires_phone_verification", "display_order")
    list_filter = ("document_type", "requires_phone_verification", "project__city", "project__publication_status")
    search_fields = ("project__title", "project__developer", "label", "source_url", "source_key")
    autocomplete_fields = ("project",)
    list_select_related = ("project",)
    ordering = ("project", "display_order", "id")

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title


@admin.register(EstateSourceSnapshot)
class EstateSourceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("project_display", "parser_version", "source_updated_at", "imported_at")
    list_filter = ("parser_version", "source_updated_at", "imported_at")
    search_fields = ("project__title", "project__developer")
    autocomplete_fields = ("project",)
    list_select_related = ("project",)
    readonly_fields = ("imported_at",)
    ordering = ("-imported_at",)

    @admin.display(description="Project", ordering="project__title")
    def project_display(self, obj):
        return obj.project.title


@admin.register(EstateDocumentIntent)
class EstateDocumentIntentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "document_display", "user_display", "phone", "verified_at")
    list_filter = ("verified_at", "created_at", "document__document_type")
    search_fields = (
        "document__label",
        "document__project__title",
        "user__email",
        "user__first_name",
        "user__last_name",
        "phone",
    )
    autocomplete_fields = ("document", "user")
    list_select_related = ("document__project", "user")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    @admin.display(description="Document", ordering="document__label")
    def document_display(self, obj):
        return f"{obj.document.project.title} · {obj.document.label}"

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email


# --------------------------------------------------------------------------
# Listing submissions ancillary
# --------------------------------------------------------------------------


@admin.register(ListingSubmissionMedia)
class ListingSubmissionMediaAdmin(admin.ModelAdmin):
    list_display = ("submission_display", "media_type", "display_order", "uploaded_at")
    list_filter = ("media_type", "uploaded_at")
    search_fields = (
        "submission__address_line_1",
        "submission__project_name",
        "submission__city",
        "submission__contact_email",
    )
    autocomplete_fields = ("submission",)
    list_select_related = ("submission",)
    readonly_fields = ("uploaded_at",)
    ordering = ("submission", "display_order", "id")

    @admin.display(description="Submission", ordering="submission__id")
    def submission_display(self, obj):
        s = obj.submission
        return f"#{s.id} · {s.address_line_1 or s.project_name or 'submission'}"

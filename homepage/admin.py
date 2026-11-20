from django.contrib import admin

from .models import (
    BuyerIncentive,
    CommunityImage,
    IntegrationSettings,
    MarketSnapshot,
    NearbyAlert,
    NewsArticle,
    NewsletterSubscriber,
    NewsSource,
    Partner,
    SiteContent,
    SiteContentRevision,
    SoldBelowPurchase,
)


@admin.register(SiteContent)
class SiteContentAdmin(admin.ModelAdmin):
    list_display = ("key", "schema_version", "updated_at", "published_at", "updated_by_display")
    list_filter = ("key", "schema_version", "updated_at", "published_at")
    search_fields = ("key", "updated_by__email", "updated_by__first_name", "updated_by__last_name")
    list_select_related = ("updated_by",)
    readonly_fields = ("key", "draft", "published", "schema_version", "updated_at", "published_at", "updated_by")
    ordering = ("key",)

    @admin.display(description="Updated by", ordering="updated_by__email")
    def updated_by_display(self, obj):
        return obj.updated_by.email if obj.updated_by_id else "—"


@admin.register(BuyerIncentive)
class BuyerIncentiveAdmin(admin.ModelAdmin):
    list_display = ("title", "amount_text", "label", "icon", "reviewed_at", "is_active", "display_order", "updated_at")
    list_editable = ("is_active", "display_order")
    list_filter = ("is_active", "icon", "reviewed_at")
    search_fields = ("title", "label", "description", "amount_text", "source_url")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("display_order", "id")


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "website_url", "is_active", "display_order", "updated_at")
    list_editable = ("is_active", "display_order")
    list_filter = ("category", "is_active")
    search_fields = ("name", "category", "description", "website_url")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("display_order", "id")


@admin.register(CommunityImage)
class CommunityImageAdmin(admin.ModelAdmin):
    list_display = ("city_label", "city_key", "credit", "updated_at")
    list_filter = ("updated_at",)
    search_fields = ("city_label", "city_key", "credit")
    readonly_fields = ("updated_at",)
    ordering = ("city_label",)


@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "feed_url", "tag", "is_active", "last_fetched_at")
    list_filter = ("is_active", "tag", "last_fetched_at")
    list_editable = ("is_active",)
    search_fields = ("name", "feed_url", "tag")
    readonly_fields = ("last_fetched_at", "last_error")
    ordering = ("name",)


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "source_display", "tag", "published_at", "fetched_at", "is_hidden")
    list_filter = ("source", "tag", "is_hidden", "published_at", "fetched_at")
    list_editable = ("is_hidden",)
    search_fields = ("title", "summary", "url", "tag", "source__name")
    autocomplete_fields = ("source",)
    list_select_related = ("source",)
    date_hierarchy = "published_at"
    readonly_fields = ("fetched_at",)
    ordering = ("-published_at",)

    @admin.display(description="Source", ordering="source__name")
    def source_display(self, obj):
        return obj.source.name


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    # Consent evidence is read-only: editing it would defeat its purpose.
    list_display = ("email", "user_display", "source", "consent_at", "unsubscribed_at", "created_at")
    list_filter = ("source", "consent_at", "unsubscribed_at", "created_at")
    search_fields = ("email", "user__email", "user__first_name", "user__last_name", "ip_address")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("consent_at", "consent_text", "ip_address", "token", "created_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"


@admin.register(NearbyAlert)
class NearbyAlertAdmin(admin.ModelAdmin):
    list_display = ("email", "user_display", "label", "radius_km", "is_active", "last_notified_at", "created_at")
    list_filter = ("is_active", "radius_km", "created_at", "last_notified_at")
    list_editable = ("is_active",)
    search_fields = ("email", "label", "user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("consent_at", "consent_text", "token", "created_at")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="User", ordering="user__email")
    def user_display(self, obj):
        return obj.user.email if obj.user_id else "—"


@admin.register(SoldBelowPurchase)
class SoldBelowPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "address",
        "city",
        "property_sub_type",
        "bedrooms",
        "bathrooms",
        "close_price",
        "previous_close_price",
        "close_date",
        "previous_close_date",
    )
    list_filter = ("city", "property_sub_type", "close_date")
    search_fields = ("address", "city", "listing_key", "property_sub_type")
    readonly_fields = ("computed_at",)
    date_hierarchy = "close_date"
    ordering = ("-close_date",)

    def has_add_permission(self, request):
        return False  # computed by refresh_homepage_feeds


@admin.register(MarketSnapshot)
class MarketSnapshotAdmin(admin.ModelAdmin):
    list_display = ("scope", "as_of")
    list_filter = ("scope", "as_of")
    search_fields = ("scope",)
    readonly_fields = ("scope", "payload", "as_of")
    ordering = ("scope",)

    def has_add_permission(self, request):
        return False  # computed by refresh_homepage_feeds


@admin.register(SiteContentRevision)
class SiteContentRevisionAdmin(admin.ModelAdmin):
    list_display = ("content_display", "created_at", "created_by_display")
    list_filter = ("content", "created_at")
    search_fields = (
        "content__key",
        "created_by__email",
        "created_by__first_name",
        "created_by__last_name",
    )
    autocomplete_fields = ("content", "created_by")
    list_select_related = ("content", "created_by")
    readonly_fields = ("content", "snapshot", "created_at", "created_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Site content", ordering="content__key")
    def content_display(self, obj):
        return obj.content.key

    @admin.display(description="Created by", ordering="created_by__email")
    def created_by_display(self, obj):
        return obj.created_by.email if obj.created_by_id else "—"

    def has_add_permission(self, request):
        return False  # snapshots are written on publish


@admin.register(IntegrationSettings)
class IntegrationSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "updated_at")
    list_filter = ("updated_at",)
    readonly_fields = ("updated_at",)
    ordering = ("-updated_at",)

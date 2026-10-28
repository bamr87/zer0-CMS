"""The shapes `/api/v2/sites/` reads and answers with (sites/views.py), which the
OpenAPI document and the studio's generated client follow. `Site` is P4's shape
(the studio's site switcher reads it) with what the platform manages of it."""

import re

from rest_framework import serializers

from jobs.serializers import JobSerializer

from .models import ManagedSite, SiteSettings

HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")


class ManagedSiteSerializer(serializers.ModelSerializer):
    domains = serializers.ListField(child=serializers.CharField(), help_text="The host names it is published at.")
    errors = serializers.SerializerMethodField(help_text="Errors in the last doctor run.")
    warnings = serializers.SerializerMethodField(help_text="Warnings in the last doctor run.")

    class Meta:
        model = ManagedSite
        fields = [
            "key",
            "checkout",
            "content_source",
            "render",
            "theme_tag",
            "server",
            "domains",
            "deploy_target",
            "last_synced_at",
            "last_exported_at",
            "last_doctor_at",
            "errors",
            "warnings",
        ]

    def get_errors(self, managed) -> int:
        return sum(f.get("severity") == "error" for f in managed.findings)

    def get_warnings(self, managed) -> int:
        return sum(f.get("severity") == "warning" for f in managed.findings)


class SiteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    hostname = serializers.CharField()
    port = serializers.IntegerField()
    is_default = serializers.BooleanField()
    root_page_id = serializers.IntegerField()
    managed = ManagedSiteSerializer(
        allow_null=True,
        required=False,
        help_text="The platform's registry entry, or null for a site it does not manage.",
    )
    can_manage = serializers.BooleanField(required=False, help_text="The caller may sync, write back and configure it.")


class PageCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    live = serializers.IntegerField()
    drafts = serializers.IntegerField(help_text="Never published, or with changes not yet published.")


class SiteDetailSerializer(SiteSerializer):
    pages = PageCountsSerializer()
    files = serializers.IntegerField(help_text="Content files the platform has read from or written to its checkout.")
    jobs = JobSerializer(many=True, help_text="Its latest jobs, newest first.")


class SiteUpdateSerializer(serializers.ModelSerializer):
    domains = serializers.ListField(child=serializers.CharField(max_length=253), required=False, max_length=20)

    class Meta:
        model = ManagedSite
        fields = ["content_source", "render", "theme_tag", "server", "domains", "deploy_target"]
        extra_kwargs = {name: {"required": False} for name in fields}

    def validate_domains(self, domains):
        cleaned = [d.strip().lower() for d in domains if d.strip()]
        bad = [d for d in cleaned if not HOSTNAME.match(d)]
        if bad:
            raise serializers.ValidationError(f"not a host name: {', '.join(bad)}")
        return list(dict.fromkeys(cleaned))

    def validate_theme_tag(self, tag):
        if tag and not re.fullmatch(r"v?\d+(\.\d+){0,2}[\w.-]*", tag):
            raise serializers.ValidationError("a release tag, e.g. v1.31.3")
        return tag


class NavigationItemSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=80)
    url = serializers.CharField(max_length=500)


class BannedPatternSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, help_text="What the guard calls it in a refusal.")
    pattern = serializers.CharField(max_length=500, help_text="A regular expression (Python's).")
    flags = serializers.CharField(
        max_length=8,
        required=False,
        allow_blank=True,
        help_text="`i`, or none given, matches any case; empty matches case.",
    )

    def validate_pattern(self, value):
        try:
            re.compile(value)
        except re.error as e:
            raise serializers.ValidationError(f"not a regular expression: {e}") from e
        return value


class SiteSettingsSerializer(serializers.ModelSerializer):
    navigation = NavigationItemSerializer(many=True, required=False)
    banned_patterns = BannedPatternSerializer(many=True, required=False)
    design_tokens = serializers.DictField(child=serializers.CharField(max_length=200), required=False)

    class Meta:
        model = SiteSettings
        fields = [
            "seo_title_suffix",
            "seo_description",
            "seo_image",
            "noindex",
            "ga4_measurement_id",
            "search_console_property",
            "navigation",
            "brand_voice",
            "banned_patterns",
            "skin",
            "design_tokens",
            "monthly_budget_usd",
        ]
        extra_kwargs = {name: {"required": False} for name in fields}

    def validate_ga4_measurement_id(self, value):
        if value and not re.fullmatch(r"G-[A-Z0-9]{4,20}", value):
            raise serializers.ValidationError("a GA4 measurement id looks like G-XXXXXXX")
        return value


class RegisterSiteSerializer(serializers.Serializer):
    checkout = serializers.CharField(
        max_length=512, help_text="The site's Jekyll root, relative to the repository or absolute under SITES_DIR."
    )
    key = serializers.SlugField(max_length=80, required=False, allow_blank=True, help_text="Defaults to its name.")


class RegisteredSiteSerializer(serializers.Serializer):
    site = SiteSerializer()
    job = JobSerializer(help_text="Its first sync, queued.")


class SiteCandidateSerializer(serializers.Serializer):
    key = serializers.CharField()
    checkout = serializers.CharField()
    render = serializers.CharField()
    theme_tag = serializers.CharField(allow_blank=True)
    server = serializers.CharField(allow_blank=True)
    deploy_target = serializers.CharField(allow_blank=True)


class SyncOptionsSerializer(serializers.Serializer):
    force = serializers.BooleanField(
        default=False, help_text="Take a changed file over a page changed here since (else a conflict)."
    )


class ExportOptionsSerializer(serializers.Serializer):
    include_drafts = serializers.BooleanField(
        default=False, help_text="Write the latest revisions, not the live pages."
    )
    base = serializers.DictField(
        child=serializers.CharField(max_length=64),
        required=False,
        help_text="{path: sha256} as the caller saw each file; a file the platform re-indexed since is not written.",
    )


class JobAcceptedSerializer(serializers.Serializer):
    job = JobSerializer()


class DoctorFindingSerializer(serializers.Serializer):
    check_id = serializers.CharField()
    severity = serializers.ChoiceField([("error", "error"), ("warning", "warning")])
    file = serializers.CharField(allow_blank=True)
    line = serializers.IntegerField(allow_null=True)
    rule = serializers.CharField()
    evidence = serializers.CharField(allow_blank=True)
    fingerprint = serializers.CharField()

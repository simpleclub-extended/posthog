"""
URL configuration for Workload Identity Federation OIDC provider.

These endpoints enable PostHog to act as an OIDC identity provider
for Google Cloud Workload Identity Federation.
"""

from django.urls import path, re_path

from posthog.api import workload_identity
from posthog.utils import opt_slash_path

app_name = "workload_identity"

urlpatterns = [
    # OIDC Discovery endpoint
    re_path(
        r"^\.well-known/openid-configuration/?$",
        workload_identity.WorkloadIdentityDiscoveryView.as_view(),
        name="discovery",
    ),
    # JWKS endpoint
    path(
        ".well-known/jwks.json",
        workload_identity.WorkloadIdentityJWKSView.as_view(),
        name="jwks",
    ),
    # Token generation endpoint
    opt_slash_path(
        "token",
        workload_identity.WorkloadIdentityTokenGenerationView.as_view(),
        name="token",
    ),
]

"""
URL configuration for Workload Identity Federation OIDC provider.

These endpoints enable PostHog to act as an OIDC identity provider
for Google Cloud Workload Identity Federation.

Note: Token generation is NOT exposed as a public endpoint.
It is an internal function called by workloads.
"""

from django.urls import path, re_path

from posthog.api import workload_identity

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
]

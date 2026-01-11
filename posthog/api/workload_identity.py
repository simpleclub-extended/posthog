"""
Workload Identity Federation OIDC Provider for Google Cloud.

This module implements PostHog as an OIDC identity provider to enable
Workload Identity Federation with Google Cloud services. It provides:

1. OIDC Discovery endpoint (/.well-known/openid-configuration)
2. JWKS endpoint (/.well-known/jwks.json)  
3. Internal function for generating JWT tokens (NOT a public endpoint)

Token generation is only accessible internally by workloads (BigQuery sources,
Cloud Storage destinations, etc.) that need to authenticate with Google Cloud.

See: https://docs.cloud.google.com/iam/docs/use-workload-identity-federation-to-let-customers-access-their-cloud-resources
"""

import base64
import time
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

import jwt
import structlog

from posthog.models import Team
from posthog.models.workload_identity_key import WorkloadIdentityKey

logger = structlog.get_logger(__name__)


def get_workload_identity_issuer() -> str:
    """Get the OIDC issuer URL for Workload Identity Federation.
    
    Uses a dedicated subdomain to separate from regular OAuth flows.
    """
    # Use the site URL but replace the subdomain with 'integrations'
    # e.g., https://us.posthog.com -> https://us.integrations.posthog.com
    site_url = settings.SITE_URL
    
    # For now, use the main site URL with a path prefix
    # In production, this could be a separate subdomain like integrations.posthog.com
    return f"{site_url}/workload-identity"


def get_workload_identity_jwks_uri() -> str:
    """Get the JWKS URI for Workload Identity Federation."""
    return f"{get_workload_identity_issuer()}/.well-known/jwks.json"


class WorkloadIdentityDiscoveryView(View):
    """
    OIDC Discovery endpoint for Workload Identity Federation.
    
    Returns the OpenID Connect configuration for Google Cloud to discover
    and validate PostHog as an identity provider.
    
    Endpoint: /workload-identity/.well-known/openid-configuration
    """
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def get(self, request):
        issuer = get_workload_identity_issuer()
        
        discovery_info = {
            "issuer": issuer,
            "jwks_uri": get_workload_identity_jwks_uri(),
            "subject_types_supported": ["public"],
            "response_types_supported": ["id_token"],
            "claims_supported": [
                "sub",
                "aud",
                "exp",
                "iat",
                "iss",
                "nbf",
                "organization_id",
                "project_id",
                "project_name",
                "project_region",
            ],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid"],
        }
        
        return JsonResponse(discovery_info)


class WorkloadIdentityJWKSView(View):
    """
    JWKS endpoint for Workload Identity Federation.
    
    Returns the public keys used to sign JWT tokens for Google Cloud
    to validate the tokens.
    
    Endpoint: /workload-identity/.well-known/jwks.json
    """
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def get(self, request):
        # Get all valid keys for JWKS
        keys_data = []
        
        for key_model in WorkloadIdentityKey.get_all_valid_keys():
            key_data = {
                "kty": "RSA",
                "kid": key_model.key_id,
                "use": "sig",
                "alg": key_model.algorithm,
                "n": key_model.public_key_n,
                "e": key_model.public_key_e,
            }
            keys_data.append(key_data)
        
        jwks = {
            "keys": keys_data
        }
        
        return JsonResponse(jwks)


def generate_workload_identity_token(
    team_id: int,
    audience: str,
    service_type: str | None = None,
    service_id: str | None = None,
) -> str:
    """
    Internal function to generate a Workload Identity Federation JWT token.
    
    This function should ONLY be called by internal workloads (BigQuery sources,
    Cloud Storage destinations, etc.) that need to authenticate with Google Cloud.
    It is NOT exposed as a public endpoint.
    
    Args:
        team_id: PostHog team/project ID
        audience: Google Cloud Workload Identity Pool audience URL
        service_type: Type of Google Cloud service (bigquery, storage, pubsub, etc.)
        service_id: ID of the specific source/destination
        
    Returns:
        JWT token string to use with Google STS API
        
    Raises:
        ValueError: If team doesn't exist or no active signing key is available
    """
    # Get the team and verify it exists
    try:
        team = Team.objects.select_related('organization').get(id=team_id)
    except Team.DoesNotExist:
        raise ValueError(f"Team with id {team_id} does not exist")
    
    organization_id = str(team.organization_id)
    project_id = str(team_id)
    project_name = team.name
    project_region = _get_project_region()
    
    # Generate the JWT token
    now = int(time.time())
    expiration = now + 3600  # 1 hour from now
    
    # Build the subject claim
    # Format: project:<ORG-ID>/<PROJECT-ID>:<service_type>:<service_id>
    subject_parts = [f"project:{organization_id}/{project_id}"]
    if service_type:
        subject_parts.append(service_type)
    if service_id:
        subject_parts.append(service_id)
    subject = ":".join(subject_parts)
    
    # Build the token claims
    claims = {
        "iss": get_workload_identity_issuer(),
        "sub": subject,
        "aud": audience,
        "exp": expiration,
        "iat": now,
        "nbf": now,
        "organization_id": organization_id,
        "project_id": project_id,
        "project_name": project_name,
        "project_region": project_region,
    }
    
    # Add optional service-specific claims
    if service_type:
        claims["service_type"] = service_type
    if service_id:
        claims["service_id"] = service_id
    
    # Get the active signing key
    key_model = WorkloadIdentityKey.get_active_key()
    if not key_model:
        raise ValueError("No active signing key available for Workload Identity Federation")
    
    # Sign the token with RS256
    token = jwt.encode(
        claims,
        key_model.private_key,
        algorithm=key_model.algorithm,
        headers={"kid": key_model.key_id}
    )
    
    # Mark the key as used
    key_model.mark_used()
    
    logger.info(
        "workload_identity_token_generated",
        organization_id=organization_id,
        project_id=project_id,
        team_id=team_id,
        service_type=service_type,
        key_id=key_model.key_id,
    )
    
    return token


def _get_project_region() -> str:
    """Determine the region of the current PostHog instance."""
    # Extract region from SITE_URL
    # e.g., https://us.posthog.com -> "us"
    #       https://eu.posthog.com -> "eu"
    site_url = settings.SITE_URL
    if ".posthog.com" in site_url:
        parts = site_url.split("://")
        if len(parts) > 1:
            domain_parts = parts[1].split(".")
            if len(domain_parts) > 2:
                return domain_parts[0]  # us, eu, etc.
    return "us"  # default

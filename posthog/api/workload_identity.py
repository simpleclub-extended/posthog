"""
Workload Identity Federation OIDC Provider for Google Cloud.

This module implements PostHog as an OIDC identity provider to enable
Workload Identity Federation with Google Cloud services. It provides:

1. OIDC Discovery endpoint (/.well-known/openid-configuration)
2. JWKS endpoint (/.well-known/jwks.json)  
3. JWT token generation with organization/project claims
4. Token exchange with Google STS API

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
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models import Team, User
from posthog.models.workload_identity_key import WorkloadIdentityKey
from posthog.user_permissions import UserPermissions

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


class WorkloadIdentityTokenGenerationView(APIView):
    """
    Generate OIDC tokens for Workload Identity Federation.
    
    This endpoint creates JWT tokens that PostHog can use to authenticate
    with Google Cloud services via Workload Identity Federation.
    
    The token includes claims about the organization and project to enable
    fine-grained access control in Google Cloud via attribute conditions.
    """
    
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """Generate a Workload Identity Federation token.
        
        Required parameters:
        - organization_id: PostHog organization ID
        - project_id: PostHog project ID
        - audience: Google Cloud Workload Identity Pool audience
        - service_type: Type of service (bigquery, storage, pubsub, etc.)
        - service_id: ID of the specific service/source/destination
        
        Returns:
        - token: JWT token to use with Google STS API
        - expires_in: Token expiration time in seconds
        """
        user: User = request.user
        
        # Validate required parameters
        organization_id = request.data.get("organization_id")
        project_id = request.data.get("project_id")
        audience = request.data.get("audience")
        service_type = request.data.get("service_type")
        service_id = request.data.get("service_id")
        
        if not all([organization_id, project_id, audience]):
            return Response(
                {"error": "organization_id, project_id, and audience are required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify user has access to the organization and project
        try:
            team = Team.objects.get(id=project_id, organization_id=organization_id)
        except Team.DoesNotExist:
            return Response(
                {"error": "Project not found or access denied"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        user_permissions = UserPermissions(user)
        if not user_permissions.team(team).effective_membership_level:
            return Response(
                {"error": "You don't have access to this project"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Generate the JWT token
        try:
            token = self._generate_token(
                organization_id=organization_id,
                project_id=project_id,
                project_name=team.name,
                project_region=self._get_project_region(),
                audience=audience,
                service_type=service_type,
                service_id=service_id,
            )
            
            return Response({
                "token": token,
                "expires_in": 3600,  # 1 hour
                "token_type": "Bearer"
            })
            
        except Exception as e:
            logger.error("workload_identity_token_generation_failed", error=str(e))
            return Response(
                {"error": "Failed to generate token"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _generate_token(
        self,
        organization_id: str,
        project_id: int,
        project_name: str,
        project_region: str,
        audience: str,
        service_type: str | None = None,
        service_id: str | None = None,
    ) -> str:
        """Generate a JWT token for Workload Identity Federation.
        
        The token includes claims that Google Cloud can use for attribute-based
        access control via CEL expressions.
        """
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
            "organization_id": str(organization_id),
            "project_id": str(project_id),
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
            raise ValueError("No active signing key available")
        
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
            service_type=service_type,
            key_id=key_model.key_id,
        )
        
        return token
    
    def _get_project_region(self) -> str:
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

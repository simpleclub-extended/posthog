"""
Google STS (Security Token Service) API integration for Workload Identity Federation.

This module handles exchanging PostHog-generated OIDC tokens for Google Cloud
access tokens via the Google STS API.

See: https://cloud.google.com/iam/docs/reference/sts/rest/v1/TopLevel/token
"""

import time
from typing import Any

import requests
import structlog

logger = structlog.get_logger(__name__)


class GoogleSTSClient:
    """Client for Google Cloud Security Token Service (STS) API."""
    
    STS_TOKEN_ENDPOINT = "https://sts.googleapis.com/v1/token"
    
    def exchange_token(
        self,
        subject_token: str,
        audience: str,
        scope: str = "https://www.googleapis.com/auth/cloud-platform",
        requested_token_type: str = "urn:ietf:params:oauth:token-type:access_token",
    ) -> dict[str, Any]:
        """
        Exchange a PostHog OIDC token for a Google Cloud access token.
        
        Args:
            subject_token: PostHog-generated OIDC token (JWT)
            audience: Workload Identity Pool audience URL
            scope: OAuth scope for the access token
            requested_token_type: Type of token to request
            
        Returns:
            Dictionary containing:
            - access_token: Google Cloud access token
            - issued_token_type: Type of token issued
            - token_type: Token type (usually "Bearer")
            - expires_in: Token expiration in seconds
            
        Raises:
            requests.HTTPError: If the STS API returns an error
            ValueError: If the response is invalid
        """
        request_body = {
            "audience": audience,
            "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requestedTokenType": requested_token_type,
            "scope": scope,
            "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
            "subjectToken": subject_token,
        }
        
        logger.info(
            "google_sts_token_exchange_request",
            audience=audience,
            scope=scope,
        )
        
        try:
            response = requests.post(
                self.STS_TOKEN_ENDPOINT,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            
            token_data = response.json()
            
            logger.info(
                "google_sts_token_exchange_success",
                expires_in=token_data.get("expires_in"),
                token_type=token_data.get("token_type"),
            )
            
            return token_data
            
        except requests.HTTPError as e:
            logger.error(
                "google_sts_token_exchange_failed",
                status_code=e.response.status_code if e.response else None,
                error=str(e),
                response_body=e.response.text if e.response else None,
            )
            raise
        except Exception as e:
            logger.error("google_sts_token_exchange_error", error=str(e))
            raise


def get_google_cloud_access_token(
    team_id: int,
    audience: str,
    service_type: str | None = None,
    service_id: str | None = None,
    scope: str = "https://www.googleapis.com/auth/cloud-platform",
) -> str:
    """
    Get a Google Cloud access token for a specific team.
    
    This function combines OIDC token generation and STS token exchange
    to obtain a Google Cloud access token that can be used to access
    Google Cloud services.
    
    Args:
        team_id: PostHog team/project ID
        audience: Workload Identity Pool audience URL
        service_type: Type of Google Cloud service
        service_id: ID of the specific source/destination
        scope: OAuth scope for the access token
        
    Returns:
        Google Cloud access token (string)
        
    Raises:
        ValueError: If token generation or exchange fails
    """
    from posthog.api.workload_identity import generate_workload_identity_token
    
    # Step 1: Generate PostHog OIDC token
    oidc_token = generate_workload_identity_token(
        team_id=team_id,
        audience=audience,
        service_type=service_type,
        service_id=service_id,
    )
    
    # Step 2: Exchange OIDC token for Google Cloud access token
    sts_client = GoogleSTSClient()
    token_response = sts_client.exchange_token(
        subject_token=oidc_token,
        audience=audience,
        scope=scope,
    )
    
    # Extract and return the access token
    access_token = token_response.get("access_token")
    if not access_token:
        raise ValueError("No access token returned from Google STS")
    
    return access_token

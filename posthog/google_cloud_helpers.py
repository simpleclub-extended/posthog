"""
Google Cloud authentication helper for Workload Identity Federation.

This module provides a unified interface for authenticating with Google Cloud
services using Workload Identity Federation. It handles the full flow:
1. Generate PostHog OIDC token
2. Exchange for Google Cloud access token
3. Create authenticated clients for Google Cloud services
"""

import contextlib
from typing import Any, Iterator

from google.auth import credentials as auth_credentials
from google.auth.transport import requests as google_requests
from google.cloud import bigquery, storage
from google.oauth2 import credentials as oauth2_credentials
import structlog

from posthog.google_cloud_sts import get_google_cloud_access_token

logger = structlog.get_logger(__name__)


def get_google_cloud_credentials(
    team_id: int,
    audience: str,
    service_type: str | None = None,
    service_id: str | None = None,
    scopes: list[str] | None = None,
) -> auth_credentials.Credentials:
    """
    Get Google Cloud credentials for a specific team using Workload Identity Federation.
    
    Args:
        team_id: PostHog team/project ID
        audience: Workload Identity Pool audience URL
        service_type: Type of Google Cloud service (bigquery, storage, etc.)
        service_id: ID of the specific source/destination
        scopes: OAuth scopes (default: cloud-platform scope)
        
    Returns:
        Google Cloud credentials object
    """
    if scopes is None:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    
    # Get access token via Workload Identity Federation
    access_token = get_google_cloud_access_token(
        team_id=team_id,
        audience=audience,
        service_type=service_type,
        service_id=service_id,
        scope=" ".join(scopes),
    )
    
    # Create OAuth2 credentials from the access token
    credentials = oauth2_credentials.Credentials(
        token=access_token,
        scopes=scopes,
    )
    
    return credentials


@contextlib.contextmanager
def bigquery_client_with_workload_identity(
    team_id: int,
    audience: str,
    project_id: str,
    service_type: str | None = None,
    service_id: str | None = None,
) -> Iterator[bigquery.Client]:
    """
    Create an authenticated BigQuery client using Workload Identity Federation.
    
    Args:
        team_id: PostHog team/project ID
        audience: Workload Identity Pool audience URL
        project_id: Google Cloud project ID
        service_type: Type of service (e.g., "bigquery_source")
        service_id: ID of the specific source/destination
        
    Yields:
        Authenticated BigQuery client
    """
    credentials = get_google_cloud_credentials(
        team_id=team_id,
        audience=audience,
        service_type=service_type,
        service_id=service_id,
        scopes=[
            "https://www.googleapis.com/auth/bigquery",
            "https://www.googleapis.com/auth/cloud-platform",
        ],
    )
    
    client = bigquery.Client(
        project=project_id,
        credentials=credentials,
    )
    
    try:
        yield client
    finally:
        client.close()


@contextlib.contextmanager
def storage_client_with_workload_identity(
    team_id: int,
    audience: str,
    project_id: str,
    service_type: str | None = None,
    service_id: str | None = None,
) -> Iterator[storage.Client]:
    """
    Create an authenticated Cloud Storage client using Workload Identity Federation.
    
    Args:
        team_id: PostHog team/project ID
        audience: Workload Identity Pool audience URL
        project_id: Google Cloud project ID
        service_type: Type of service (e.g., "storage_destination")
        service_id: ID of the specific source/destination
        
    Yields:
        Authenticated Cloud Storage client
    """
    credentials = get_google_cloud_credentials(
        team_id=team_id,
        audience=audience,
        service_type=service_type,
        service_id=service_id,
        scopes=[
            "https://www.googleapis.com/auth/devstorage.read_write",
            "https://www.googleapis.com/auth/cloud-platform",
        ],
    )
    
    client = storage.Client(
        project=project_id,
        credentials=credentials,
    )
    
    try:
        yield client
    finally:
        client.close()

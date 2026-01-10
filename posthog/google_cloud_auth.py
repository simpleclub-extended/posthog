"""Centralized Google Cloud authentication utilities.

This module provides utilities for authenticating with Google Cloud services using
either service account keys or Workload Identity Federation.
"""

import contextlib
from typing import Any, Iterator, Literal

from google.auth import credentials as auth_credentials
from google.auth import external_account
from google.oauth2 import service_account


def get_google_credentials(
    auth_config: dict[str, Any],
    scopes: list[str],
) -> auth_credentials.Credentials:
    """Get Google Cloud credentials from either service account key or external account config.

    Args:
        auth_config: Either a service account key dict or external account config dict
        scopes: List of OAuth scopes to request

    Returns:
        Google auth credentials object

    Raises:
        ValueError: If auth_config is invalid or missing required fields
    """
    auth_type = auth_config.get("type")

    if auth_type == "service_account":
        # Traditional service account key authentication
        required_fields = ["project_id", "private_key", "private_key_id", "client_email", "token_uri"]
        missing_fields = [field for field in required_fields if not auth_config.get(field)]

        if missing_fields:
            raise ValueError(f"Missing required service account fields: {', '.join(missing_fields)}")

        return service_account.Credentials.from_service_account_info(
            {
                "type": "service_account",
                "private_key": auth_config["private_key"],
                "private_key_id": auth_config["private_key_id"],
                "token_uri": auth_config["token_uri"],
                "client_email": auth_config["client_email"],
                "project_id": auth_config["project_id"],
            },
            scopes=scopes,
        )

    elif auth_type == "external_account":
        # Workload Identity Federation authentication
        return external_account.Credentials.from_info(auth_config, scopes=scopes)

    else:
        # Legacy format: assume service account if type field is missing but has service account fields
        if all(
            auth_config.get(field)
            for field in ["project_id", "private_key", "private_key_id", "client_email", "token_uri"]
        ):
            return service_account.Credentials.from_service_account_info(
                {
                    "type": "service_account",
                    "private_key": auth_config["private_key"],
                    "private_key_id": auth_config["private_key_id"],
                    "token_uri": auth_config["token_uri"],
                    "client_email": auth_config["client_email"],
                    "project_id": auth_config["project_id"],
                },
                scopes=scopes,
            )

        raise ValueError(
            "Invalid auth_config: must be either a service account key (with project_id, "
            "private_key, etc.) or an external_account configuration (with type='external_account')"
        )


def get_project_id_from_credentials(credentials: auth_credentials.Credentials, auth_config: dict[str, Any]) -> str:
    """Get project ID from credentials or config.

    Args:
        credentials: Google auth credentials
        auth_config: The config dict used to create credentials

    Returns:
        Project ID string

    Raises:
        ValueError: If project ID cannot be determined
    """
    # Try to get from credentials first
    if hasattr(credentials, "project_id") and credentials.project_id:
        return credentials.project_id

    # Fall back to auth_config
    if "project_id" in auth_config:
        return auth_config["project_id"]

    # For external accounts with service account impersonation
    if auth_config.get("type") == "external_account" and "service_account_impersonation" in auth_config:
        # Extract project from service account email or impersonation URL
        impersonation_url = auth_config.get("service_account_impersonation_url", "")
        if "/projects/" in impersonation_url:
            parts = impersonation_url.split("/projects/")
            if len(parts) > 1:
                project_part = parts[1].split("/")[0]
                if project_part and project_part != "-":
                    return project_part

    raise ValueError("Could not determine project_id from credentials or configuration")

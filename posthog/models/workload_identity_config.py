"""
Model for storing Workload Identity Federation configuration.

Teams can configure Workload Identity Federation to authenticate with their
Google Cloud resources. This model stores the configuration including the
Workload Identity Pool audience URL.
"""

from django.db import models

from posthog.models.team import Team
from posthog.models.organization import Organization


class WorkloadIdentityConfig(models.Model):
    """
    Configuration for Google Cloud Workload Identity Federation.
    
    This stores the configuration needed for a team to authenticate with
    their Google Cloud resources using Workload Identity Federation.
    """
    
    # Team this configuration belongs to
    team = models.OneToOneField(
        Team,
        on_delete=models.CASCADE,
        related_name="workload_identity_config",
    )
    
    # Google Cloud Workload Identity Pool audience URL
    # Format: //iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID
    audience = models.TextField(
        help_text="Workload Identity Pool audience URL from Google Cloud"
    )
    
    # Google Cloud project ID where resources are located
    google_cloud_project_id = models.CharField(
        max_length=255,
        help_text="Google Cloud project ID for accessing resources"
    )
    
    # Whether this configuration is enabled
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether Workload Identity Federation is enabled for this team"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Who created this configuration
    created_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    
    class Meta:
        indexes = [
            models.Index(fields=["team", "is_enabled"]),
        ]
    
    def __str__(self):
        return f"WorkloadIdentityConfig(team={self.team.name}, project={self.google_cloud_project_id})"
    
    @classmethod
    def get_for_team(cls, team_id: int):
        """Get the active Workload Identity configuration for a team."""
        try:
            return cls.objects.get(team_id=team_id, is_enabled=True)
        except cls.DoesNotExist:
            return None

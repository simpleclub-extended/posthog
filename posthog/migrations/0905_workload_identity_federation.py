# Generated migration for Workload Identity Federation models

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0904_alter_dashboard_creation_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkloadIdentityKey',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key_id', models.CharField(db_index=True, max_length=255, unique=True)),
                ('private_key', models.TextField()),
                ('public_key', models.TextField()),
                ('public_key_n', models.TextField()),
                ('public_key_e', models.TextField(default='AQAB')),
                ('algorithm', models.CharField(default='RS256', max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='workloadidentitykey',
            index=models.Index(fields=['is_active', 'expires_at'], name='posthog_wor_is_acti_idx'),
        ),
        migrations.CreateModel(
            name='WorkloadIdentityConfig',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('audience', models.TextField(help_text='Workload Identity Pool audience URL from Google Cloud')),
                ('google_cloud_project_id', models.CharField(help_text='Google Cloud project ID for accessing resources', max_length=255)),
                ('is_enabled', models.BooleanField(default=True, help_text='Whether Workload Identity Federation is enabled for this team')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('team', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='workload_identity_config', to='posthog.team')),
            ],
        ),
        migrations.AddIndex(
            model_name='workloadidentityconfig',
            index=models.Index(fields=['team', 'is_enabled'], name='posthog_wor_team_id_idx'),
        ),
    ]

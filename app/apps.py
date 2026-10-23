from django.apps import AppConfig
from django.core import checks


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"

    def ready(self):
        from . import signals  # noqa: F401


@checks.register(checks.Tags.database)
def unapplied_migrations(app_configs=None, databases=None, **kwargs):
    """Warn (clearly) when the database has not been migrated."""
    import sys

    from django.db import DatabaseError, connection

    if len(sys.argv) > 1 and sys.argv[1] in ("migrate", "makemigrations", "test", "sqlmigrate", "showmigrations", "flush"):
        return []
    from django.db.migrations.executor import MigrationExecutor

    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except DatabaseError:
        pending = [("unknown", False)]
    if pending:
        return [checks.Warning(
            "The database has unapplied migrations.",
            hint="Run: python manage.py migrate",
            id="app.W001",
        )]
    return []

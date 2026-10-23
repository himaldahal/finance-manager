"""Security headers and a friendly page for an unmigrated database."""
import logging

logger = logging.getLogger(__name__)

POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
# The bundled Django admin still uses a few inline style attributes.
ADMIN_POLICY = POLICY.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            admin = request.path.startswith("/admin/")
            response["Content-Security-Policy"] = ADMIN_POLICY if admin else POLICY
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


SETUP_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Database not set up - Finance Manager</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{css}">
</head><body>
<main class="auth"><div class="auth-card"><div class="card">
<h1>Database not set up</h1>
<p>The database is missing tables the app needs. Stop the server, run this command in the project folder,
then start the server again:</p>
<p><code>python manage.py migrate</code></p>
<p class="muted small">If you just cloned the project, also copy <code>.env.example</code> to <code>.env</code>.
See the Troubleshooting section of the README.</p>
</div></div></main></body></html>
"""


class DatabaseReadyMiddleware:
    """Show a plain explanation instead of a stack trace when migrations have not been applied.

    The result is cached once the database is ready, so the normal cost is one attribute read.
    """

    ready = False

    def __init__(self, get_response):
        self.get_response = get_response

    @classmethod
    def check_ready(cls):
        from django.db import DatabaseError, connection
        from django.db.migrations.executor import MigrationExecutor

        try:
            executor = MigrationExecutor(connection)
            return not executor.migration_plan(executor.loader.graph.leaf_nodes())
        except DatabaseError:
            return False

    def __call__(self, request):
        cls = type(self)
        if not cls.ready:
            cls.ready = self.check_ready()
            if not cls.ready:
                logger.error("Database not set up: unapplied migrations. Run: python manage.py migrate")
                from django.http import HttpResponse
                from django.templatetags.static import static
                try:
                    css = static("app/css/app.css")
                except ValueError:
                    css = ""
                response = HttpResponse(SETUP_PAGE.format(css=css), status=503, content_type="text/html; charset=utf-8")
                response["Retry-After"] = "60"
                response["Cache-Control"] = "no-store"
                return response
        return self.get_response(request)

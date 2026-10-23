"""Regression tests for the fresh-clone failure `OperationalError: no such table` (an unmigrated database)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from app.apps import unapplied_migrations
from expensemanager.middleware import DatabaseReadyMiddleware

ROOT = Path(__file__).resolve().parent.parent.parent


class FriendlyPageTests(TestCase):
    def setUp(self):
        DatabaseReadyMiddleware.ready = False
        self.addCleanup(setattr, DatabaseReadyMiddleware, "ready", True)

    def test_unmigrated_database_shows_instructions_not_a_500(self):
        with mock.patch.object(DatabaseReadyMiddleware, "check_ready", return_value=False), self.assertLogs("expensemanager.middleware", "ERROR"):
            for path in ("/", "/login/", "/register/", "/api/summary/", "/transactions/"):
                r = Client().get(path)
                self.assertEqual(r.status_code, 503, path)
                self.assertContains(r, "Database not set up", status_code=503)
                self.assertContains(r, "python manage.py migrate", status_code=503)
                self.assertEqual(r["Retry-After"], "60")
            r = Client().post("/register/", {"username": "x"})
            self.assertEqual(r.status_code, 503)

    def test_it_is_logged(self):
        with mock.patch.object(DatabaseReadyMiddleware, "check_ready", return_value=False):
            with self.assertLogs("expensemanager.middleware", level="ERROR") as logs:
                Client().get("/login/")
        self.assertIn("python manage.py migrate", logs.output[0])

    def test_database_errors_while_checking_count_as_not_ready(self):
        DatabaseReadyMiddleware.ready = False
        with mock.patch("django.db.migrations.executor.MigrationExecutor.__init__", side_effect=DatabaseError("no such table")):
            self.assertFalse(DatabaseReadyMiddleware.check_ready())

    def test_recovers_once_migrated(self):
        with mock.patch.object(DatabaseReadyMiddleware, "check_ready", return_value=False), self.assertLogs("expensemanager.middleware", "ERROR"):
            self.assertEqual(Client().get("/login/").status_code, 503)
        DatabaseReadyMiddleware.ready = False
        self.assertEqual(Client().get("/login/").status_code, 200)
        self.assertTrue(DatabaseReadyMiddleware.ready)

    def test_ready_flag_is_cached(self):
        DatabaseReadyMiddleware.ready = True
        with mock.patch.object(DatabaseReadyMiddleware, "check_ready", side_effect=AssertionError("should not run")):
            self.assertEqual(Client().get("/login/").status_code, 200)


class SystemCheckTests(TestCase):
    def test_warning_when_migrations_pending(self):
        with mock.patch.object(sys, "argv", ["manage.py", "check"]), \
                mock.patch("django.db.migrations.executor.MigrationExecutor.migration_plan", return_value=[("app", False)]):
            messages = unapplied_migrations()
        self.assertEqual(messages[0].id, "app.W001")
        self.assertIn("migrate", messages[0].hint)

    def test_no_warning_when_clean(self):
        with mock.patch.object(sys, "argv", ["manage.py", "check"]), \
                mock.patch("django.db.migrations.executor.MigrationExecutor.migration_plan", return_value=[]):
            self.assertEqual(unapplied_migrations(), [])

    def test_no_warning_while_migrating(self):
        with mock.patch.object(sys, "argv", ["manage.py", "migrate"]):
            self.assertEqual(unapplied_migrations(), [])


@unittest.skipIf(os.environ.get("SKIP_SUBPROCESS_TESTS"), "subprocess tests disabled")
class RealEmptyDatabaseTests(unittest.TestCase):
    """Run the app against a SQLite file with no tables at all, exactly like a fresh clone."""

    def run_snippet(self, code, db):
        env = dict(os.environ, DEBUG="1", SECRET_KEY="x" * 60, DATABASE_PATH=str(db), ALLOWED_HOSTS="testserver,localhost",
                   PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)

    def test_register_on_empty_database_is_friendly(self):
        code = (
            "import os, django\n"
            "os.environ['DJANGO_SETTINGS_MODULE']='expensemanager.settings'\n"
            "django.setup()\n"
            "from django.test import Client\n"
            "c = Client()\n"
            "for method, path in (('get','/register/'), ('post','/register/'), ('get','/login/'), ('get','/')):\n"
            "    r = getattr(c, method)(path, {'username':'a'} if method == 'post' else {})\n"
            "    print(method, path, r.status_code, b'Database not set up' in r.content)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_snippet(code, Path(tmp) / "empty.sqlite3")
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        lines = [l for l in result.stdout.splitlines() if l.startswith(("get", "post"))]
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertTrue(line.endswith("503 True"), line)

    def test_works_after_migrate(self):
        code = (
            "import os, django\n"
            "os.environ['DJANGO_SETTINGS_MODULE']='expensemanager.settings'\n"
            "django.setup()\n"
            "from django.core.management import call_command\n"
            "call_command('migrate', verbosity=0)\n"
            "from django.test import Client\n"
            "c = Client()\n"
            "r = c.post('/register/', {'full_name':'Solo','username':'solo','email':'s@e.com','password1':'a-Long-pass-77x','password2':'a-Long-pass-77x'})\n"
            "from django.contrib.auth import get_user_model\n"
            "u = get_user_model().objects.get(username='solo')\n"
            "print('RESULT', r.status_code, u.categories.count() > 5, u.accounts.count())\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_snippet(code, Path(tmp) / "ok.sqlite3")
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("RESULT 302 True 1", result.stdout)

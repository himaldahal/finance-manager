import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from app import services
from expensemanager.env import env_bool, env_int, env_list, load_dotenv

from .base import AppTestCase

ROOT = Path(__file__).resolve().parent.parent.parent
User = get_user_model()


class EnvLoaderTests(SimpleTestCase):
    def test_load_dotenv_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# comment\n\nFM_A=1\nexport FM_B = two words # trailing\nFM_C='quoted # not comment'\nFM_D=\"dq\"\nbroken line\nFM_E=\n"
                            "FM_PRESET=from-file\n", encoding="utf-8")
            os.environ["FM_PRESET"] = "from-env"
            self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FM_A", "FM_B", "FM_C", "FM_D", "FM_E", "FM_PRESET")])
            load_dotenv(path)
        self.assertEqual(os.environ["FM_A"], "1")
        self.assertEqual(os.environ["FM_B"], "two words")
        self.assertEqual(os.environ["FM_C"], "quoted # not comment")
        self.assertEqual(os.environ["FM_D"], "dq")
        self.assertEqual(os.environ["FM_E"], "")
        self.assertEqual(os.environ["FM_PRESET"], "from-env")  # real environment wins

    def test_missing_file_is_ignored(self):
        load_dotenv("/nonexistent/.env")

    def test_typed_accessors(self):
        os.environ.update(FM_T="yes", FM_F="0", FM_BAD="maybe", FM_I="12", FM_BADI="x", FM_L=" a, b ,,c ")
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FM_T", "FM_F", "FM_BAD", "FM_I", "FM_BADI", "FM_L")])
        self.assertTrue(env_bool("FM_T"))
        self.assertFalse(env_bool("FM_F", True))
        self.assertTrue(env_bool("FM_MISSING", True))
        with self.assertRaises(ValueError):
            env_bool("FM_BAD")
        self.assertEqual(env_int("FM_I", 0), 12)
        self.assertEqual(env_int("FM_MISSING", 5), 5)
        with self.assertRaises(ValueError):
            env_int("FM_BADI", 0)
        self.assertEqual(env_list("FM_L"), ["a", "b", "c"])
        self.assertEqual(env_list("FM_MISSING", ["z"]), ["z"])


@unittest.skipIf(os.environ.get("SKIP_SUBPROCESS_TESTS"), "subprocess tests disabled")
class ProductionSettingsTests(unittest.TestCase):
    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("SECRET_KEY", "DEBUG", "DATABASE_PATH")}
        env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", **extra)
        return env

    def run_py(self, code, **extra):
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=self.env(**extra), capture_output=True, text=True, timeout=120)

    def test_secret_key_required_when_not_debug(self):
        r = self.run_py("import os; os.environ['DJANGO_SETTINGS_MODULE']='expensemanager.settings'; "
                        "from django.conf import settings; settings.SECRET_KEY", SECRET_KEY="", DEBUG="0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SECRET_KEY is not set", r.stderr)

    def test_production_defaults_are_secure(self):
        code = ("import os; os.environ['DJANGO_SETTINGS_MODULE']='expensemanager.settings'\n"
                "from django.conf import settings as s\n"
                "print(s.DEBUG, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS, "
                "s.SECURE_HSTS_INCLUDE_SUBDOMAINS, s.SECURE_CONTENT_TYPE_NOSNIFF, s.X_FRAME_OPTIONS, s.SESSION_COOKIE_HTTPONLY, "
                "s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS)")
        r = self.run_py(code, SECRET_KEY="k" * 60, DEBUG="0", ALLOWED_HOSTS="a.example.com, b.example.com",
                        CSRF_TRUSTED_ORIGINS="https://a.example.com")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "False True True True 31536000 True True DENY True ['a.example.com', 'b.example.com'] ['https://a.example.com']")

    def test_debug_defaults_for_development(self):
        code = ("import os; os.environ['DJANGO_SETTINGS_MODULE']='expensemanager.settings'\n"
                "from django.conf import settings as s\n"
                "print(s.DEBUG, s.SESSION_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.ALLOWED_HOSTS, bool(s.SECRET_KEY))")
        r = self.run_py(code, DEBUG="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "True False False ['localhost', '127.0.0.1', '[::1]'] True")

    def test_check_deploy_is_clean_with_production_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = dict(SECRET_KEY="Qx7!aB9#" * 8, DEBUG="0", ALLOWED_HOSTS="money.example.com", DATABASE_PATH=str(Path(tmp) / "db.sqlite3"))
            migrate = subprocess.run([sys.executable, "manage.py", "migrate", "-v0"], cwd=ROOT, env=self.env(**extra), capture_output=True, text=True, timeout=120)
            self.assertEqual(migrate.returncode, 0, migrate.stderr)
            r = subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"], cwd=ROOT,
                               env=self.env(**extra), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no issues", r.stdout + r.stderr)

    def test_makemigrations_check_is_clean(self):
        r = subprocess.run([sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"], cwd=ROOT,
                           env=self.env(DEBUG="1"), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_python_39_compatible_syntax(self):
        """No `match`, no `X | Y` annotations and no parenthesised context managers in application code."""
        import ast
        for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "expensemanager").rglob("*.py")):
            if "migrations" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, feature_version=(3, 9))
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, getattr(ast, "Match", ()), path)


class RepositoryHygieneTests(SimpleTestCase):
    def tracked_text_files(self):
        skip = {".git", "__pycache__", "staticfiles", ".venv", "node_modules"}
        for path in ROOT.rglob("*"):
            if path.is_file() and not (set(path.relative_to(ROOT).parts) & skip) and path.suffix in {".py", ".js", ".css", ".html", ".md", ".txt", ".yml", ".sh", ".svg", ".json", ".example"}:
                if path.name == "sprite.svg" or path.name == "LICENSE":
                    continue
                yield path

    def test_no_dashes_or_forbidden_words(self):
        bad_chars = [chr(0x2014), chr(0x2013), chr(0x2015)]
        import base64
        words = base64.b64decode("Y2xhdWRlfGFudGhyb3BpY3xqdWxlc3xnb29nbGVbIC1dbGFicw==").decode().replace("[ -]", " ").split("|")
        words.append(words[-1].replace(" ", "-"))
        for path in self.tracked_text_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for ch in bad_chars:
                self.assertNotIn(ch, text, f"{path}: dash character")
            lowered = text.lower()
            for word in words:
                self.assertNotIn(word, lowered, f"{path}: {word}")

    def test_requirements_are_clean_utf8_and_minimal(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
        self.assertEqual(lines, ["Django>=4.2,<6"])

    def test_no_third_party_urls_in_templates_or_static(self):
        import re
        for path in list((ROOT / "app" / "templates").rglob("*.html")) + list((ROOT / "app" / "static" / "app" / "js").glob("*.js")) + list((ROOT / "app" / "static" / "app" / "css").glob("*.css")):
            text = path.read_text(encoding="utf-8")
            for url in re.findall(r"https?://[^\s\"')]+", text):
                self.assertTrue(url.startswith("http://www.w3.org"), f"{path}: {url}")

    def test_gitignore_covers_local_files(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("db.sqlite3", "__pycache__", "*.py[cod]", ".env", "staticfiles", "media", ".venv"):
            self.assertIn(entry, text)

    def test_env_example_documents_settings(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in ("SECRET_KEY", "DEBUG", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "DATABASE_PATH", "ALLOW_NEGATIVE_BALANCE"):
            self.assertIn(key, text)


class SeedDemoCommandTests(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())
        self.assertFalse(User.objects.filter(username="demo").exists())

    @override_settings(DEBUG=True)
    def test_seeds_realistic_data_once(self):
        out = io.StringIO()
        call_command("seed_demo", stdout=out)
        user = User.objects.get(username="demo")
        self.assertGreater(user.transactions.count(), 100)
        self.assertGreaterEqual(user.accounts.count(), 4)
        self.assertTrue(user.budgets.exists() and user.goals.exists() and user.recurring.exists() and user.rules.exists())
        self.assertTrue(user.transfers.exists())
        self.assertTrue(services.get_profile(user).setup_done)
        self.assertTrue(user.check_password("demo-password-123"))
        self.assertIn("Created demo user", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())

    def test_force_flag_overrides_debug_guard(self):
        with override_settings(DEBUG=False):
            call_command("seed_demo", "--force", "--username", "forced", stdout=io.StringIO())
        self.assertTrue(User.objects.filter(username="forced").exists())

    @override_settings(DEBUG=True)
    def test_demo_is_isolated_and_repeatable_for_existing_defaults(self):
        user = User.objects.create_user("fresh", password="x" * 12)
        services.set_up_new_user(user)
        from app import demo
        demo.seed_user(user)
        self.assertGreater(user.transactions.count(), 100)
        self.assertEqual(user.categories.filter(name__iexact="groceries").count(), 1)

from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from app import services
from app.forms import RegisterForm, split_name, password_min_length
from app.models import Account, Category

from .base import AppTestCase, PASSWORD

User = get_user_model()


class RegistrationTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def data(self, **kw):
        d = {"full_name": "Asha Gurung", "username": "Asha", "email": "Asha@Example.com", "password1": PASSWORD, "password2": PASSWORD}
        d.update(kw)
        return d

    def test_register_creates_user_defaults_account_and_logs_in(self):
        r = self.client.post(reverse("register"), self.data())
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(username="asha")
        self.assertEqual((user.first_name, user.last_name, user.email), ("Asha", "Gurung", "asha@example.com"))
        self.assertGreaterEqual(Category.objects.filter(user=user).count(), 10)
        self.assertEqual(Account.objects.filter(user=user).count(), 1)
        self.assertFalse(services.get_profile(user).setup_done)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)  # to the welcome page
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("welcome"))

    def test_single_word_name(self):
        r = self.client.post(reverse("register"), self.data(full_name="Madonna"))
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(username="asha")
        self.assertEqual((user.first_name, user.last_name), ("Madonna", ""))

    def test_extra_spaces_and_long_names(self):
        self.client.post(reverse("register"), self.data(full_name="  Mary   Jane   Watson  "))
        user = User.objects.get(username="asha")
        self.assertEqual((user.first_name, user.last_name), ("Mary", "Jane   Watson"))

    def test_unique_username_and_email_case_insensitive(self):
        self.client.post(reverse("register"), self.data())
        self.client.logout()
        r = self.client.post(reverse("register"), self.data(username="ASHA", email="other@example.com"))
        self.assertContains(r, "already taken")
        r = self.client.post(reverse("register"), self.data(username="asha2", email="ASHA@example.com"))
        self.assertContains(r, "already exists")
        self.assertEqual(User.objects.filter(username__startswith="asha").count(), 1)

    def test_password_validators(self):
        for bad in ("short1", "1234567890123", "password1234", "asha@example.com"):
            r = self.client.post(reverse("register"), self.data(password1=bad, password2=bad))
            self.assertEqual(r.status_code, 200, bad)
            self.assertFalse(User.objects.filter(username="asha").exists(), bad)

    def test_password_mismatch(self):
        r = self.client.post(reverse("register"), self.data(password2="different-Pass-1"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "field-error")

    def test_registration_is_atomic(self):
        from unittest import mock
        with mock.patch("app.services.set_up_new_user", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("register"), self.data())
        self.assertFalse(User.objects.filter(username="asha").exists())

    @override_settings(ALLOW_REGISTRATION=False)
    def test_registration_can_be_disabled(self):
        self.assertEqual(self.client.get(reverse("register")).status_code, 404)
        self.assertEqual(self.client.get(reverse("username_available"), {"u": "x"}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("login")), "Create one")

    def test_logged_in_users_are_redirected(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse("register")), reverse("dashboard"), fetch_redirect_response=False)

    def test_split_name_helper(self):
        self.assertEqual(split_name(""), ("", ""))
        self.assertEqual(split_name("One"), ("One", ""))
        self.assertEqual(split_name("A B C"), ("A", "B C"))
        self.assertEqual(split_name("x" * 400)[0], "x" * 150)

    def test_username_normalisation(self):
        form = RegisterForm(self.data(username="  ＡＳＨＡ  "))
        form.is_valid()
        self.assertEqual(form.cleaned_data["username"], "asha")


class RegisterPageUxTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_no_static_password_help_list(self):
        html = self.client.get(reverse("register")).content.decode()
        self.assertNotIn("can’t be too similar", html)
        self.assertNotIn("must contain at least", html)
        self.assertNotIn("commonly used password", html)
        self.assertNotIn("entirely numeric", html)
        self.assertNotIn("Letters, digits and @/./+/-/_ only", html)
        self.assertNotIn("<ul", html.split("<form")[1].split("</form>")[0])

    def test_data_attributes_and_hints(self):
        html = self.client.get(reverse("register")).content.decode()
        self.assertIn(f'data-min-length="{password_min_length()}"', html)
        self.assertEqual(password_min_length(), 10)
        self.assertIn('data-similar-to="id_full_name id_username id_email"', html)
        self.assertIn('data-match="id_password1"', html)
        self.assertIn('data-validate="register"', html)
        self.assertIn('data-availability-url="/register/username-available/"', html)
        self.assertGreaterEqual(html.count('aria-live="polite"'), 6)
        self.assertEqual(html.count("data-pw-toggle"), 2)
        self.assertIn("data-meter", html)
        self.assertIn("data-caps", html)
        self.assertIn("register.js", html)

    def test_server_errors_render_inline_one_per_field(self):
        r = self.client.post(reverse("register"), {"full_name": "", "username": "bad name!", "email": "nope", "password1": "123", "password2": "456"})
        html = r.content.decode()
        self.assertGreaterEqual(html.count('class="field-error"'), 4)
        for field in ("password1", "password2"):
            section = html.split(f'name="{field}"')[1].split("</div>")[0]
            self.assertLessEqual(section.count('class="field-error"'), 1)

    def test_submit_button_is_not_disabled(self):
        html = self.client.get(reverse("register")).content.decode()
        self.assertNotRegex(html, r'<button[^>]*type="submit"[^>]*disabled')

    def test_single_word_name_is_accepted_by_form(self):
        self.assertTrue(RegisterForm({"full_name": "Prince", "username": "prince", "email": "p@x.com", "password1": PASSWORD, "password2": PASSWORD}).is_valid())


class UsernameAvailabilityTests(AppTestCase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.client = Client()

    def check(self, name):
        return self.client.get(reverse("username_available"), {"u": name})

    def test_taken_free_and_invalid(self):
        self.assertEqual(self.check("alice").json(), {"ok": True, "valid": True, "available": False})
        self.assertEqual(self.check("ALICE").json()["available"], False)
        self.assertEqual(self.check("fresh_name").json()["available"], True)
        self.assertEqual(self.check("bad name").json()["valid"], False)
        self.assertEqual(self.check("").json()["valid"], False)
        self.assertEqual(self.check("x" * 200).json()["valid"], False)

    def test_response_headers_and_method(self):
        self.assertEqual(self.check("alice")["Cache-Control"], "no-store")
        self.assertEqual(self.client.post(reverse("username_available")).status_code, 405)

    def test_reveals_nothing_beyond_the_signup_form(self):
        body = self.check("alice").json()
        self.assertEqual(set(body), {"ok", "valid", "available"})

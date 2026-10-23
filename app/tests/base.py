import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from app import services
from app.models import Account, Category, Transaction

User = get_user_model()
PASSWORD = "correct-Horse-battery-42"


def today():
    return timezone.localdate()


class AppTestCase(TestCase):
    """Helpers shared by the app tests."""

    password = PASSWORD

    def make_user(self, username="alice", setup=True, **extra):
        user = User.objects.create_user(username, f"{username}@example.com", PASSWORD, first_name=username.title(), **extra)
        services.set_up_new_user(user)
        if setup:
            profile = services.get_profile(user)
            profile.setup_done = True
            profile.save()
            services.forget_profile(user)
        return user

    def setUp(self):
        super().setUp()
        self.user = self.make_user("alice")
        self.other = self.make_user("mallory")
        self.client.force_login(self.user)

    # --- data helpers
    def cat(self, user=None, name="Groceries"):
        return Category.objects.get(user=user or self.user, name=name)

    def account(self, user=None):
        return services.default_account(user or self.user)

    def tx(self, user=None, amount="10.00", kind="expense", name="Item", category=None, date=None, **extra):
        user = user or self.user
        category = category or self.cat(user, "Salary" if kind == "income" else "Groceries")
        extra.setdefault("account", services.default_account(user))
        return Transaction.objects.create(user=user, name=name, amount=Decimal(amount), kind=kind, category=category,
                                          date=date or today(), **extra)

    # --- http helpers
    def payload(self, **overrides):
        data = {"name": "Lunch", "amount": "12.50", "date": today().isoformat(), "kind": "expense",
                "category": self.cat().pk, "note": "", "payee": "", "tags": []}
        data.update(overrides)
        return data

    def post(self, url, data=None, client=None):
        return (client or self.client).post(url, json.dumps(data if data is not None else {}), content_type="application/json")

    def delete(self, url, client=None):
        return (client or self.client).delete(url)

    def json(self, response):
        return json.loads(response.content)

    def csrf_client(self, user=None):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user or self.user)
        return client

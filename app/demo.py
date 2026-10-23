"""Realistic sample data for one user (used by seed_demo and the "load sample data" button)."""
import datetime
import random
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from . import services
from .models import (
    Account, Budget, Category, CategoryRule, Contribution, Goal, LedgerEntry, Person, RecurringTransaction, Tag, Transaction,
    Transfer,
)

D = Decimal

PAYEES = {
    "Groceries": ["Bhat-Bhateni", "Big Mart", "Local market"],
    "Transport": ["Pathao", "City bus", "Petrol pump"],
    "Dining out": ["Cafe Mitini", "Thakali Kitchen", "Momo Hut"],
    "Shopping": ["Daraz", "Fashion Street", "Book House"],
    "Utilities": ["NEA", "Khanepani"],
    "Health": ["City Pharmacy", "Medicare Clinic"],
    "Gifts": ["Gift Corner"],
}


@db_transaction.atomic
def seed_user(user, seed=7):
    rng = random.Random(seed)
    today = timezone.localdate()
    services.set_up_new_user(user)
    main = services.default_account(user)
    if not main.transactions.exists():
        main.opening_balance = D("60000.00")
        main.save()
    def account(name, kind, opening="0"):
        found = Account.objects.filter(user=user, name__iexact=name).first()
        return found or Account.objects.create(user=user, name=name, type=kind, opening_balance=D(opening))

    def category(name, kind, color, icon, parent=None):
        found = Category.objects.filter(user=user, name__iexact=name).first()
        return found or Category.objects.create(user=user, name=name, kind=kind, color=color, icon=icon, parent=parent)

    cash = account("Cash", "cash", "5000.00")
    wallet = account("Mobile wallet", "wallet", "2500.00")
    credit = account("Credit card", "credit")
    savings = account("Savings", "bank", "40000.00")

    cats = {c.name: c for c in user.categories.all()}
    for name, kind, color, icon in (("Internet", "expense", "blue", "wifi"), ("Freelance", "income", "olive", "briefcase"),
                                    ("Gifts", "expense", "plum", "gift")):
        cats[name] = category(name, kind, color, icon)
    cats["Coffee"] = category("Coffee", "expense", "amber", "coffee", cats["Dining out"])
    cats["Fuel"] = category("Fuel", "expense", "red", "fuel", cats["Transport"])

    tags = {n: (Tag.objects.filter(user=user, name__iexact=n).first() or Tag.objects.create(user=user, name=n))
            for n in ("work", "weekend", "essential", "treat")}
    for pattern, cat in (("bhat", "Groceries"), ("pathao", "Transport"), ("daraz", "Shopping"), ("cafe", "Coffee")):
        CategoryRule.objects.create(user=user, pattern=pattern, category=cats[cat])

    def add(day, name, kind, category, amount, payee="", account=main, tag_names=(), note="", recurring=None):
        if day > today:
            return None
        tx = Transaction.objects.create(
            user=user, name=name, kind=kind, category=cats[category], amount=D(amount).quantize(D("0.01")), date=day,
            payee=payee, account=account, note=note, recurring=recurring, recurring_date=day if recurring else None)
        if tag_names:
            tx.tags.set([tags[t] for t in tag_names])
        return tx

    rent = RecurringTransaction.objects.create(
        user=user, name="Apartment rent", amount=D("22000"), kind="expense", category=cats["Rent"], payee="Landlord",
        account=main, frequency="monthly", start_date=services.add_months(today.replace(day=1), -11),
        next_due=services.add_months(today.replace(day=1), 1))
    net = RecurringTransaction.objects.create(
        user=user, name="Internet plan", amount=D("1500"), kind="expense", category=cats["Internet"], payee="WorldLink",
        account=main, frequency="monthly", start_date=services.add_months(today.replace(day=5), -11),
        next_due=today.replace(day=5) if today.day < 5 else services.add_months(today.replace(day=5), 1))
    weekly = RecurringTransaction.objects.create(
        user=user, name="Weekly vegetables", amount=D("1200"), kind="expense", category=cats["Groceries"],
        payee="Local market", account=cash, frequency="weekly", start_date=today - datetime.timedelta(days=2),
        next_due=today + datetime.timedelta(days=5))
    RecurringTransaction.objects.create(
        user=user, name="Gym membership", amount=D("2500"), kind="expense", category=cats["Health"],
        account=main, frequency="monthly", start_date=today.replace(day=1),
        next_due=services.add_months(today.replace(day=1), 1), active=False)
    add(today - datetime.timedelta(days=2), "Weekly vegetables", "expense", "Groceries", 1200, "Local market", cash, recurring=weekly)

    first = services.add_months(today.replace(day=1), -11)
    for i in range(12):
        month = services.add_months(first, i)
        d = lambda n: month.replace(day=n)  # noqa: E731
        add(d(1), "Apartment rent", "expense", "Rent", 22000, "Landlord", recurring=rent, tag_names=("essential",))
        add(d(5), "Internet plan", "expense", "Internet", 1500, "WorldLink", recurring=net, tag_names=("essential",))
        add(d(1), "Monthly salary", "income", "Salary", 72000 + (i // 4) * 3000, "Employer")
        if rng.random() < 0.55:
            add(d(14), "Freelance project", "income", "Freelance", rng.randrange(8000, 26000, 500), "Client", tag_names=("work",))
        add(d(9), "Electricity and water", "expense", "Utilities", rng.randrange(2200, 4200, 50), rng.choice(PAYEES["Utilities"]),
            tag_names=("essential",))
        for _ in range(rng.randint(4, 6)):
            add(d(rng.randint(2, 27)), rng.choice(["Weekly groceries", "Market run", "Supermarket"]), "expense", "Groceries",
                rng.randrange(1800, 6200, 50), rng.choice(PAYEES["Groceries"]), rng.choice([main, main, cash]))
        for _ in range(rng.randint(2, 4)):
            add(d(rng.randint(2, 27)), rng.choice(["Taxi ride", "Bus pass", "Fuel"]), "expense",
                rng.choice(["Transport", "Fuel"]), rng.randrange(400, 2600, 50), rng.choice(PAYEES["Transport"]), cash)
        for _ in range(rng.randint(3, 6)):
            add(d(rng.randint(2, 27)), rng.choice(["Lunch with friends", "Coffee", "Dinner out"]), "expense",
                rng.choice(["Dining out", "Coffee", "Coffee"]), rng.randrange(150, 3400, 50), rng.choice(PAYEES["Dining out"]),
                wallet, tag_names=rng.choice([(), ("weekend",), ("treat",)]))
        if rng.random() < 0.6:
            add(d(rng.randint(3, 25)), rng.choice(["Clothes", "Headphones", "Books"]), "expense", "Shopping",
                rng.randrange(1500, 9000, 100), rng.choice(PAYEES["Shopping"]), credit, tag_names=("treat",))
        if rng.random() < 0.35:
            add(d(rng.randint(3, 25)), "Pharmacy", "expense", "Health", rng.randrange(500, 3500, 50), rng.choice(PAYEES["Health"]))
        if rng.random() < 0.25:
            add(d(rng.randint(3, 25)), "Birthday gift", "expense", "Gifts", rng.randrange(1000, 4000, 100), "Gift Corner")
        for day, target, amount, note in ((3, cash, "13000", "Cash for the month"), (4, wallet, "9500", "Top up wallet"),
                                          (6, savings, "15000", "Monthly savings"), (28, credit, "3000", "Card repayment")):
            if d(day) <= today:
                Transfer.objects.create(user=user, from_account=main, to_account=target, amount=D(amount), date=d(day), note=note)

    for back in range(0, 7):
        month = services.add_months(today.replace(day=1), -back)
        Budget.objects.update_or_create(user=user, category=None, month=month, defaults={"amount": D("66000"), "warn_percent": 85})
        for name, amount, roll in (("Groceries", 24000, True), ("Dining out", 9000, False), ("Transport", 8000, False),
                                   ("Shopping", 7000, False), ("Utilities", 4000, False), ("Internet", 1500, False)):
            Budget.objects.update_or_create(user=user, category=cats[name], month=month, defaults={"amount": D(amount), "rollover": roll})

    goal = Goal.objects.create(user=user, name="Emergency fund", target_amount=D("150000"), account=main,
                               target_date=today + datetime.timedelta(days=300))
    laptop = Goal.objects.create(user=user, name="New laptop", target_amount=D("120000"),
                                 target_date=today + datetime.timedelta(days=170))
    Goal.objects.create(user=user, name="Trip to Pokhara", target_amount=D("45000"), target_date=today + datetime.timedelta(days=90))
    for i in range(8):
        Contribution.objects.create(goal=goal, amount=D("8000"), date=services.add_months(today.replace(day=15), -i) if i or today.day >= 15 else today)
    for i in range(3):
        Contribution.objects.create(goal=laptop, amount=D("12000"), date=services.add_months(today.replace(day=20), -i - 1))
    trip = Goal.objects.get(user=user, name="Trip to Pokhara")
    Contribution.objects.create(goal=trip, amount=D("9000"), date=today - datetime.timedelta(days=12))
    sita = Person.objects.create(user=user, name="Sita Rai")
    ram = Person.objects.create(user=user, name="Ram Thapa")
    for person, kind, amount, back, note, due in (
            (sita, "lent", "6000", 14, "Lent for her course fee", 20), (sita, "paid_me", "1500", 6, "Partial repayment", None),
            (sita, "split_me", "1200", 3, "Dinner, she owes her half", None), (ram, "borrowed", "2500", 9, "Borrowed for a taxi and lunch", 12)):
        sign = 1 if kind in ("lent", "split_me", "paid_them") else -1
        LedgerEntry.objects.create(person=person, kind=kind, amount=sign * D(amount), description=note,
                                   date=today - datetime.timedelta(days=back),
                                   due_date=today + datetime.timedelta(days=due) if due else None)
    profile = services.get_profile(user)
    profile.setup_done = True
    profile.save(update_fields=["setup_done"])
    return user

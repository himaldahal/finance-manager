from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.exceptions import ValidationError
from decimal import Decimal
import json

from .models import Transaction, TransactionType, Balance
from .forms import RegisterForm # For testing registration directly if needed

class ViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        self.category = TransactionType.objects.create(name='View Test Category', added_by=self.user)
        
        # Log in the user for views that require authentication
        self.client.login(username='testuser', password='password123')

        # Initial balance for some tests
        Balance.objects.create(balance_of=self.user, balance=Decimal('100.00'))


    def test_transaction_create_view_insufficient_balance(self):
        """Test transaction_create_view for insufficient balance (JSON response)."""
        # User has 100.00
        response = self.client.post(reverse('transaction_create'), {
            'name': 'Overdraft Expense',
            'amount': '150.00', # Exceeds balance
            'transaction_type': 'expense',
            'category': self.category.id,
            'date': '2023-01-01', # Ensure all required fields are present
            'remarks': 'Attempting overdraft'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest') # Simulate AJAX request
        
        self.assertEqual(response.status_code, 200) # View returns 200 for JsonResponse
        json_response = response.json()
        self.assertFalse(json_response['success'])
        self.assertIn('message', json_response) # The refactored view returns 'message'
        self.assertEqual(json_response['message'], "Insufficient balance to complete this transaction.")

        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('100.00')) # Balance should be unchanged


    def test_user_registration_view(self):
        """Test user registration via the register view."""
        # Log out the current user to test registration
        self.client.logout()

        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'newpassword123',
            'password2': 'newpassword123',
            'first_name': 'New',
            'last_name': 'User'
        }, follow=True) # follow=True to follow the redirect to home

        self.assertEqual(response.status_code, 200) # Should redirect to home page (status 200 after redirect)
        self.assertTrue(User.objects.filter(username='newuser').exists())
        new_user = User.objects.get(username='newuser')
        self.assertTrue(new_user.check_password('newpassword123'))
        self.assertEqual(new_user.first_name, 'New')
        
        # Check if balance object was created
        self.assertTrue(Balance.objects.filter(balance_of=new_user).exists())
        user_balance = Balance.objects.get(balance_of=new_user)
        self.assertEqual(user_balance.balance, Decimal('0.00'))

        # Clean up new user
        new_user.delete()

    def test_user_login_view_success(self):
        """Test successful user login."""
        # Log out first if a user is logged in from setUp
        self.client.logout()
        
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'password123'
        }, follow=True)
        
        self.assertEqual(response.status_code, 200) # Successful login redirects to home (or a configured page)
        self.assertTrue(response.context['user'].is_authenticated) # Check user in context
        self.assertEqual(response.context['user'].username, 'testuser')


    def test_user_login_view_failure(self):
        """Test failed user login with incorrect credentials."""
        self.client.logout() # Ensure no user is logged in
        
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'wrongpassword'
        }, follow=True)
        
        self.assertEqual(response.status_code, 200) # Login page re-renders with errors
        self.assertFalse(response.context['user'].is_authenticated)
        # Check for form errors if your login view adds them to context
        # For CustomAuthenticationForm, errors are in form.errors
        self.assertTrue(response.context['form'].errors)


    def test_delete_transaction_view_csrf_failure(self):
        """Test delete_transaction view for CSRF protection failure."""
        # User has 100.00. Create a transaction to delete.
        transaction_to_delete = Transaction.objects.create(
            name='Test Deletion',
            amount=Decimal('10.00'),
            transaction_type='expense', # Balance becomes 90
            transaction_of=self.user,
            category=self.category
        )
        self.client.login(username='testuser', password='password123') # Ensure user is logged in

        # Attempt DELETE request without CSRF token.
        # Django's test client enforces CSRF by default for POST.
        # For DELETE via AJAX style, it might also. We can use enforce_csrf_checks=True on client.
        self.client.enforce_csrf_checks = True
        delete_url = reverse('delete_transaction', args=[transaction_to_delete.id])
        
        # Simulate a POST request as AJAX DELETE is often done via POST with a _method or specific header
        # Or directly use client.delete() if your routing/JS handles it.
        # For this test, a direct POST to the URL without CSRF should fail if CSRF middleware is active.
        # The view itself isn't CSRF exempt anymore.
        response = self.client.post(delete_url) # No CSRF token by default with enforce_csrf_checks
        
        self.assertEqual(response.status_code, 403) # Forbidden due to CSRF
        self.assertTrue(Transaction.objects.filter(pk=transaction_to_delete.pk).exists()) # Still exists
        self.client.enforce_csrf_checks = False # Reset for other tests


    def test_delete_transaction_view_csrf_success(self):
        """Test delete_transaction view with CSRF token (implicitly handled by test client for POST)."""
        # Initial balance 100.
        transaction_to_delete = Transaction.objects.create(
            name='Test Deletion Success',
            amount=Decimal('20.00'),
            transaction_type='expense', # Balance becomes 80
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('80.00'))

        self.client.login(username='testuser', password='password123')
        delete_url = reverse('delete_transaction', args=[transaction_to_delete.id])
        
        # Django test client automatically includes CSRF token for POST requests
        # if CsrfViewMiddleware is enabled and client is not enforcing checks explicitly to fail.
        # The view expects a DELETE method.
        response = self.client.delete(delete_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest') # Simulate AJAX
        
        self.assertEqual(response.status_code, 200)
        json_response = response.json()
        self.assertTrue(json_response['success'])
        
        self.assertFalse(Transaction.objects.filter(pk=transaction_to_delete.pk).exists())
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('100.00')) # 80 + 20 (reverted expense)

    def test_transaction_update_view_permission_denied_ajax(self):
        """Test TransactionUpdateView dispatch for permission denied (AJAX)."""
        other_user = User.objects.create_user(username='otheruser', password='password')
        transaction_of_other_user = Transaction.objects.create(
            name='Other User Tx',
            amount=Decimal('50.00'),
            transaction_type='income',
            transaction_of=other_user,
            category=self.category # Assuming category can be shared or create one for other_user
        )

        self.client.login(username='testuser', password='password123') # Logged in as 'testuser'
        update_url = reverse('transaction_update', args=[transaction_of_other_user.pk])
        
        response = self.client.get(update_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest') # AJAX get
        self.assertEqual(response.status_code, 200) # JsonResponse returns 200
        json_data = response.json()
        self.assertFalse(json_data['success'])
        self.assertEqual(json_data['errors'], 'Permission denied. You do not have permission to edit this transaction.')

        response = self.client.post(update_url, {'name': 'Trying to update'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest') # AJAX post
        self.assertEqual(response.status_code, 200) # JsonResponse returns 200
        json_data = response.json()
        self.assertFalse(json_data['success'])
        self.assertEqual(json_data['errors'], 'Permission denied. You do not have permission to edit this transaction.')
        
        other_user.delete() # Clean up


    def test_transaction_update_view_permission_denied_non_ajax(self):
        """Test TransactionUpdateView dispatch for permission denied (non-AJAX)."""
        other_user = User.objects.create_user(username='anotheruser', password='password')
        transaction_of_other_user = Transaction.objects.create(
            name='Another User Tx',
            amount=Decimal('70.00'),
            transaction_type='income',
            transaction_of=other_user,
            category=self.category
        )

        self.client.login(username='testuser', password='password123')
        update_url = reverse('transaction_update', args=[transaction_of_other_user.pk])
        
        response = self.client.get(update_url) # Non-AJAX GET
        self.assertEqual(response.status_code, 403) # HttpResponseForbidden
        self.assertContains(response, "You do not have permission to edit this transaction.", status_code=403)

        response = self.client.post(update_url, {'name': 'Trying to update non-ajax'}) # Non-AJAX POST
        self.assertEqual(response.status_code, 403) # HttpResponseForbidden
        self.assertContains(response, "You do not have permission to edit this transaction.", status_code=403)

        other_user.delete() # Clean up


    def tearDown(self):
        # Clean up created objects if not handled by on_delete cascade
        # User and Category are created in setUp, Balance might be created per test.
        # Transactions are created per test.
        # Balances associated with self.user will be deleted when self.user is deleted.
        self.user.delete() 
        self.category.delete()
        # Any other users created in specific tests are deleted there.
        # Transactions linked to self.user or self.category will also be cascaded.
        # Balances linked to other_user are handled when other_user is deleted.

# To run these tests: python manage.py test app
# Ensure your settings.py has the app listed and database configured for tests.
# Ensure URLs for 'transaction_create', 'register', 'login', 'delete_transaction', 'transaction_update' are correctly named.

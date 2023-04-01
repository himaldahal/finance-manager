from django.shortcuts import redirect
from django.urls import reverse

class AuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and (request.path == reverse('login') or request.path == reverse('register') or  request.path.startswith('/captcha/')):
                return redirect('home')

        if not request.user.is_authenticated and (request.path != reverse('login') and request.path != reverse('register') and not request.path.startswith('/captcha/')):
            return redirect('login')

        response = self.get_response(request)
        return response
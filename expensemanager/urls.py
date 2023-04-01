from django.contrib import admin
from django.urls import path,include
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.conf.urls.static import static
from django.conf import settings

def logout_view(request):
    logout(request)
    return redirect('/')
    
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('app.urls')),
    path('captcha/', include('captcha.urls'),name="captcha"),
    
    path('logout/', logout_view, name='logout'),
]
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
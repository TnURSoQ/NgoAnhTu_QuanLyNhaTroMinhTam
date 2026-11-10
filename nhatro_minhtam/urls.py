from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts import views as accounts_views
from accounts.forms import ChangePasswordForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', accounts_views.home, name='home'),
    path('dang-nhap/', accounts_views.RememberLoginView.as_view(), name='login'),
    path('dang-xuat/', auth_views.LogoutView.as_view(), name='logout'),
    path('doi-mat-khau/', auth_views.PasswordChangeView.as_view(
        form_class=ChangePasswordForm), name='password_change'),
    path('doi-mat-khau/xong/', auth_views.PasswordChangeDoneView.as_view(),
         name='password_change_done'),
    path('phong/', include('rooms.owner_urls')),
    path('nguoi-thue/', include('accounts.owner_urls')),
    path('hoa-don/', include('billing.urls')),
    path('hop-dong/', include('rooms.urls')),
    path('', include('reports.urls')),
]
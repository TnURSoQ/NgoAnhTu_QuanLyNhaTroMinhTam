from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts import views as accounts_views
from accounts.forms import ChangePasswordForm, LoginForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', accounts_views.home, name='home'),
    path('dang-nhap/', auth_views.LoginView.as_view(
        authentication_form=LoginForm, redirect_authenticated_user=True), name='login'),
    path('dang-xuat/', auth_views.LogoutView.as_view(), name='logout'),
    path('doi-mat-khau/', auth_views.PasswordChangeView.as_view(
        form_class=ChangePasswordForm), name='password_change'),
    path('doi-mat-khau/xong/', auth_views.PasswordChangeDoneView.as_view(),
         name='password_change_done'),
    path('hoa-don/', include('billing.urls')),
    path('hop-dong/', include('rooms.urls')),
]
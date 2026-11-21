from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from accounts import views as accounts_views
from accounts.forms import ChangePasswordForm
from accounts.identity_views import identity_image
from billing import views as billing_views

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
    path('phong-cua-toi/', billing_views.my_room, name='my_room'),
    path('thong-tin-ca-nhan/', accounts_views.my_profile, name='my_profile'),
    path('giay-to/<uuid:reference>/<str:side>/', identity_image, name='identity_image'),
    path('lich-hen/', include('rooms.appointment_urls')),
    path('nguoi-thue/', include('accounts.owner_urls')),
    path('hoa-don/', include('billing.owner_urls')),
    path('hoa-don-cua-toi/', include('billing.urls')),
    path('cau-hinh/', include('billing.settings_urls')),
    path('hop-dong/', include('rooms.contract_urls')),
    path('hop-dong-cua-toi/', include('rooms.urls')),
    path('', include('support.urls')),
    path('', include('rooms.cooccupant_urls')),
    path('', include('rooms.public_urls')),
    path('', include('reports.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

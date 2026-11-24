from django.urls import path

from . import owner_views as views
from .identity_exports import export_identities

urlpatterns = [
    path('', views.tenant_list, name='tenant_list'),
    path('xuat-ho-so/', export_identities, name='identity_export'),
    path('them/', views.TenantCreateView.as_view(), name='tenant_create'),
    path('<int:pk>/', views.tenant_detail, name='tenant_detail'),
    path('<int:pk>/sua/', views.TenantUpdateView.as_view(), name='tenant_update'),
    path('<int:pk>/xoa/', views.tenant_delete, name='tenant_delete'),
    path('<int:pk>/dat-lai-mat-khau/', views.tenant_reset_password, name='tenant_reset_password'),
    path('<int:pk>/khoa/', views.tenant_toggle_active, name='tenant_toggle_active'),
]

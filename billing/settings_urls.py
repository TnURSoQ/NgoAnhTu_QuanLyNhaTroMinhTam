from django.urls import path

from . import owner_views as views

urlpatterns = [
    path('', views.billing_settings, name='billing_settings'),
    path('dich-vu/<int:pk>/sua/', views.service_edit, name='service_edit'),
    path('dich-vu/<int:pk>/xoa/', views.service_delete, name='service_delete'),
]

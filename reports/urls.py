from django.urls import path

from . import views

urlpatterns = [
    path('tong-quan/', views.overview, name='owner_dashboard'),
    path('bao-cao/', views.dashboard, name='report_dashboard'),
]
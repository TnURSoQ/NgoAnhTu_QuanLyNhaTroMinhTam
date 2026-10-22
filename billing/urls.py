from django.urls import path

from . import views

urlpatterns = [
    path('', views.my_invoices, name='my_invoices'),
    path('<int:pk>/', views.my_invoice_detail, name='my_invoice_detail'),
    path('thanh-toan/', views.my_payments, name='my_payments'),
]
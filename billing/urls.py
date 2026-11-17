from django.urls import path

from . import views

urlpatterns = [
    path('', views.my_invoices, name='my_invoices'),
    path('<int:pk>/', views.my_invoice_detail, name='my_invoice_detail'),
    path('<int:pk>/bao-chuyen-khoan/', views.report_transfer, name='report_transfer'),
    path('thanh-toan/', views.my_payments, name='my_payments'),
]

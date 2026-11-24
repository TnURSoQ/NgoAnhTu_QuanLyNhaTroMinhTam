from django.urls import path

from . import views

urlpatterns = [
    path('', views.my_invoices, name='my_invoices'),
    path('<int:pk>/', views.my_invoice_detail, name='my_invoice_detail'),
    path('<int:pk>/in/', views.my_invoice_print, name='my_invoice_print'),
    path('<int:pk>/bao-chuyen-khoan/', views.report_transfer, name='report_transfer'),
    path('thanh-toan/', views.my_payments, name='my_payments'),
    path('thanh-toan/<int:pk>/', views.my_payment_detail, name='my_payment_detail'),
    path('thanh-toan/<int:pk>/in/', views.my_payment_print, name='my_payment_print'),
]

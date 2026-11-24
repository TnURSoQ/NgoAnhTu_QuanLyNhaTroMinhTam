from django.urls import path

from . import owner_views as views

urlpatterns = [
    path('', views.invoice_list, name='invoice_list'),
    path('tao/', views.invoice_create, name='invoice_create'),
    path('nhap/', views.invoice_drafts, name='invoice_drafts'),
    path('nhap/tao/', views.invoice_generate_drafts, name='invoice_generate_drafts'),
    path('<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('<int:pk>/in/', views.invoice_print, name='invoice_print'),
    path('<int:pk>/xoa/', views.invoice_delete, name='invoice_delete'),
    path('thanh-toan/<int:pk>/xoa/', views.payment_delete, name='payment_delete'),
    path('thanh-toan/<int:pk>/dieu-chinh/', views.payment_correct, name='payment_correct'),
    path('bao-chuyen-khoan/<int:pk>/xac-nhan/', views.payment_notice_confirm, name='payment_notice_confirm'),
    path('bao-chuyen-khoan/<int:pk>/tu-choi/', views.payment_notice_reject, name='payment_notice_reject'),
]

from django.urls import path

from . import contract_views as views

urlpatterns = [
    path('', views.contract_list, name='contract_list'),
    path('them/', views.contract_create, name='contract_create'),
    path('<int:pk>/', views.contract_detail, name='contract_detail'),
    path('<int:pk>/gia-han/', views.contract_renew, name='contract_renew'),
    path('<int:pk>/thu-coc/', views.contract_deposit_receive, name='contract_deposit_receive'),
    path('<int:pk>/hoan-coc/', views.contract_deposit_refund, name='contract_deposit_refund'),
    path('<int:pk>/doi-tru-coc/<int:invoice_pk>/', views.contract_deposit_apply, name='contract_deposit_apply'),
    path('<int:pk>/tra-phong/', views.contract_checkout, name='contract_checkout'),
    path('<int:pk>/chuyen-phong/', views.contract_transfer, name='contract_transfer'),
]

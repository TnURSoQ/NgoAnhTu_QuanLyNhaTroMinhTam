from django.urls import path

from . import contract_views as views

urlpatterns = [
    path('', views.contract_list, name='contract_list'),
    path('them/', views.contract_create, name='contract_create'),
    path('<int:pk>/', views.contract_detail, name='contract_detail'),
    path('<int:pk>/gia-han/', views.contract_renew, name='contract_renew'),
    path('<int:pk>/tra-phong/', views.contract_checkout, name='contract_checkout'),
    path('<int:pk>/chuyen-phong/', views.contract_transfer, name='contract_transfer'),
]
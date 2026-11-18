from django.urls import path

from . import views


urlpatterns = [
    path('sua-chua-cua-toi/', views.my_maintenance_requests, name='my_maintenance_requests'),
    path('sua-chua-cua-toi/gui/', views.maintenance_create, name='maintenance_create'),
    path('sua-chua-cua-toi/<int:pk>/da-gui/', views.maintenance_sent, name='maintenance_sent'),
    path('sua-chua-cua-toi/<int:pk>/', views.my_maintenance_detail, name='my_maintenance_detail'),
    path('sua-chua-cua-toi/<int:pk>/huy/', views.maintenance_cancel, name='maintenance_cancel'),
    path('sua-chua/', views.maintenance_list, name='maintenance_list'),
    path('sua-chua/<int:pk>/', views.maintenance_detail, name='maintenance_detail'),
    path('sua-chua/<int:pk>/trang-thai/', views.maintenance_set_status, name='maintenance_set_status'),
    path('thong-bao/', views.announcement_list, name='announcement_list'),
    path('thong-bao/them/', views.announcement_create, name='announcement_create'),
    path('thong-bao/<int:pk>/sua/', views.announcement_update, name='announcement_update'),
    path('thong-bao/<int:pk>/an-hien/', views.announcement_toggle, name='announcement_toggle'),
    path('thong-bao/<int:pk>/xoa/', views.announcement_delete, name='announcement_delete'),
]

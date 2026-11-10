from django.urls import path

from . import owner_views as views

urlpatterns = [
    path('', views.room_list, name='room_list'),
    path('them/', views.RoomCreateView.as_view(), name='room_create'),
    path('<int:pk>/', views.room_detail, name='room_detail'),
    path('<int:pk>/sua/', views.RoomUpdateView.as_view(), name='room_update'),
    path('<int:pk>/xoa/', views.room_delete, name='room_delete'),
]
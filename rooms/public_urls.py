from django.urls import path

from . import public_views as views

urlpatterns = [
    path('ve-chung-toi/', views.about, name='public_about'),
    path('phong-tro/', views.room_list, name='public_rooms'),
    path('phong-tro/<int:pk>/', views.room_detail, name='public_room_detail'),
    path('tra-cuu-lich-hen/', views.appointment_lookup, name='appointment_lookup'),
    path('tra-cuu-lich-hen/<str:code>/', views.appointment_status, name='appointment_status'),
    path('tra-cuu-lich-hen/<str:code>/huy/', views.appointment_cancel, name='appointment_cancel'),
]

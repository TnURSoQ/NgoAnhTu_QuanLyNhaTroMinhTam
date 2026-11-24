from django.urls import path

from . import appointment_views as views

urlpatterns = [
    path('', views.appointment_list, name='appointment_list'),
    path('<int:pk>/', views.appointment_detail, name='appointment_detail'),
    path('<int:pk>/trang-thai/', views.appointment_set_status, name='appointment_set_status'),
    path('<int:pk>/doi-lich/', views.appointment_reschedule, name='appointment_reschedule'),
    path('<int:pk>/email/', views.appointment_update_email, name='appointment_update_email'),
    path('<int:pk>/email/gui-lai/', views.appointment_retry_email, name='appointment_retry_email'),
]

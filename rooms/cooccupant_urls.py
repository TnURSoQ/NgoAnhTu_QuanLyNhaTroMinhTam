from django.urls import path

from . import cooccupant_views as views

urlpatterns = [
    path('nguoi-o-cung/', views.my_cooccupants, name='my_cooccupants'),
    path('nguoi-o-cung/gui/', views.cooccupant_create, name='cooccupant_create'),
    path('nguoi-o-cung/<int:pk>/', views.my_cooccupant_detail, name='my_cooccupant_detail'),
    path('nguoi-o-cung/<int:pk>/huy/', views.cooccupant_cancel, name='cooccupant_cancel'),
    path('nguoi-o-cung/<int:previous_pk>/gui-lai/', views.cooccupant_create, name='cooccupant_resubmit'),
    path('duyet-nguoi-o-cung/', views.cooccupant_review_list, name='cooccupant_review_list'),
    path('duyet-nguoi-o-cung/<int:pk>/', views.cooccupant_review, name='cooccupant_review'),
]

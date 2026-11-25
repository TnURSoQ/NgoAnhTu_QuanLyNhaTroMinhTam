from django.urls import path

from . import views
from . import renewal_views

urlpatterns = [
    path('', views.my_contracts, name='my_contracts'),
    path('<int:pk>/', renewal_views.my_contract_detail, name='my_contract_detail'),
    path('<int:pk>/gia-han/', renewal_views.renewal_create, name='my_contract_renew'),
    path('<int:pk>/du-kien-tra-phong/', renewal_views.moveout_create, name='my_contract_moveout'),
    path('<int:pk>/in/', renewal_views.my_contract_print, name='my_contract_print'),
    path('de-nghi/<int:pk>/phan-hoi/', renewal_views.renewal_respond, name='renewal_respond'),
    path('de-nghi/<int:pk>/in/', renewal_views.renewal_print, name='renewal_print'),
    path('du-kien/<int:pk>/phan-hoi/', renewal_views.moveout_respond, name='moveout_respond'),
    path('tai-lieu/<int:pk>/', renewal_views.contract_document_download, name='contract_document_download'),
]

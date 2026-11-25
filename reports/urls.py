from django.urls import path

from . import views
from . import print_views

urlpatterns = [
    path('tong-quan/', views.overview, name='owner_dashboard'),
    path('bao-cao/', views.dashboard, name='report_dashboard'),
    path('bao-cao/excel/', views.dashboard_excel, name='report_excel'),
    path('bao-cao/so-thu.csv', views.cashbook_csv, name='cashbook_csv'),
    path('in/hop-dong/<int:pk>/', print_views.contract_print, name='contract_print'),
    path('in/thanh-toan/<int:pk>/', print_views.payment_print, name='payment_print'),
    path('in/giao-dich-coc/<int:pk>/', print_views.deposit_print, name='deposit_print'),
    path('in/tra-phong/<int:pk>/', print_views.checkout_print, name='checkout_print'),
    path('in/nguoi-dang-o/', print_views.residents_print, name='residents_print'),
    path('in/phong/', print_views.rooms_print, name='rooms_print'),
    path('in/bao-cao/', print_views.report_print, name='report_print'),
    path('in/sua-chua/<int:pk>/', print_views.maintenance_print, name='maintenance_print'),
]

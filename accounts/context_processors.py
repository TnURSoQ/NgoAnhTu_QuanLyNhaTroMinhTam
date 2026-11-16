from django.conf import settings


def site_info(request):
    return {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'Nhà trọ Minh Tâm'),
        'SITE_ADDRESS': getattr(settings, 'SITE_ADDRESS', ''),
        'SITE_PHONE': getattr(settings, 'SITE_PHONE', ''),
    }
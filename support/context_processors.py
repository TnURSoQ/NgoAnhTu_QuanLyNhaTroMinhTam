from .notifications import unread_count


def notification_status(request):
    if not hasattr(request, 'notification_unread_count'):
        request.notification_unread_count = unread_count(request.user)
    return {'notification_unread_count': request.notification_unread_count}

from django.contrib.auth.views import LoginView
from django.http import JsonResponse

from rooms.public_views import landing

from .forms import LoginForm


class RememberLoginView(LoginView):
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def wants_json(self):
        return 'application/json' in self.request.headers.get('Accept', '')

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(0)  # hết phiên khi đóng trình duyệt
        if self.wants_json():
            return JsonResponse({'redirect_url': self.get_success_url()})
        return response

    def form_invalid(self, form):
        if self.wants_json():
            return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
        return super().form_invalid(form)


def home(request):
    return landing(request)

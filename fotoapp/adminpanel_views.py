from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Session  # <- upewnij się, że to poprawna nazwa modelu

@login_required
def dashboard(request):
    return render(request, "adminpanel/dashboard.html")

@login_required
def session_list(request):
    sessions = Session.objects.all()
    return render(request, "adminpanel/session_list.html", {"sessions": sessions})

@login_required
def session_add(request):
    if request.method == "POST":
        # tu możesz dodać walidację lub użyć formularza Django
        Session.objects.create(
            name=request.POST.get("name"),
            code=request.POST.get("code"),
        )
        return redirect("panel_sessions")
    return render(request, "adminpanel/session_form.html")

@login_required
def session_edit(request, id):
    session = get_object_or_404(Session, id=id)
    if request.method == "POST":
        session.name = request.POST.get("name")
        session.code = request.POST.get("code")
        session.save()
        return redirect("panel_sessions")
    return render(request, "adminpanel/session_form.html", {"session": session})

@login_required
def session_delete(request, id):
    session = get_object_or_404(Session, id=id)
    session.delete()
    return redirect("panel_sessions")

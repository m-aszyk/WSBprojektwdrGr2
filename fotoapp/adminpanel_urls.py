from django.urls import path
from . import adminpanel_views

urlpatterns = [
    path("", adminpanel_views.dashboard, name="panel_dashboard"),
    path("sessions/", adminpanel_views.session_list, name="panel_sessions"),
    path("sessions/add/", adminpanel_views.session_add, name="panel_session_add"),
    path("sessions/<int:id>/edit/", adminpanel_views.session_edit, name="panel_session_edit"),
    path("sessions/<int:id>/delete/", adminpanel_views.session_delete, name="panel_session_delete"),
]

# SPDX-License-Identifier: Apache-2.0
from django.urls import path

from . import views

app_name = 'contacts'

urlpatterns = [
    path('', views.contact_list, name='list'),
    path('<uuid:pk>/panel/', views.contact_panel, name='panel'),
    path('organizations/', views.organization_list, name='org_list'),
    path('organizations/<uuid:pk>/panel/', views.organization_panel, name='org_panel'),
    path('email/<uuid:pk>/popup/', views.email_popup, name='email_popup'),
]

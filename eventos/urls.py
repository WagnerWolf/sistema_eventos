from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.lista_eventos, name='lista_eventos'),
    path('painel/auditoria-conflitos/', views.painel_conflitos, name='painel_conflitos'),
    path('painel/resolver-conflito/<int:inscricao_id>/', views.resolver_conflito, name='resolver_conflito'),
    path('evento/<int:evento_id>/inscrever/', views.inscricao_evento, name='inscricao_evento'),
    path('painel/', views.painel_dashboard, name='painel_dashboard'),
    path('painel/evento/<int:evento_id>/exportar/', views.exportar_inscricoes_excel, name='exportar_excel'),
    path('login/', auth_views.LoginView.as_view(template_name='eventos/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('painel/evento/<int:evento_id>/inscricoes/', views.gerenciar_inscricoes, name='gerenciar_inscricoes'),
    path('painel/evento/novo/', views.novo_evento, name='novo_evento'),
    path('painel/evento/<int:evento_id>/presenca/', views.lista_presenca, name='lista_presenca'),
    
]
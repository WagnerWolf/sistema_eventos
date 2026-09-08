from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.lista_eventos, name='lista_eventos'),
    path('painel/auditoria-conflitos/', views.painel_conflitos, name='painel_conflitos'),
    path('painel/resolver-conflito/<int:inscricao_id>/', views.resolver_conflito, name='resolver_conflito'),
    path('painel/evento/<int:evento_id>/exportar/', views.exportar_inscricoes_excel, name='exportar_excel'),
    path('painel/evento/<int:evento_id>/inscricoes/', views.gerenciar_inscricoes, name='gerenciar_inscricoes'),
    path('painel/evento/novo/', views.novo_evento, name='novo_evento'),
    path('painel/evento/<int:evento_id>/presenca/', views.lista_presenca, name='lista_presenca'),
    path('painel/evento/<int:evento_id>/credenciamento/', views.tela_qrcode_checkin, name='tela_qrcode_checkin'),
    path('painel/evento/<int:evento_id>/api/token-checkin/', views.api_gerar_token_qrcode, name='api_token_checkin'),
    path('painel/evento/<int:evento_id>/api/monitoramento/', views.api_dados_monitoramento, name='api_dados_monitoramento'),
    # Rota tradicional (já existe)
    path('inscricao/<int:evento_id>/', views.inscricao_evento, name='inscricao_evento'),    
    # NOVA: Rota minúscula que servirá como encurtador
    path('e/<int:evento_id>/', views.link_curto_evento, name='link_curto_evento'),
    path('painel/', views.painel_dashboard, name='painel_dashboard'),    
    path('login/', auth_views.LoginView.as_view(template_name='eventos/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),    
    path('consultar-inscricao/', views.consultar_inscricao, name='consultar_inscricao'),
    path('cancelar-inscricao/<int:inscricao_id>/', views.cancelar_inscricao, name='cancelar_inscricao'),    
    path('checkin/<int:evento_id>/', views.checkin_evento, name='checkin_evento'),
    path('painel/api/grupo/novo/', views.api_criar_grupo, name='api_criar_grupo'),
    
]
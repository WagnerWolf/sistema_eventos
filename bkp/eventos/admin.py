import openpyxl
from django.http import HttpResponse
from django.contrib import admin, messages
from .models import Evento, Inscricao, GrupoEvento

@admin.action(description='Exportar inscrições para planilha de certificados')
def exportar_para_excel(modeladmin, request, queryset):
    # Cria o workbook e a planilha
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inscrições"

    # Cabeçalho obrigatório solicitado
    headers = ['CPF', 'NOME', 'EMAIL', 'TRABALHO', 'Orientador']
    ws.append(headers)

    # Adiciona os dados das inscrições selecionadas
    for inscricao in queryset:
        ws.append([
            inscricao.cpf,
            inscricao.nome_completo.upper(),
            inscricao.email,
            inscricao.trabalho or '',
            inscricao.orientador or ''
        ])

    # Prepara a resposta do navegador para download
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=inscricoes_certificados.xlsx'
    wb.save(response)
    return response

@admin.register(Inscricao)
class InscricaoAdmin(admin.ModelAdmin):
    list_display = ('nome_completo', 'evento', 'status', 'data_inscricao')
    list_filter = ('evento', 'status')
    search_fields = ('nome_completo', 'cpf', 'email')
    actions = [exportar_para_excel, 'aprovar_inscricoes']

    @admin.action(description='Aprovar inscrições selecionadas')
    def aprovar_inscricoes(self, request, queryset):
        # Aqui podemos adicionar a lógica de conferir vagas antes de aprovar
        for inscricao in queryset:
            evento = inscricao.evento
            if evento.vagas_restantes > 0:
                inscricao.status = 'APROVADA'
            else:
                inscricao.status = 'LISTA_ESPERA'
            inscricao.save()

@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'data_inicio', 'vagas_totais', 'aberto_comunidade', 'grupo')
    list_filter = ('aberto_comunidade', 'data_inicio')
    search_fields = ('titulo', 'descricao')
    actions = ['verificar_duplicidade']

    @admin.action(description='Verificar duplicidade de inscritos (Selecione 2 eventos)')
    def verificar_duplicidade(self, request, queryset):
        # Trava para garantir que o usuário selecione apenas 2 eventos
        if queryset.count() != 2:
            self.message_user(request, "Por favor, selecione exatamente DOIS eventos para comparar.", level=messages.ERROR)
            return

        evento1, evento2 = queryset[0], queryset[1]
        
        # Pegamos apenas os CPFs de cada evento e transformamos em "sets" (conjuntos)
        cpfs_e1 = set(evento1.inscricoes.values_list('cpf', flat=True))
        cpfs_e2 = set(evento2.inscricoes.values_list('cpf', flat=True))
        
        # O Python cruza os dados e acha quem está nos dois grupos instantaneamente
        duplicados = cpfs_e1.intersection(cpfs_e2)
        
        if not duplicados:
            self.message_user(request, f"Tudo limpo! Nenhuma duplicidade encontrada entre '{evento1.titulo}' e '{evento2.titulo}'.", level=messages.SUCCESS)
        else:
            # Pega os nomes das pessoas duplicadas (usando o evento1 como base de busca)
            inscritos_duplicados = evento1.inscricoes.filter(cpf__in=duplicados)
            nomes = [insc.nome_completo for insc in inscritos_duplicados]
            
            # Monta a mensagem de aviso
            mensagem = f"Atenção! {len(duplicados)} pessoa(s) inscrita(s) em ambos os eventos: {', '.join(nomes)}."
            self.message_user(request, mensagem, level=messages.WARNING)

@admin.register(GrupoEvento)
class GrupoEventoAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)
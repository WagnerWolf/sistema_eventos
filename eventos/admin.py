import openpyxl
from django.http import HttpResponse
from django.contrib import admin
from .models import Evento, Inscricao

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
    list_display = ('titulo', 'data_inicio', 'vagas_totais', 'aberto_comunidade')
    list_filter = ('aberto_comunidade', 'data_inicio')
    search_fields = ('titulo', 'descricao')
import openpyxl
from django.http import HttpResponse
from django.contrib import admin, messages
from .models import Evento, Inscricao, GrupoEvento, ControleNoShow

import io
from django.http import FileResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER


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

# 1. Cria a Ação que gera o PDF
@admin.action(description="🖨️ Gerar Ficha de Avaliação (PDF)")
def exportar_candidatos_avaliacao_pdf(modeladmin, request, queryset):
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=landscape(A4),
        rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30,
        title="Ficha de Avaliação de Candidatos",
        author="Sistema de Eventos UFOPA"
    )
    
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(name='CenterTitle', parent=styles['Heading2'], alignment=TA_CENTER)
    subtitle_style = ParagraphStyle(name='CenterSubTitle', parent=styles['Normal'], alignment=TA_CENTER, textColor=colors.dimgrey)

    # Percorre os eventos selecionados na caixinha do painel admin
    for evento in queryset:
        # Filtra apenas quem NÃO está aprovado (Pendente, Espera, etc)
        inscricoes = evento.inscricoes.exclude(status='APROVADA').order_by('nome_completo')
        
        # Se não houver candidatos pendentes, pula a página
        if not inscricoes.exists():
            continue

        # Cabeçalho
        elements.append(Paragraph("Ficha de Avaliação de Candidatos", title_style))
        elements.append(Paragraph(f"Evento: {evento.titulo}", title_style))
        elements.append(Spacer(1, 15))
        
        # Monta o cabeçalho da tabela
        data = [['Nome do Candidato', 'Vínculo / Matrícula', 'Curso / Setor', 'Status Atual', 'Parecer']]
        
        for insc in inscricoes:
            vinculo = insc.matricula if (insc.tem_vinculo_universidade and insc.matricula) else "Comunidade Externa"
            curso = insc.curso_turma if insc.curso_turma else "-"
            status = insc.get_status_display()
            
            # A última coluna vai vazia para o professor escrever à mão
            data.append([insc.nome_completo, vinculo, curso, status, ""])
            
        # Desenha a tabela
        # As larguras somam o total da folha A4 em paisagem (~780 pontos)
        t = Table(data, colWidths=[200, 120, 160, 90, 180])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'), # Nome alinhado à esquerda
            ('ALIGN', (2, 0), (2, -1), 'LEFT'), # Curso alinhado à esquerda
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9), # Letra um pouco menor nas linhas para caber mais dados
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
        ]))
        
        elements.append(t)
        elements.append(Spacer(1, 30))

    # Se nenhum evento tiver candidatos pendentes, gera um PDF com aviso
    if not elements:
        elements.append(Paragraph("Nenhum candidato pendente de avaliação nos eventos selecionados.", title_style))

    doc.build(elements)
    buffer.seek(0)
    
    # Retorna o PDF para visualização direta no navegador
    return FileResponse(buffer, as_attachment=False, filename="ficha_avaliacao_candidatos.pdf")


@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'data_inicio', 'vagas_totais', 'aberto_comunidade', 'grupo')
    list_filter = ('aberto_comunidade', 'data_inicio')
    search_fields = ('titulo', 'descricao')
    actions = ['verificar_duplicidade', exportar_candidatos_avaliacao_pdf]

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

@admin.register(ControleNoShow)
class ControleNoShowAdmin(admin.ModelAdmin):
    # Colunas que vão aparecer na listagem
    list_display = ('cpf', 'nome', 'tipo', 'atualizado_em')
    
    # Filtro lateral (útil para ver só quem tá bloqueado ou só quem foi perdoado)
    list_filter = ('tipo', 'atualizado_em')
    
    # Barra de pesquisa no topo
    search_fields = ('cpf', 'nome', 'justificativa')
    
    # Impede que alguém tente editar a data de atualização manualmente e quebre a nossa regra
    readonly_fields = ('atualizado_em',)
    
    # Ordena mostrando as regras mais recentes primeiro
    ordering = ('-atualizado_em',)



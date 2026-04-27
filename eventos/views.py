from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import Evento, Inscricao
from django.contrib.auth.decorators import login_required
from django.db.models import Count
import openpyxl
from django.http import HttpResponse
from django.urls import reverse
from django.core.paginator import Paginator
from .forms import EventoForm
import resend
from django.conf import settings
from django.utils import timezone
import pytz

def lista_eventos(request):
    todos_eventos = Evento.objects.all().order_by('-data_inicio')
    
    eventos_abertos_list = [evento for evento in todos_eventos if evento.inscricoes_abertas]
    eventos_encerrados_list = [evento for evento in todos_eventos if not evento.inscricoes_abertas]
    
    # Paginação para os Eventos Abertos (10 por página)
    paginator_abertos = Paginator(eventos_abertos_list, 10)
    page_number_abertos = request.GET.get('page_abertos', 1)
    eventos_abertos = paginator_abertos.get_page(page_number_abertos)

    # Paginação para os Eventos Encerrados (10 por página)
    paginator_encerrados = Paginator(eventos_encerrados_list, 10)
    page_number_encerrados = request.GET.get('page_encerrados', 1)
    eventos_encerrados = paginator_encerrados.get_page(page_number_encerrados)
    
    context = {
        'eventos_abertos': eventos_abertos,
        'eventos_encerrados': eventos_encerrados
    }
    return render(request, 'eventos/lista_eventos.html', context)

def inscricao_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    
    if request.method == 'POST':
        # Coleta os dados enviados pelo formulário HTML
        nome = request.POST.get('nome_completo')
        email = request.POST.get('email')
        cpf = request.POST.get('cpf')
        
        # --- BLOQUEIO DE DUPLICATA ---
        if Inscricao.objects.filter(evento=evento, cpf=cpf).exists():
            messages.warning(request, f'Já existe uma inscrição realizada com o CPF {cpf} para este evento.')
            return redirect('inscricao_evento', evento_id=evento.id)
        
        # O checkbox de vínculo retornará 'on' se estiver marcado
        vinculo = request.POST.get('tem_vinculo') == 'on'
        matricula = request.POST.get('matricula')
        curso_turma = request.POST.get('curso_turma')
        # --- NOVA VALIDAÇÃO DE SEGURANÇA ---
        # 1. Tentar se inscrever sem vínculo num evento restrito
        if not evento.aberto_comunidade and not vinculo:
            messages.error(request, 'Operação negada. Este evento é exclusivo para a comunidade acadêmica.')
            return redirect('inscricao_evento', evento_id=evento.id)
        
        # 2. Afirmar que tem vínculo, mas deixar os dados em branco
        if vinculo and (not matricula or not curso_turma):
            messages.error(request, 'Por favor, preencha sua matrícula e curso/setor.')
            return redirect('inscricao_evento', evento_id=evento.id)
        # -----------------------------------
        respostas_dict = {}
        if evento.tem_questionario and evento.questionario:
            for pergunta in evento.questionario:
                q_id = pergunta['id']
                # Pega a resposta enviada via POST baseada no ID da pergunta
                respostas_dict[q_id] = request.POST.get(q_id, '')
        
        # Cria e salva a inscrição no banco de dados
        Inscricao.objects.create(
            evento=evento,
            nome_completo=nome,
            email=email,
            cpf=cpf,
            tem_vinculo_universidade=vinculo,
            matricula=matricula if vinculo else '',
            curso_turma=curso_turma if vinculo else '',
            respostas_questionario=respostas_dict # Salva o dicionário como JSON!
        )
        
        # Mensagem de sucesso para o usuário
        messages.success(request, 'Sua inscrição foi registrada com sucesso, aguarde o email de confirmação!')
        return redirect('lista_eventos')

    return render(request, 'eventos/form_inscricao.html', {'evento': evento})

@login_required
def painel_dashboard(request):
    # Verifica se o usuário tem permissão de staff (equipe)
    if not request.user.is_staff:
        messages.error(request, 'Acesso negado. Você não tem permissão para ver esta página.')
        return redirect('lista_eventos')

    # Anota (calcula) o total de inscrições para cada evento
    eventos = Evento.objects.annotate(total_inscricoes=Count('inscricoes')).order_by('-data_inicio')
    
    # Estatísticas gerais para os cards do topo
    total_eventos = Evento.objects.count()
    total_inscricoes_geral = Inscricao.objects.count()
    inscricoes_pendentes = Inscricao.objects.filter(status='PENDENTE').count()

    context = {
        'eventos': eventos,
        'total_eventos': total_eventos,
        'total_inscricoes_geral': total_inscricoes_geral,
        'inscricoes_pendentes': inscricoes_pendentes,
    }
    
    return render(request, 'eventos/dashboard.html', context)

@login_required
def exportar_inscricoes_excel(request, evento_id):
    # Busca o evento específico
    evento = get_object_or_404(Evento, id=evento_id)
    
    # Busca todas as inscrições do evento (você pode alterar para .filter(status='APROVADA') se preferir exportar só os aprovados)
    inscricoes = evento.inscricoes.all().order_by('nome_completo')

    # Cria o arquivo Excel em memória
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inscrições"

    # Define e insere o cabeçalho exato que você solicitou
    headers = ['CPF', 'NOME', 'EMAIL', 'TRABALHO', 'Orientador']
    ws.append(headers)

    # Preenche as linhas com os dados dos inscritos
    for inscricao in inscricoes:
        ws.append([
            inscricao.cpf,
            inscricao.nome_completo.upper(), # Nome em maiúsculo costuma ficar melhor em certificados
            inscricao.email,
            inscricao.trabalho or '',
            inscricao.orientador or ''
        ])

    # Prepara a resposta HTTP para forçar o download do arquivo
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    # O nome do arquivo terá o título do evento (removendo espaços para evitar problemas no download)
    nome_arquivo = f"inscricoes_{evento.titulo.replace(' ', '_')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename={nome_arquivo}'
    
    wb.save(response)
    return response

import resend
from django.conf import settings

@login_required
def gerenciar_inscricoes(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    inscricoes = evento.inscricoes.all().order_by('-data_inscricao')

    # --- Prepara as respostas cruzando o ID com o Enunciado ---
    perguntas_dict = {}
    if evento.questionario:
        for p in evento.questionario:
            perguntas_dict[p['id']] = p['enunciado']

    for inscricao in inscricoes:
        inscricao.respostas_detalhadas = []
        if inscricao.respostas_questionario:
            for q_id, resposta in inscricao.respostas_questionario.items():
                enunciado = perguntas_dict.get(q_id, 'Pergunta não encontrada')
                inscricao.respostas_detalhadas.append({
                    'enunciado': enunciado,
                    'resposta': resposta
                })

    # Processa a mudança de status
    if request.method == 'POST':
        inscricao_id = request.POST.get('inscricao_id')
        novo_status = request.POST.get('novo_status')
        
        if inscricao_id and novo_status in dict(Inscricao.STATUS_CHOICES).keys():
            inscricao = get_object_or_404(Inscricao, id=inscricao_id, evento=evento)
            
            # Guardamos o status antigo para checar se já estava aprovado
            status_anterior = inscricao.status
            inscricao.status = novo_status
            inscricao.save()

            # --- Lógica de Envio de E-mail ---
            # --- Lógica de Envio de E-mail ---
            if novo_status == 'APROVADA' and status_anterior != 'APROVADA':
                try:
                    # Converte a data do banco (UTC) para o fuso local definido no settings
                    fuso_local = pytz.timezone(settings.TIME_ZONE)
                    data_local = evento.data_inicio.astimezone(fuso_local)
                    
                    resend.api_key = settings.RESEND_API_KEY
                    resend.Emails.send({
                        "from": f"Sistema de Eventos <{settings.EMAIL_REMETENTE}>",
                        "to": [inscricao.email],
                        "subject": f"Inscrição Confirmada: {evento.titulo}",
                        "html": f"""
                            <div style="font-family: sans-serif; border: 1px solid #198754; padding: 20px; border-radius: 10px;">
                                <h2 style="color: #198754;">Olá, {inscricao.nome_completo}!</h2>
                                <p>Temos o prazer de informar que sua inscrição para o evento <strong>{evento.titulo}</strong> foi <strong>APROVADA</strong>.</p>
                                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                                    <p style="margin: 0;"><strong>📍 Local:</strong> {evento.local or 'A definir'}</p>
                                    <p style="margin: 5px 0 0 0;"><strong>⏰ Início:</strong> {data_local.strftime('%d/%m/%Y às %H:%M')}</p>
                                </div>
                                <p style="font-size: 12px; color: #666;">Este é um e-mail automático, por favor não responda.</p>
                            </div>
                        """
                    })
                except Exception as e:
                    # Logamos o erro no console para não travar a experiência do admin se o Resend falhar
                    print(f"Erro ao disparar Resend: {e}")
            # ---------------------------------

            messages.success(request, f'Status de {inscricao.nome_completo} atualizado para {inscricao.get_status_display()}.')
            return redirect('gerenciar_inscricoes', evento_id=evento.id)

    context = {
        'evento': evento,
        'inscricoes': inscricoes,
    }
    return render(request, 'eventos/gerenciar_inscricoes.html', context)

@login_required
def novo_evento(request):
    if not request.user.is_staff:
        messages.error(request, 'Acesso negado.')
        return redirect('lista_eventos')

    if request.method == 'POST':
        form = EventoForm(request.POST, request.FILES) # request.FILES é vital para a foto!
        if form.is_valid():
            form.save()
            messages.success(request, 'Evento criado com sucesso!')
            return redirect('painel_dashboard')
    else:
        form = EventoForm()

    return render(request, 'eventos/form_evento.html', {'form': form, 'titulo_pagina': 'Criar Novo Evento'})

@login_required
def lista_presenca(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    # Filtra apenas os aprovados e ordena por nome
    inscricoes = evento.inscricoes.filter(status='APROVADA').order_by('nome_completo')
    
    context = {
        'evento': evento,
        'inscricoes': inscricoes,
    }
    return render(request, 'eventos/lista_presenca.html', context)
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
from django.http import JsonResponse
from django.db import transaction
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.decorators import permission_required

def e_avaliador(user):
    # Primeiro garante que está logado, depois verifica o grupo ou se é admin
    if not user.is_authenticated:
        return False
    return user.groups.filter(name='Avaliadores').exists() or user.is_superuser

def lista_eventos(request):
    todos_eventos = Evento.objects.all().order_by('-data_inicio')
    agora = timezone.now()

    eventos_ativos_list = [] # Vai guardar tanto os abertos quanto os futuros
    eventos_encerrados_list = []
    
    for evento in todos_eventos:
        # Se tem data de fim de inscrição e o 'agora' já passou dela, está encerrado
        if evento.fim_inscricoes and agora > evento.fim_inscricoes:
            eventos_encerrados_list.append(evento)
        else:
            # Caso contrário, ou está aberto agora, ou vai abrir no futuro
            eventos_ativos_list.append(evento)
    
    paginator_abertos = Paginator(eventos_ativos_list, 10)
    page_number_abertos = request.GET.get('page_abertos', 1)
    eventos_abertos = paginator_abertos.get_page(page_number_abertos)

    paginator_encerrados = Paginator(eventos_encerrados_list, 10)
    page_number_encerrados = request.GET.get('page_encerrados', 1)
    eventos_encerrados = paginator_encerrados.get_page(page_number_encerrados)
    
    context = {
        'eventos_abertos': eventos_abertos,
        'eventos_encerrados': eventos_encerrados,
        'agora': agora
    }
    return render(request, 'eventos/lista_eventos.html', context)

def inscricao_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    agora = timezone.now()
    
    if evento.inicio_inscricoes and agora < evento.inicio_inscricoes:
        messages.warning(request, 'As inscrições para este evento ainda não começaram.')
        return redirect('lista_eventos')
        
    if evento.fim_inscricoes and agora > evento.fim_inscricoes:
        messages.warning(request, 'As inscrições para este evento já foram encerradas.')
        return redirect('lista_eventos')
    
    if request.method == 'POST':
        nome = request.POST.get('nome_completo')
        email = request.POST.get('email')
        cpf = request.POST.get('cpf')
        vinculo = request.POST.get('tem_vinculo') == 'on'
        matricula = request.POST.get('matricula', '')
        curso_turma = request.POST.get('curso_turma', '')
        
        # --- VERIFICAÇÃO AJAX ---
        if request.POST.get('ajax_check') == '1':
            if Inscricao.objects.filter(evento=evento, cpf=cpf).exists():
                return JsonResponse({'status': 'erro', 'mensagem': 'Já existe uma inscrição realizada com este CPF para este evento.'})
                
            if getattr(evento, 'grupo', None):
                inscricao_existente = Inscricao.objects.filter(evento__grupo=evento.grupo, cpf=cpf).first()
                if inscricao_existente:
                    divergencias = []
                    if inscricao_existente.nome_completo != nome:
                        divergencias.append({'campo': 'Nome', 'antigo': inscricao_existente.nome_completo, 'novo': nome})
                    if inscricao_existente.email != email:
                        divergencias.append({'campo': 'E-mail', 'antigo': inscricao_existente.email, 'novo': email})
                    
                    banco_matricula = inscricao_existente.matricula or ''
                    banco_curso = inscricao_existente.curso_turma or ''
                    
                    if banco_matricula != matricula:
                        divergencias.append({'campo': 'Matrícula', 'antigo': banco_matricula or '(Vazio)', 'novo': matricula or '(Vazio)'})
                    if banco_curso != curso_turma:
                        divergencias.append({'campo': 'Curso/Setor', 'antigo': banco_curso or '(Vazio)', 'novo': curso_turma or '(Vazio)'})

                    return JsonResponse({
                        'status': 'conflito_grupo', 
                        'evento_antigo': inscricao_existente.evento.titulo,
                        'divergencias': divergencias
                    })
            return JsonResponse({'status': 'ok'})
        # ------------------------

        # --- EXECUÇÃO FINAL DO POST ---
        
        # 🚨 BLOQUEIO DE SEGURANÇA FINAL (O que estava faltando!) 🚨
        if Inscricao.objects.filter(evento=evento, cpf=cpf).exists():
            messages.error(request, 'Operação cancelada: Já existe uma inscrição ativa para este CPF neste evento.')
            return redirect('inscricao_evento', evento_id=evento.id)

        confirmar_transferencia = request.POST.get('confirmar_transferencia') == '1'
        atualizar_dados = request.POST.get('atualizar_dados') == '1'

        if getattr(evento, 'grupo', None):
            inscricao_existente = Inscricao.objects.filter(evento__grupo=evento.grupo, cpf=cpf).first()
            if inscricao_existente and confirmar_transferencia:
                inscricao_existente.evento = evento
                inscricao_existente.status = 'PENDENTE'
                
                if atualizar_dados:
                    inscricao_existente.nome_completo = nome
                    inscricao_existente.email = email
                    inscricao_existente.tem_vinculo_universidade = vinculo
                    inscricao_existente.matricula = matricula
                    inscricao_existente.curso_turma = curso_turma
                    
                    respostas_dict = {}
                    if evento.tem_questionario and evento.questionario:
                        for pergunta in evento.questionario:
                            respostas_dict[pergunta['id']] = request.POST.get(pergunta['id'], '')
                    inscricao_existente.respostas_questionario = respostas_dict

                inscricao_existente.save()
                messages.success(request, f'Sua inscrição foi transferida com sucesso para: {evento.titulo}.')
                return redirect('lista_eventos')

        if not evento.aberto_comunidade and not vinculo:
            messages.error(request, 'Operação negada. Este evento é exclusivo para a comunidade acadêmica.')
            return redirect('inscricao_evento', evento_id=evento.id)
        
        if vinculo and (not matricula or not curso_turma):
            messages.error(request, 'Por favor, preencha sua matrícula e curso/setor.')
            return redirect('inscricao_evento', evento_id=evento.id)
        
        respostas_dict = {}
        if evento.tem_questionario and evento.questionario:
            for pergunta in evento.questionario:
                respostas_dict[pergunta['id']] = request.POST.get(pergunta['id'], '')
        
        Inscricao.objects.create(
            evento=evento, nome_completo=nome, email=email, cpf=cpf,
            tem_vinculo_universidade=vinculo, matricula=matricula if vinculo else '',
            curso_turma=curso_turma if vinculo else '', respostas_questionario=respostas_dict
        )
        messages.success(request, 'Sua inscrição foi registrada com sucesso, aguarde o email de confirmação!')
        return redirect('lista_eventos')

    return render(request, 'eventos/form_inscricao.html', {'evento': evento})

@user_passes_test(e_avaliador)
def painel_dashboard(request):
    # Verifica se o usuário tem permissão de staff (equipe)


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
    if not request.user.is_staff:

        messages.error(request, 'Acesso negado. Você não tem permissão para ver esta página.')

        return redirect('painel_dashboard')
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



@user_passes_test(e_avaliador)
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
@permission_required('eventos.add_evento', raise_exception=True)
def novo_evento(request):

    if request.method == 'POST':
        form = EventoForm(request.POST, request.FILES) # request.FILES é vital para a foto!
        if form.is_valid():
            form.save()
            messages.success(request, 'Evento criado com sucesso!')
            return redirect('painel_dashboard')
    else:
        form = EventoForm()

    return render(request, 'eventos/form_evento.html', {'form': form, 'titulo_pagina': 'Criar Novo Evento'})

@user_passes_test(e_avaliador)
def lista_presenca(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    # Filtra apenas os aprovados e ordena por nome
    inscricoes = evento.inscricoes.filter(status='APROVADA').order_by('nome_completo')
    
    context = {
        'evento': evento,
        'inscricoes': inscricoes,
    }
    return render(request, 'eventos/lista_presenca.html', context)


@user_passes_test(e_avaliador)
def painel_conflitos(request):
    # 1. Filtra os CPFs que estão em mais de um evento do mesmo grupo e NÃO estão recusados
    conflitos_brutos = Inscricao.objects.exclude(status='RECUSADA')\
        .values('cpf', 'evento__grupo__nome')\
        .annotate(total=Count('id'))\
        .filter(total__gt=1, evento__grupo__isnull=False)

    conflitos_detalhados = []
    for c in conflitos_brutos:
        # 2. Busca os detalhes dessas inscrições, também EXCLUINDO as já recusadas
        inscricoes = Inscricao.objects.filter(
            cpf=c['cpf'], 
            evento__grupo__nome=c['evento__grupo__nome']
        ).exclude(status='RECUSADA').order_by('status')
        
        conflitos_detalhados.append({
            'cpf': c['cpf'],
            'grupo': c['evento__grupo__nome'],
            'inscricoes': inscricoes
        })

    return render(request, 'eventos/painel_conflitos.html', {'conflitos': conflitos_detalhados})


@user_passes_test(e_avaliador)
def resolver_conflito(request, inscricao_id):
    if request.method == 'POST':
        inscricao_mantida = get_object_or_404(Inscricao, id=inscricao_id)
        grupo = inscricao_mantida.evento.grupo
        cpf = inscricao_mantida.cpf

        if not grupo:
            messages.error(request, "Erro: Esta inscrição não pertence a um grupo.")
            return redirect('painel_conflitos')

        # O transaction.atomic() garante que se der erro em uma linha, ele desfaz tudo
        with transaction.atomic():
            # 1. Aprova a inscrição que o avaliador escolheu
            #inscricao_mantida.status = 'APROVADA' 
            #inscricao_mantida.save()

            # 2. Busca TODAS as outras inscrições do mesmo CPF naquele mesmo grupo
            # que não sejam a que acabamos de manter, e que ainda não estejam recusadas
            outras_inscricoes = Inscricao.objects.filter(
                cpf=cpf,
                evento__grupo=grupo
            ).exclude(id=inscricao_id).exclude(status='RECUSADA')

            # 3. Altera o status das outras para RECUSADA
            for outra in outras_inscricoes:
                outra.status = 'RECUSADA'
                outra.save()

        messages.success(request, f"Conflito resolvido! A inscrição na turma '{inscricao_mantida.evento.titulo}' permanece como pendente para análise e as duplicatas foram recusadas.")

    return redirect('painel_conflitos')
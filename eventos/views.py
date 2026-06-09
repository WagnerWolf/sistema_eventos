import xlwt
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
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from datetime import timedelta


def enviar_email_confirmacao(inscricao, evento):
    """Função centralizada para disparo de e-mail de aprovação"""
    try:
        fuso_local = pytz.timezone(settings.TIME_ZONE)
        data_local = evento.data_inicio.astimezone(fuso_local)
        
        # Cria a URL usando o Python. Substitua pelo domínio real do seu servidor!
        caminho_consulta = reverse('consultar_inscricao')
        url_completa = f"https://eventos.wagnerwolf.com.br{caminho_consulta}"
        
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
                        <p style="margin: 0; color: #333;"><strong>📍 Local:</strong> {evento.local or 'A definir'}</p>
                        <p style="margin: 5px 0 0 0; color: #333;"><strong>⏰ Início:</strong> {data_local.strftime('%d/%m/%Y às %H:%M')}</p>
                    </div>
                    
                    <div style="margin-top: 25px; padding: 15px; border-left: 4px solid #dc3545; background-color: #fff3f3; border-radius: 4px;">
                        <p style="margin: 0; color: #842029; font-size: 14px;">
                            <strong>⚠️ Importante: Imprevistos acontecem!</strong><br>
                            As vagas para este evento são limitadas. Se você perceber que <strong>não poderá comparecer</strong>, por favor, acesse o portal e cancele sua inscrição para liberar a vaga a um colega.
                        </p>
                        <p style="margin: 10px 0 0 0; font-size: 14px;">
                            👉 <a href="{url_completa}" style="color: #dc3545; font-weight: bold;">Clique aqui para gerenciar sua inscrição</a>
                        </p>
                    </div>

                    <p style="font-size: 12px; color: #666; margin-top: 20px;">Este é um e-mail automático, por favor não responda.</p>
                </div>
            """
        })
    except Exception as e:
        print(f"Erro ao disparar Resend: {e}")



def promover_da_lista_espera(evento):
    """
    Verifica se há vagas e pessoas na lista de espera.
    Aprova o mais antigo da fila automaticamente e dispara o e-mail.
    """
    # Usamos um loop caso abra mais de uma vaga de uma vez
    while True:
        # Pega a quantidade de vagas atualizada (considerando os aprovados atuais)
        vagas_abertas = getattr(evento, 'vagas_restantes', 0)
        
        # Se for um método do model em vez de property, executa ele
        if callable(vagas_abertas):
            vagas_abertas = vagas_abertas()

        if vagas_abertas <= 0:
            break # Evento lotado novamente

        # Busca a inscrição mais antiga da lista de espera
        proximo = Inscricao.objects.filter(
            evento=evento, 
            status='LISTA_ESPERA'
        ).order_by('data_inscricao').first()

        if proximo:
            proximo.status = 'APROVADA'
            proximo.save()
            
            # O próximo da fila conseguiu a vaga, manda o e-mail de surpresa boa!
            enviar_email_confirmacao(proximo, evento)
        else:
            break # Não há mais ninguém na lista de espera

def e_avaliador(user):
    # Primeiro garante que está logado, depois verifica o grupo ou se é admin
    if not user.is_authenticated:
        return False
    return user.groups.filter(name='Avaliadores').exists() or user.is_superuser

def lista_eventos(request):
    todos_eventos = Evento.objects.all().order_by('data_inicio', 'id')
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
    
    # --- VALIDAÇÃO DO TOKEN DE CREDENCIAMENTO LOCAL ---
    signer = TimestampSigner()
    token = request.GET.get('token') or request.POST.get('token')
    is_inscricao_local = False
    
    if token:
        try:
            # Dá 10 minutos (600s) para o aluno preencher o formulário com calma
            evento_id_assinado = signer.unsign(token, max_age=600)
            if str(evento.id) == evento_id_assinado:
                is_inscricao_local = True
        except (SignatureExpired, BadSignature):
            messages.error(request, 'O tempo para inscrição no local expirou. Por favor, escaneie o QR Code novamente.')
            return redirect('lista_eventos')
    # --------------------------------------------------

    # Trava de datas (Ignorada se for Inscrição Local VIP)
    if not is_inscricao_local:
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
        if Inscricao.objects.filter(evento=evento, cpf=cpf).exists():
            messages.error(request, 'Operação cancelada: Já existe uma inscrição ativa para este CPF neste evento.')
            return redirect('inscricao_evento', evento_id=evento.id)

        confirmar_transferencia = request.POST.get('confirmar_transferencia') == '1'
        atualizar_dados = request.POST.get('atualizar_dados') == '1'

        if getattr(evento, 'grupo', None):
            inscricao_existente = Inscricao.objects.filter(evento__grupo=evento.grupo, cpf=cpf).first()
            if inscricao_existente and confirmar_transferencia:
                inscricao_existente.evento = evento
                
                # --- LÓGICA NA TRANSFERÊNCIA ---
                if is_inscricao_local:
                    inscricao_existente.status = 'APROVADA'
                    inscricao_existente.compareceu = True
                    inscricao_existente.inscricao_local = True
                    # Inicia a contagem progressiva na transferência local
                    inscricao_existente.total_presencas = 1
                    inscricao_existente.ultimo_checkin = agora
                else:
                    if evento.aprovacao_automatica:
                        if getattr(evento, 'vagas_restantes', 1) > 0:
                            inscricao_existente.status = 'APROVADA'
                        else:
                            inscricao_existente.status = 'LISTA_ESPERA'
                    else:
                        inscricao_existente.status = 'PENDENTE'
                # --------------------------------
                
                if atualizar_dados:
                    inscricao_existente.nome_completo = nome
                    inscricao_existente.email = email
                    inscricao_existente.tem_vinculo_universidade = vinculo
                    inscricao_existente.matricula = matricula
                    inscricao_existente.curso_turma = curso_turma
                    
                    respostas_dict = {}
                    if getattr(evento, 'tem_questionario', False) and evento.questionario:
                        for pergunta in evento.questionario:
                            respostas_dict[pergunta['id']] = request.POST.get(pergunta['id'], '')
                    inscricao_existente.respostas_questionario = respostas_dict

                inscricao_existente.save()

                if inscricao_existente.status == 'APROVADA' and not is_inscricao_local:
                    enviar_email_confirmacao(inscricao_existente, evento)

                if is_inscricao_local:
                    messages.success(request, f'✅ Presença confirmada via transferência! Bem-vindo(a), {nome.split()[0]}!')
                else:
                    messages.success(request, f'Sua inscrição foi transferida com sucesso para: {evento.titulo}.')
                return redirect('lista_eventos')

        if not getattr(evento, 'aberto_comunidade', True) and not vinculo:
            messages.error(request, 'Operação negada. Este evento é exclusivo para a comunidade acadêmica.')
            return redirect('inscricao_evento', evento_id=evento.id)
        
        if vinculo and (not matricula or not curso_turma):
            messages.error(request, 'Por favor, preencha sua matrícula e curso/setor.')
            return redirect('inscricao_evento', evento_id=evento.id)
        
        respostas_dict = {}
        if getattr(evento, 'tem_questionario', False) and evento.questionario:
            for pergunta in evento.questionario:
                respostas_dict[pergunta['id']] = request.POST.get(pergunta['id'], '')
        
        # --- LÓGICA PARA INSCRIÇÃO NOVA ---
        if is_inscricao_local:
            status_inicial = 'APROVADA'
        else:
            status_inicial = 'PENDENTE'
            if evento.aprovacao_automatica:
                if getattr(evento, 'vagas_restantes', 1) > 0:
                    status_inicial = 'APROVADA'
                else:
                    status_inicial = 'LISTA_ESPERA'

        nova_inscricao = Inscricao.objects.create(
            evento=evento, nome_completo=nome, email=email, cpf=cpf,
            tem_vinculo_universidade=vinculo, matricula=matricula if vinculo else '',
            curso_turma=curso_turma if vinculo else '', respostas_questionario=respostas_dict,
            status=status_inicial,
            compareceu=is_inscricao_local,        
            inscricao_local=is_inscricao_local,
            # Configura a primeira presença progressiva no banco
            total_presencas=1 if is_inscricao_local else 0,
            ultimo_checkin=agora if is_inscricao_local else None
        )

        if is_inscricao_local:
            messages.success(request, f'✅ Inscrição expressa concluída e presença confirmada! Bom evento, {nome.split()[0]}!')
        else:
            if status_inicial == 'APROVADA':
                enviar_email_confirmacao(nova_inscricao, evento)
                messages.success(request, 'Sua inscrição foi registrada e confirmada com sucesso!')
            elif status_inicial == 'LISTA_ESPERA':
                messages.warning(request, 'As vagas estão esgotadas. Você foi colocado na Lista de Espera e será aprovado caso alguém desista!')
            else:
                messages.success(request, 'Sua inscrição foi registrada com sucesso, aguarde o email de confirmação da equipe!')
            
        return redirect('lista_eventos')

    context = {
        'evento': evento,
        'cpf_preenchido': request.GET.get('cpf', ''),
        'token': token if is_inscricao_local else ''
    }
    return render(request, 'eventos/form_inscricao.html', context)

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
    
    # Busca todas as inscrições aprovadas para filtragem por propriedade
    inscricoes_aprovadas = evento.inscricoes.filter(status='APROVADA').order_by('nome_completo')
    
    # 🚨 FILTRO ATUALIZADO: Avalia a propriedade baseada na frequência mínima da oficina/evento
    inscricoes = [i for i in inscricoes_aprovadas if i.aprovado_certificado]

    # Prepara a resposta HTTP para forçar o download em .xls
    response = HttpResponse(content_type='application/vnd.ms-excel')
    nome_arquivo = f"inscricoes_{evento.titulo.replace(' ', '_')}.xls"
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'

    # Cria o arquivo Excel em memória usando xlwt
    wb = xlwt.Workbook(encoding='utf-8')
    ws = wb.add_sheet("Inscrições")

    # Define e insere o cabeçalho (Adicionado a coluna de Frequência para auditoria)
    headers = ['CPF', 'NOME', 'EMAIL', 'TRABALHO', 'Orientador', 'FREQUÊNCIA']
    for col_num, header in enumerate(headers):
        ws.write(0, col_num, header)

    # Preenche as linhas com os dados dos inscritos habilitados
    for row_num, inscricao in enumerate(inscricoes, start=1):
        ws.write(row_num, 0, inscricao.cpf)
        ws.write(row_num, 1, inscricao.nome_completo.upper())
        ws.write(row_num, 2, inscricao.email)
        ws.write(row_num, 3, inscricao.trabalho or '')
        ws.write(row_num, 4, inscricao.orientador or '')
        ws.write(row_num, 5, f"{inscricao.percentual_frequencia}%")
        
    # Salva o workbook diretamente no objeto response
    wb.save(response)
    return response



@user_passes_test(e_avaliador)
def gerenciar_inscricoes(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    agora = timezone.now()
    
    # 1. Checa se o prazo acabou (Apenas data)
    prazo_encerrado = evento.fim_inscricoes and agora > evento.fim_inscricoes

    # 2. Só bloqueia o avaliador se o evento for AUTOMÁTICO e o prazo acabou
    bloquear_avaliador = prazo_encerrado and evento.aprovacao_automatica

    # 3. 🚨 NOVA TRAVA: Checa se o evento está lotado
    vagas_restantes = getattr(evento, 'vagas_restantes', 0)
    if callable(vagas_restantes):
        vagas_restantes = vagas_restantes()
    evento_lotado = vagas_restantes <= 0

    # Se estiver bloqueado (automático + encerrado), exibe APENAS os aprovados. Se não, exibe todos.
    if bloquear_avaliador:
        inscricoes = evento.inscricoes.filter(status='APROVADA').order_by('nome_completo')
    else:
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
        # Trava de fechamento de lista
        if bloquear_avaliador:
            messages.error(request, 'Operação negada: A lista deste evento foi fechada automaticamente.')
            return redirect('gerenciar_inscricoes', evento_id=evento.id)

        inscricao_id = request.POST.get('inscricao_id')
        novo_status = request.POST.get('novo_status')
        
        if inscricao_id and novo_status in dict(Inscricao.STATUS_CHOICES).keys():
            inscricao = get_object_or_404(Inscricao, id=inscricao_id, evento=evento)
            status_anterior = inscricao.status
            
            # 🚨 TRAVA DE OVERBOOKING (Backend)
            if novo_status == 'APROVADA' and status_anterior != 'APROVADA':
                if evento_lotado:
                    messages.error(request, 'Erro: Não é possível aprovar. As vagas para este evento já estão esgotadas!')
                    return redirect('gerenciar_inscricoes', evento_id=evento.id)

            inscricao.status = novo_status
            inscricao.save()

            # --- Lógica de Envio de E-mail ---
            if novo_status == 'APROVADA' and status_anterior != 'APROVADA':
                enviar_email_confirmacao(inscricao, evento)
            # ---------------------------------
            
            # --- Lógica da Fila de Espera ---
            if status_anterior == 'APROVADA' and novo_status != 'APROVADA':
                promover_da_lista_espera(evento)
            # ---------------------------------

            messages.success(request, f'Status de {inscricao.nome_completo} atualizado para {inscricao.get_status_display()}.')
            return redirect('gerenciar_inscricoes', evento_id=evento.id)

    context = {
        'evento': evento,
        'inscricoes': inscricoes,
        'bloquear_avaliador': bloquear_avaliador,
        'prazo_encerrado': prazo_encerrado,
        'evento_lotado': evento_lotado, # Passando para o template
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

def consultar_inscricao(request):
    inscricoes = None
    buscou = False
    
    # Mantemos o GET para que o redirecionamento do cancelamento funcione
    cpf_buscado = request.GET.get('cpf', '').strip()
    email_buscado = request.GET.get('email', '').strip()
    anos_usuario = []
    agora = timezone.now()

    if cpf_buscado and email_buscado:
        buscou = True
        # Traz TODAS as inscrições do usuário
        inscricoes = Inscricao.objects.filter(cpf=cpf_buscado, email=email_buscado).order_by('-data_inscricao')
        
        # Coleta dinamicamente apenas os anos em que este usuário específico tem inscrições
        anos_set = set(i.evento.data_inicio.year for i in inscricoes if i.evento.data_inicio)
        anos_usuario = sorted(list(anos_set), reverse=True)
        
    elif 'cpf' in request.GET or 'email' in request.GET:
        messages.error(request, 'Por favor, informe o CPF e o E-mail para consultar.')

    return render(request, 'eventos/consultar_inscricao.html', {
        'inscricoes': inscricoes,
        'buscou': buscou,
        'cpf_buscado': cpf_buscado,
        'email_buscado': email_buscado,
        'anos_usuario': anos_usuario,
        'agora': agora,
    })

def cancelar_inscricao(request, inscricao_id):
    if request.method == 'POST':
        cpf = request.POST.get('cpf')
        email = request.POST.get('email')

        inscricao = get_object_or_404(Inscricao, id=inscricao_id, cpf=cpf, email=email)
        agora = timezone.now()

        # Monta a URL de volta mantendo a sessão de busca ativa
        url_retorno = reverse('consultar_inscricao') + f"?cpf={cpf}&email={email}"

        # 🚨 TRAVA DE TEMPO: Impede o cancelamento se as inscrições já fecharam
        if inscricao.evento.fim_inscricoes and agora > inscricao.evento.fim_inscricoes:
            messages.error(request, 'O período de inscrições para este evento já foi encerrado. Não é possível desistir da vaga neste momento.')
            return redirect(url_retorno)

        if inscricao.status in ['APROVADA', 'PENDENTE', 'LISTA_ESPERA']:
            status_anterior = inscricao.status
            # Mudando o status de acordo com o seu STATUS_CHOICES
            inscricao.status = 'RECUSADA' 
            inscricao.save()

            if status_anterior == 'APROVADA':
                promover_da_lista_espera(inscricao.evento)

            messages.success(request, f'Sua inscrição para "{inscricao.evento.titulo}" foi cancelada com sucesso.')
        else:
            messages.warning(request, 'Esta inscrição já se encontra cancelada ou recusada.')

        return redirect(url_retorno)
    
    return redirect('consultar_inscricao')

def link_curto_evento(request, evento_id):
    # Verifica se o evento existe, se não, dá erro 404
    evento = get_object_or_404(Evento, id=evento_id)
    
    # Redireciona o usuário para a rota oficial e completa de inscrição
    return redirect('inscricao_evento', evento_id=evento.id)


# 1. TELA DA EQUIPE: Exibe o QR Code
@user_passes_test(e_avaliador)
def tela_qrcode_checkin(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    return render(request, 'eventos/tela_qrcode.html', {'evento': evento})

# 2. API: Gera o link que expira
@user_passes_test(e_avaliador)
def api_gerar_token_qrcode(request, evento_id):
    signer = TimestampSigner()
    # Assina o ID do evento com um carimbo de tempo
    token = signer.sign(str(evento_id))
    
    # Monta a URL completa que vai para o QR Code
    url_base = request.build_absolute_uri(reverse('checkin_evento', args=[evento_id]))
    url_completa = f"{url_base}?token={token}"
    return JsonResponse({'url': url_completa})

# 3. TELA DO ALUNO: Onde ele digita o CPF
def checkin_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    signer = TimestampSigner()
    
    # Tenta pegar o token (seja pela URL ao escanear, ou pelo form ao enviar o CPF)
    token = request.GET.get('token') or request.POST.get('token')
    
    if not token:
        messages.error(request, 'Acesso bloqueado. Escaneie o QR Code oficial na recepção do evento.')
        return render(request, 'eventos/checkin_self_service.html', {'evento': evento, 'token_invalido': True})
        
    try:
        # UX: 45s para conseguir escanear e carregar a página. 3 minutos para digitar o CPF e enviar.
        tempo_limite = 180 if request.method == 'POST' else 45
        evento_id_assinado = signer.unsign(token, max_age=tempo_limite)
        
        if str(evento.id) != evento_id_assinado:
            raise BadSignature
            
    except (SignatureExpired, BadSignature):
        messages.error(request, 'O QR Code expirou! Por favor, escaneie novamente com a equipe da recepção.')
        return render(request, 'eventos/checkin_self_service.html', {'evento': evento, 'token_invalido': True})

    # A partir daqui, o token é válido!
    if request.method == 'POST':
        cpf_digitado = request.POST.get('cpf', '')
        
        # Limpa tudo o que não for número
        cpf_limpo = ''.join(filter(str.isdigit, cpf_digitado))
        
        if len(cpf_limpo) == 11:
            # Reconstrói a máscara perfeitamente para bater com o banco de dados
            cpf_formatado = f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}"
            
            # Busca com o CPF exato e mascarado
            inscricao = evento.inscricoes.filter(cpf=cpf_formatado).first()
            
            if inscricao:
                if inscricao.status == 'RECUSADA':
                    messages.error(request, 'Sua inscrição foi cancelada anteriormente.')
                else:
                    # Promove da fila de espera na hora
                    if inscricao.status == 'LISTA_ESPERA':
                        inscricao.status = 'APROVADA'
                    
                    inscricao.compareceu = True
                    
                    # --- REGRA DE MÚLTIPLAS SESSÕES COM COOLDOWN DE 2 HORAS ---
                    agora = timezone.now()
                    intervalo_minimo = timedelta(hours=2)
                    
                    # Verifica se é o primeiro check-in OU se já passou o tempo mínimo
                    if not inscricao.ultimo_checkin or (agora - inscricao.ultimo_checkin) > intervalo_minimo:
                        inscricao.total_presencas += 1
                        inscricao.ultimo_checkin = agora
                        inscricao.save()
                        
                        messages.success(request, f'✅ Presença {inscricao.total_presencas}/{evento.total_sessoes} confirmada! Bem-vindo(a), {inscricao.nome_completo.split()[0]}!')
                    else:
                        # Tocou o QR code de novo antes de 2 horas na mesma sessão
                        messages.info(request, f'Você já registrou sua presença nesta sessão! (Frequência atual: {inscricao.percentual_frequencia}%)')
            else:
                messages.warning(request, 'Inscrição não encontrada. Preencha seus dados rapidamente.')
                
                # Chama a 'inscricao_evento' normal, passando o CPF já mascarado e o Token de autorização VIP
                url_inscricao = reverse('inscricao_evento', args=[evento.id])
                return redirect(f"{url_inscricao}?cpf={cpf_formatado}&token={token}")
                
    return render(request, 'eventos/checkin_self_service.html', {'evento': evento, 'token': token})
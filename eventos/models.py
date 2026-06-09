from django.db import models
from django.utils import timezone


class GrupoEvento(models.Model):
    nome = models.CharField(max_length=200, help_text="Ex: Oficina de Python (Engloba Turma Manhã e Turma Tarde)")
    descricao = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = 'Grupo de Evento'
        verbose_name_plural = 'Grupos de Eventos'

class Evento(models.Model):
    titulo = models.CharField(max_length=200)
    descricao = models.TextField()
    imagem_capa = models.ImageField(upload_to='capas_eventos/', blank=True, null=True)
    local = models.CharField(max_length=255, blank=True, null=True, verbose_name="Local do Evento")
    vagas_totais = models.PositiveIntegerField()
    aberto_comunidade = models.BooleanField(default=False, verbose_name="Aberto à comunidade externa?")
    tem_questionario = models.BooleanField(default=False, verbose_name="Habilitar questionário extra?")
    questionario = models.JSONField(default=list, blank=True, null=True)
    # --- NOVOS CAMPOS: Período de Inscrição ---
    inicio_inscricoes = models.DateTimeField(verbose_name="Início das Inscrições", null=True)
    fim_inscricoes = models.DateTimeField(verbose_name="Fim das Inscrições", null=True)
    grupo = models.ForeignKey(GrupoEvento, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos', help_text="Selecione um grupo se este evento tiver outras turmas/horários correlacionados.")
    # --- Período de Realização do Evento ---
    data_inicio = models.DateTimeField(verbose_name="Início do Evento")
    data_fim = models.DateTimeField(verbose_name="Término do Evento")
    total_sessoes = models.PositiveIntegerField(default=1, verbose_name="Total de Dias/Sessões")
    frequencia_minima = models.PositiveIntegerField(default=75, verbose_name="Frequência Mínima (%) para Certificado")

    aprovacao_automatica = models.BooleanField(
        default=False,
        verbose_name="Aprovação Automática",
        help_text="Se ativado, os inscritos serão aprovados automaticamente ao enviarem o formulário."
    )
    
    def __str__(self):
        return self.titulo

    @property
    def vagas_restantes(self):
        aprovados = self.inscricoes.filter(status='APROVADA').count()
        return max(0, self.vagas_totais - aprovados)

    @property
    def inscricoes_abertas(self):
        # Retorna True se a data atual estiver entre o início e o fim das inscrições
        agora = timezone.now()
        if self.inicio_inscricoes and self.fim_inscricoes:
            return self.inicio_inscricoes <= agora <= self.fim_inscricoes
        return False

    class Meta:
        verbose_name = 'Evento'
        verbose_name_plural = 'Eventos'



class Inscricao(models.Model):
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('APROVADA', 'Aprovada'),
        ('RECUSADA', 'Recusada'),
        ('LISTA_ESPERA', 'Lista de Espera'),
    ]

    evento = models.ForeignKey(Evento, related_name='inscricoes', on_delete=models.CASCADE)
    nome_completo = models.CharField(max_length=255)
    email = models.EmailField()
    cpf = models.CharField(max_length=14) # Validaremos no form/js
    
    # Campos condicionais (vínculo universidade)
    tem_vinculo_universidade = models.BooleanField(default=True)
    matricula = models.CharField(max_length=50, blank=True, null=True)
    curso_turma = models.CharField(max_length=100, blank=True, null=True)
    
    # Campos para a planilha de certificados (podem ser nulos conforme sua regra)
    trabalho = models.CharField(max_length=255, blank=True, null=True)
    orientador = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    data_inscricao = models.DateTimeField(auto_now_add=True)
    respostas_questionario = models.JSONField(default=dict, blank=True, null=True)
    compareceu = models.BooleanField(default=False, verbose_name="Check-in Realizado")
    inscricao_local = models.BooleanField(default=False, verbose_name="Inscrito na Hora")
    total_presencas = models.PositiveIntegerField(default=0, verbose_name="Total de Presenças")
    ultimo_checkin = models.DateTimeField(null=True, blank=True, verbose_name="Último Check-in")
    @property
    def percentual_frequencia(self):
        if self.evento.total_sessoes == 0:
            return 0
        return int((self.total_presencas / self.evento.total_sessoes) * 100)

    @property
    def aprovado_certificado(self):
        return self.percentual_frequencia >= self.evento.frequencia_minima
    
    def __str__(self):
        return f"{self.nome_completo} - {self.evento.titulo}"
    
    class Meta:
        verbose_name = 'Inscrição'
        verbose_name_plural = 'Inscrições'
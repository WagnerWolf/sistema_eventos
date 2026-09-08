from django import forms
from .models import Evento

class EventoForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = [
            'titulo', 'descricao', 'local', 'grupo', 'vagas_totais', 
            'aberto_comunidade', 'inicio_inscricoes', 'fim_inscricoes', 
            'data_inicio', 'data_fim', 'imagem_capa',
            'tem_questionario', 'questionario', 'aprovacao_automatica',
            'total_sessoes', 'frequencia_minima'
        ]
        
        # Widgets para garantir a estilização correta e limites de caracteres
        widgets = {
            'inicio_inscricoes': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control bg-dark text-white border-secondary'}),
            'fim_inscricoes': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control bg-dark text-white border-secondary'}),
            'data_inicio': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control bg-dark text-white border-secondary'}),
            'data_fim': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control bg-dark text-white border-secondary'}),
            'descricao': forms.Textarea(attrs={'rows': 4, 'class': 'form-control bg-dark text-white border-secondary'}),
            'grupo': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            
            # 🚨 ADICIONADO: maxlength="200"
            'titulo': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-white border-secondary',
                'maxlength': '200'
            }),
            
            # 🚨 ADICIONADO: maxlength="255"
            'local': forms.TextInput(attrs={
                'class': 'form-control bg-dark text-white border-secondary',
                'maxlength': '255'
            }),
            
            'vagas_totais': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary'}),
            'aberto_comunidade': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'imagem_capa': forms.FileInput(attrs={'class': 'form-control bg-dark text-white border-secondary'}),
            'tem_questionario': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'switchQuestionario'}),
            'questionario': forms.HiddenInput(attrs={'id': 'jsonQuestionario'}),
            'aprovacao_automatica': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            
            'total_sessoes': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-white border-secondary',
                'min': '1',
            }),
            'frequencia_minima': forms.NumberInput(attrs={
                'class': 'form-control bg-dark text-white border-secondary',
                'min': '1',
                'max': '100',
            }),
        }
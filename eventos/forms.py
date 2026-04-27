from django import forms
from .models import Evento

class EventoForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = [
            'titulo', 'descricao', 'local', 'vagas_totais', 
            'aberto_comunidade', 'inicio_inscricoes', 'fim_inscricoes', 
            'data_inicio', 'data_fim', 'imagem_capa',
            'tem_questionario', 'questionario'
        ]
        # Widgets para garantir que o navegador mostre o seletor de data e hora
        widgets = {
            'inicio_inscricoes': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'fim_inscricoes': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'data_inicio': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'data_fim': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'local': forms.TextInput(attrs={'class': 'form-control'}),
            'vagas_totais': forms.NumberInput(attrs={'class': 'form-control'}),
            'aberto_comunidade': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'imagem_capa': forms.FileInput(attrs={'class': 'form-control'}),
            'tem_questionario': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'switchQuestionario'}),
            'questionario': forms.HiddenInput(attrs={'id': 'jsonQuestionario'}),
        }
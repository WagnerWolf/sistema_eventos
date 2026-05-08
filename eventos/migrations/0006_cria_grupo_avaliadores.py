from django.db import migrations

def criar_perfil_avaliador(apps, schema_editor):
    # Usamos apps.get_model para garantir compatibilidade com o histórico do banco
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    # Cria o grupo "Avaliadores" (se não existir, ele cria; se existir, ele pega)
    grupo_avaliadores, created = Group.objects.get_or_create(name='Avaliadores')

    # Codinomes exatos das permissões necessárias no Django
    permissoes_necessarias = [
        'view_inscricao',
        'change_inscricao',
        'view_evento',
        'view_grupoevento'
    ]

    # Busca essas permissões no banco de dados
    permissoes = Permission.objects.filter(codename__in=permissoes_necessarias)

    # Atribui as permissões ao grupo
    grupo_avaliadores.permissions.set(permissoes)

class Migration(migrations.Migration):

    dependencies = [
        ('eventos', '0001_initial'), # ATENÇÃO: Mantenha a dependência que o Django gerou automaticamente no seu arquivo original
        ('auth', '__latest__'),      # Garante que as tabelas de permissão do Django já existam
    ]

    operations = [
        migrations.RunPython(criar_perfil_avaliador),
    ]
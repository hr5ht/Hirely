from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command('createcachetable', database=schema_editor.connection.alias)


class Migration(migrations.Migration):
    """The database cache table, created here so `migrate` stays the only deploy step."""

    dependencies = [('ai_engine', '0019_companyinvite')]

    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]

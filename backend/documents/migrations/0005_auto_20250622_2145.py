# Generated by Django 5.0.14 on 2025-06-22 21:45

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0004_auto_20250622_1116'),
    ]

    operations = [
        # First remove the form_template field from Record
        migrations.RemoveField(
            model_name='record',
            name='form_template',
        ),
        
        # Then delete the FormTemplate model
        migrations.DeleteModel(
            name='FormTemplate',
        ),
        
        # Add new form_document field to Record
        migrations.AddField(
            model_name='record',
            name='form_document',
            field=models.ForeignKey(
                limit_choices_to={'document_type': 'FORM'},
                on_delete=django.db.models.deletion.PROTECT,
                related_name='records',
                to='documents.document'
            ),
        ),
    ]

# Generated by Django 4.2.7 on 2023-12-12 00:26

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0011_commitreport_report_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repositoryflag",
            name="flag_name",
            field=models.CharField(max_length=1024),
        ),
    ]
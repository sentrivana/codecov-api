# Generated by Django 3.1.13 on 2021-09-23 02:43

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("compare", "0002_commitcomparison_patch_totals")]

    operations = [
        migrations.AddField(
            model_name="commitcomparison",
            name="error",
            field=models.TextField(
                choices=[
                    ("missing_base_report", "Missing Base Report"),
                    ("missing_head_report", "Missing Head Report"),
                ],
                null=True,
            ),
        )
    ]

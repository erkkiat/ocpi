from django.db import migrations, models
import django.db.models.deletion
import logging

logger = logging.getLogger(__name__)


def migrate_empty_logos(apps, schema_editor):
    BusinessDetails = apps.get_model('ocpi22', 'BusinessDetails')

    howmany = BusinessDetails.objects.filter(logo='').update(logo=None)
    logger.info(f"Removed {howmany} empty logos")


def migrate_logos_to_ocpi_images(apps, schema_editor):
    BusinessDetails = apps.get_model('ocpi22', 'BusinessDetails')
    OCPIImage = apps.get_model('ocpi22', 'OCPIImage')
    Location = apps.get_model('ocpi22', 'Location')

    def migrate_logo(migrate_business, migrate_category):
        if migrate_business.logo and migrate_business.logo.strip():
            ocpi_image = OCPIImage.objects.create(
                url=migrate_business.logo, category=migrate_category, image_type='jpeg'
            )
            migrate_business.logo = ocpi_image
            migrate_business.save()

    for business in BusinessDetails.objects.all():
        migrate_logo(business, 'OPERATOR')

    for location in Location.objects.all():
        for field, category in [('operator', 'OPERATOR'), ('suboperator', 'OPERATOR'), ('owner', 'OWNER')]:
            related_business = getattr(location, field, None)
            if related_business:
                migrate_logo(related_business, category)


class Migration(migrations.Migration):

    dependencies = [
        ('ocpi22', '0012_solidtariff'),
    ]

    operations = [
        migrations.AlterField(
            model_name='businessdetails',
            name='logo',
            field=models.CharField(max_length=255, blank=True, null=True),
        ),
        migrations.RunPython(migrate_empty_logos),
        migrations.CreateModel(
            name='OCPIImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.URLField()),
                ('thumbnail', models.URLField(blank=True, null=True)),
                ('category', models.CharField(choices=[('CHARGER', 'Charger'), ('ENTRANCE', 'Entrance'), ('LOCATION', 'Location'), ('NETWORK', 'Network'), ('OPERATOR', 'Operator'), ('OTHER', 'Other'), ('OWNER', 'Owner')], max_length=8)),
                ('image_type', models.CharField(max_length=4)),
                ('width', models.PositiveIntegerField(blank=True, null=True)),
                ('height', models.PositiveIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.AlterField(
            model_name='businessdetails',
            name='logo',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='ocpi22.ocpiimage'),
        ),
        migrations.RunPython(migrate_logos_to_ocpi_images),
    ]

from django.db import migrations


def migrate_payment_methods(apps, schema_editor):
    Facility = apps.get_model('facilities', 'Facility')
    PaymentMethod = apps.get_model('facilities', 'FacilityPaymentMethod')
    alias = schema_editor.connection.alias
    for facility in Facility.objects.using(alias).all().iterator():
        methods = []
        if facility.gcash_number.strip():
            methods.append(('GCash', facility.gcash_number))
        if facility.maya_number.strip():
            methods.append(('Maya', facility.maya_number))
        if facility.accepts_card:
            methods.append(('Card', ''))
        if facility.payment_qr_image and not methods:
            methods.append((facility.payout_qr_label or 'Merchant QR', ''))
        for order, (label, number) in enumerate(methods):
            label = label[:60]
            if not PaymentMethod.objects.using(alias).filter(
                facility_id=facility.pk, label=label,
            ).exists():
                PaymentMethod.objects.using(alias).create(
                    facility_id=facility.pk,
                    label=label,
                    account_name=facility.wallet_account_name,
                    account_number=number,
                    qr_image=facility.payment_qr_image.name,
                    is_active=True,
                    display_order=order,
                )


class Migration(migrations.Migration):
    dependencies = [
        ('facilities', '0009_facilitypaymentmethod'),
    ]

    operations = [
        migrations.RunPython(migrate_payment_methods, migrations.RunPython.noop),
    ]

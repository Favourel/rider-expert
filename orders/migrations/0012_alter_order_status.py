# Generated by Django 4.1.6 on 2025-01-02 21:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0011_alter_order_value_alter_order_weight'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('PendingPickup', 'Pending Pickup'), ('WaitingForPickup', 'Waiting for pickup'), ('PickedUp', 'Picked up'), ('InTransit', 'In transit'), ('Arrived', 'Arrived'), ('Delivered', 'Delivered'), ('Failed', 'Failed'), ('Cancelled', 'Cancelled'), ('Created', 'Created'), ('RiderSearch', 'RiderSearch'), ('Assigned', 'Assigned'), ('PartiallyAssigned', 'Partially Assigned')], default='Created', max_length=20),
        ),
    ]
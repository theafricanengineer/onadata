# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('main', '0002_auto_20150717_1149'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfileGroupObjectPermission',
            fields=[
                ('id', models.AutoField(
                    verbose_name='ID', serialize=False, auto_created=True,
                    primary_key=True)),
                ('content_object', models.ForeignKey(
                    to='main.UserProfile', on_delete=models.CASCADE)),
                ('group', models.ForeignKey(to='auth.Group',
                    on_delete=models.CASCADE)),
                ('permission', models.ForeignKey(
                    to='auth.Permission', on_delete=models.CASCADE)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='UserProfileUserObjectPermission',
            fields=[
                ('id', models.AutoField(
                    verbose_name='ID', serialize=False, auto_created=True,
                    primary_key=True)),
                ('content_object', models.ForeignKey(
                    to='main.UserProfile', on_delete=models.CASCADE)),
                ('permission', models.ForeignKey(
                    to='auth.Permission', on_delete=models.CASCADE)),
                ('user', models.ForeignKey(
                    to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='userprofileuserobjectpermission',
            unique_together=set([('user', 'permission', 'content_object')]),
        ),
        migrations.AlterUniqueTogether(
            name='userprofilegroupobjectpermission',
            unique_together=set([('group', 'permission', 'content_object')]),
        ),
    ]

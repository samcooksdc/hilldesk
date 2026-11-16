# SPDX-License-Identifier: Apache-2.0
"""
Management command to update user credentials.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Update user credentials'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Username to update')
        parser.add_argument('--new-username', type=str, help='New username')
        parser.add_argument('--password', type=str, help='New password')
        parser.add_argument('--email', type=str, help='New email')

    def handle(self, *args, **options):
        username = options['username']
        new_username = options.get('new_username')
        password = options.get('password')
        email = options.get('email')

        if not username:
            self.stdout.write(
                self.style.ERROR('Username is required. Use --username')
            )
            return

        try:
            user = User.objects.get(username=username)
            
            if new_username:
                user.username = new_username
                self.stdout.write(f'Updated username to: {new_username}')
            
            if password:
                user.set_password(password)
                self.stdout.write('Updated password')
            
            if email:
                user.email = email
                self.stdout.write(f'Updated email to: {email}')
            
            user.save()
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully updated user: {user.username}')
            )
            
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User "{username}" not found')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error updating user: {str(e)}')
            )
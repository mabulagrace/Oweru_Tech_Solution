"""Issue (or list) API bearer tokens for staff users.

Usage:
    python manage.py api_token <username>           # create a token
    python manage.py api_token --list               # list existing tokens
    python manage.py api_token <username> --name marketing-site
"""

import secrets

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import ApiToken


class Command(BaseCommand):
    help = 'Issue API bearer tokens for the v1 REST API.'

    def add_arguments(self, parser):
        parser.add_argument('username', nargs='?')
        parser.add_argument('--list', action='store_true', help='List existing tokens')
        parser.add_argument('--name', default='', help='Token label')

    def handle(self, *args, **options):
        if options.get('list'):
            for token in ApiToken.objects.select_related('user').order_by('-created_at'):
                self.stdout.write(
                    f'{token.user.username} | {token.name or "-"} | {token.key} '
                    f'| active={token.is_active} | last_used={token.last_used:%Y-%m-%d %H:%M if token.last_used else "never"}'
                )
            return

        username = options.get('username')
        if not username:
            raise CommandError('Provide a username or use --list.')

        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f'User "{username}" does not exist.')
        if not user.is_staff:
            raise CommandError(f'User "{username}" is not staff and cannot hold an API token.')

        key = secrets.token_hex(24)
        token = ApiToken.objects.create(user=user, key=key, name=options.get('name', ''))
        self.stdout.write(self.style.SUCCESS('Token created:'))
        self.stdout.write(key)
        self.stdout.write(self.style.WARNING('Store it somewhere safe - it is shown once.'))
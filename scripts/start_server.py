#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""
Start script for HillDesk.
This ensures the correct settings are used.
"""
import os
import sys
import django
from django.core.management import execute_from_command_line

if __name__ == '__main__':
    # Make the project root importable (this script lives in scripts/).
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # Ensure we're using development settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
    
    # Remove any conflicting environment variables
    if 'DJANGO_SETTINGS_MODULE' in os.environ and os.environ['DJANGO_SETTINGS_MODULE'] == 'config.settings.testing':
        os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.development'
    
    try:
        django.setup()
        print("[OK] Django setup successful with development settings")
        print("Starting development server...")
        execute_from_command_line(['manage.py', 'runserver', '127.0.0.1:8000'])
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc


        
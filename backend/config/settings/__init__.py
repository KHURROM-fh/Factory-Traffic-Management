"""
Settings package initialization.
Selects development or production settings based on DJANGO_ENV environment variable.
"""

import os

env = os.getenv('DJANGO_ENV', 'development').lower()

if env == 'production':
    from .production import *
else:
    from .development import *

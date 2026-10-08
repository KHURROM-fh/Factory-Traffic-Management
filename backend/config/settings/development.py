"""
Development settings for Factory Traffic Management System.
"""

from .base import *

DEBUG = env('DEBUG', cast=bool, default=True)

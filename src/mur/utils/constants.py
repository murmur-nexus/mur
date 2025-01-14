"""Constants used throughout the Mur CLI."""

import os
from pathlib import Path

# API endpoints
MURMUR_SERVER_URL = os.getenv('MURMUR_SERVER_URL', 'https://api.murmur.nexus/v1')

# Configuration
CONFIG_DIR = Path.home() / '.murmur'
CONFIG_FILE = CONFIG_DIR / 'config.json'
DEFAULT_CACHE_DIR = CONFIG_DIR / 'cache'
DEFAULT_TIMEOUT = 30

# PyPI Server
MURMUR_INDEX_URL = os.getenv('MURMUR_INDEX_URL')
MURMUR_EXTRAS_INDEX_URL = os.getenv('MURMUR_EXTRAS_INDEX_URL')
DEFAULT_MURMUR_INDEX_URL = 'https://artifacts.murmur.nexus/simple'
DEFAULT_MURMUR_EXTRA_INDEX_URLS = [
    'https://pypi.org/simple',
]
PYPI_USERNAME = os.getenv('PYPI_USERNAME', 'admin')  # local defaults
PYPI_PASSWORD = os.getenv('PYPI_PASSWORD', 'admin')  # local defaults

# Config paths
MURMURRC_PATH = Path.home() / '.murmurrc'

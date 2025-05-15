# -*- coding: utf-8 -*-

import os

BOT_VERSION = "6.2.0"
BACKUP_DIR = 'db_backups'

def get_base_dir():
    import os, sys
    return os.path.dirname(os.path.abspath(sys.argv[0]))

def get_env_path():
    return os.path.join(get_base_dir(), ".env")

def get_db_file_path():
    return os.path.join(get_base_dir(), "frags.db")

def get_sounds_path():
    return os.path.join(get_base_dir(), "sounds")

import os


def get_data_dir():
    configured = os.environ.get('MNEMOSYNE_DATA_DIR')
    if configured:
        return os.path.abspath(os.path.expanduser(configured))

    if os.name == 'nt':
        base_dir = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    else:
        base_dir = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base_dir, 'mnemosyne')
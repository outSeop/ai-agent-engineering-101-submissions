"""Read-only server inventory; print metadata, never credentials or key content."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


def command(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return {'exit_code': p.returncode, 'stdout': p.stdout[:1800], 'stderr': p.stderr[:500]}
    except Exception as error:
        return {'error_type': type(error).__name__}


home = Path.home()
app = home / '.local/share/ourolabs-r4-checkout'
code = home / '.config/ourolabs-market/owner-code'
report = {'hostname': socket.gethostname(), 'user': os.environ.get('USER'), 'home': str(home),
          'python': sys.version.split()[0], 'architecture': os.uname().machine,
          'expected_checkout_exists': app.exists(), 'owner_credential_present': code.is_file(),
          'cloudflared': shutil.which('cloudflared'), 'systemctl': shutil.which('systemctl'),
          'disk_free_bytes': shutil.disk_usage(home).free,
          'python_candidates': [str(p) for p in [*home.glob('.local/share/uv/python/*/bin/python3.12'),
                                               *home.glob('.local/share/uv/python/*/bin/python3.13')]
                                if p.is_file()],
          'user_manager': command(['systemctl', '--user', 'is-system-running']),
          'r4_service': command(['systemctl', '--user', 'show', 'ourolabs-market-r4.service',
                                 '-p', 'LoadState', '-p', 'ActiveState', '-p', 'MainPID']),
          'linger': command(['loginctl', 'show-user', str(os.getuid()), '-p', 'Linger']),
          'r4_local_app_port_in_use': command(['sh', '-c', "ss -ltn '( sport = :18804 )' 2>/dev/null"])}
print(json.dumps(report, ensure_ascii=False))

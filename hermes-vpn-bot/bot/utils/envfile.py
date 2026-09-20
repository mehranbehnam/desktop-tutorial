"""Read/write this app's own .env — shared by every admin-facing "set a
config value" flow (Cloudflare/GitHub tokens, card number, Iran SSH, the
generic /setenv command) so there's exactly one place that knows the file's
layout and the services' naming convention.
"""
import os


def env_path() -> str:
    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(bot_dir, ".env")


def service_names() -> tuple[str, str]:
    """(sales-bot service, dev-bot service) — matches setup_iran_vpn.sh's `${SVC}-dev` naming."""
    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    install_dir = os.path.dirname(bot_dir)
    service = os.path.basename(install_dir)
    return service, f"{service}-dev"


def set_env_var(path: str, key: str, value: str):
    lines = []
    if os.path.isfile(path):
        with open(path) as fh:
            lines = fh.readlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(path, "w") as fh:
        fh.writelines(lines)

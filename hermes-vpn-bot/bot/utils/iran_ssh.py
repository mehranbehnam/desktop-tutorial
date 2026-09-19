"""SSH into the Iran panel server's OS, for the handful of things the X-UI
panel's HTTP API has no endpoint for: fail2ban's ban list/unban, and
restarting the panel process itself (as opposed to just the Xray core
inside it, which the API does support).

This only works because it runs inside the bot process on Nautilus, which
has ordinary unrestricted internet access — nothing about the surrounding
sandbox that builds this code can reach the Iran server directly.
"""
import config

try:
    import paramiko
except ImportError:  # pragma: no cover - only missing before the first /update
    paramiko = None


class IranSSHError(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.IRAN_SSH_HOST and config.IRAN_SSH_USER and config.IRAN_SSH_PASSWORD)


def run(command: str, timeout: int = 20) -> tuple[str, str]:
    """Run one command on the Iran server; returns (stdout, stderr)."""
    if paramiko is None:
        raise IranSSHError("ماژول paramiko هنوز نصب نیست؛ یک بار /update بزن.")
    if not configured():
        raise IranSSHError("SSH سرور ایران تنظیم نشده — از دکمه‌ی 🔑 تنظیم SSH سرور ایران استفاده کن.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            config.IRAN_SSH_HOST, port=config.IRAN_SSH_PORT,
            username=config.IRAN_SSH_USER, password=config.IRAN_SSH_PASSWORD,
            timeout=timeout,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        return out, err
    except paramiko.AuthenticationException as e:
        raise IranSSHError(f"احراز هویت SSH ناموفق: {e}") from e
    except Exception as e:
        raise IranSSHError(f"{type(e).__name__}: {e}") from e
    finally:
        client.close()


def write_file(remote_path: str, content: str, mode: int = 0o600):
    """Write `content` to `remote_path` on the Iran server over SFTP.

    Used for TLS cert/key material, where a shell heredoc would be one
    stray character away from corrupting a PEM block — SFTP writes the
    bytes directly, no shell quoting involved.
    """
    if paramiko is None:
        raise IranSSHError("ماژول paramiko هنوز نصب نیست؛ یک بار /update بزن.")
    if not configured():
        raise IranSSHError("SSH سرور ایران تنظیم نشده — از دکمه‌ی 🔑 تنظیم SSH سرور ایران استفاده کن.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            config.IRAN_SSH_HOST, port=config.IRAN_SSH_PORT,
            username=config.IRAN_SSH_USER, password=config.IRAN_SSH_PASSWORD,
            timeout=20,
        )
        sftp = client.open_sftp()
        try:
            with sftp.open(remote_path, "w") as fh:
                fh.write(content)
            sftp.chmod(remote_path, mode)
        finally:
            sftp.close()
    except paramiko.AuthenticationException as e:
        raise IranSSHError(f"احراز هویت SSH ناموفق: {e}") from e
    except Exception as e:
        raise IranSSHError(f"{type(e).__name__}: {e}") from e
    finally:
        client.close()

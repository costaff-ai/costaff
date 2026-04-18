import subprocess
from dotenv import load_dotenv
from rich.console import Console

from utils.helpers import PATHS, _project_root, _runtime_root, _runtime_root
from managers.config import ConfigManager

console = Console()

# Map platform shortcodes to bot service names
BOT_SERVICE = {"tg": "bot-telegram", "dc": "bot-discord", "line": "bot-line"}


class DockerManager:
    @staticmethod
    def get_cmd():
        try:
            subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
            return ["docker", "compose"]
        except Exception:
            return ["docker-compose"]

    @staticmethod
    def get_compose_cwd(compose_file: str) -> str:
        import os
        costaff_dir = _runtime_root
        if os.path.exists(os.path.join(costaff_dir, compose_file)):
            return costaff_dir
        return _project_root

    @staticmethod
    def run_action(service: str, action: str):
        # Refresh process environment before calling docker
        load_dotenv(PATHS["env"], override=True)
        conf = ConfigManager.get_config()
        compose_file = "docker-compose.yaml"
        compose_cwd = DockerManager.get_compose_cwd(compose_file)

        # Determine services to act upon
        target_services = [service]
        if service == "costaff-agent" and action == "restart":
            # If agent restarts, also restart all bots to reset sessions
            for p in conf.get("channels", []):
                bot_service = BOT_SERVICE.get(p, f"bot-{p}")
                target_services.append(bot_service)

        for s in target_services:
            if action == "restart":
                # Force stop then start with recreate to ensure environment variables are fresh
                console.print(f"Force-restarting {s} to reload environment and reset sessions...")
                stop_cmd = DockerManager.get_cmd() + ["-f", compose_file, "stop", s]
                subprocess.run(stop_cmd, check=False, cwd=compose_cwd)

                up_cmd = DockerManager.get_cmd() + ["-f", compose_file, "up", "-d", "--force-recreate", s]
                subprocess.run(up_cmd, check=True, cwd=compose_cwd)
            elif action == "start":
                up_cmd = DockerManager.get_cmd() + ["-f", compose_file, "up", "-d", s]
                subprocess.run(up_cmd, check=True, cwd=compose_cwd)
            else:
                cmd = DockerManager.get_cmd() + ["-f", compose_file, action, s]
                subprocess.run(cmd, check=True, cwd=compose_cwd)

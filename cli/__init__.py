import typer

from utils.helpers import VERSION
from cli.commands.services import start, stop, status, logs
from cli.commands.onboard import onboard
from cli.commands.dashboard import dashboard, chat
from cli.commands.license_cmd import license
from cli.commands.agent import agent_app
from cli.commands.channel import channel_app
from cli.commands.database import db_app

app = typer.Typer(help=f"CoStaff Agent Ecosystem CLI v{VERSION}", rich_markup_mode="rich")

# Register direct commands
app.command()(onboard)
app.command()(start)
app.command()(stop)
app.command()(status)
app.command()(logs)
app.command()(dashboard)
app.command()(chat)
app.command()(license)

# Register subgroups
app.add_typer(agent_app, name="agent")
app.add_typer(channel_app, name="channel")
app.add_typer(db_app, name="database")

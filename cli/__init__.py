import typer

from utils.paths import VERSION
from cli.commands.lifecycle import start, stop, status, logs, restart
from cli.commands.onboard import onboard
from cli.commands.dashboard import dashboard, chat, invoke
from cli.commands.licensing import license
from cli.commands.agent import agent_app
from cli.commands.channel import channel_app
from cli.commands.config import config_app
from cli.commands.database import db_app
from cli.commands.doctor import doctor
from cli.commands.update import update

app = typer.Typer(help=f"CoStaff Agent Ecosystem CLI v{VERSION}", rich_markup_mode="rich")

# Register direct commands
app.command()(onboard)
app.command()(start)
app.command()(stop)
app.command()(restart)
app.command()(status)
app.command()(logs)
app.command()(dashboard)
app.command()(chat)
app.command()(invoke)
app.command()(license)

# Register subgroups
app.add_typer(agent_app, name="agent")
app.add_typer(channel_app, name="channel")
app.add_typer(config_app, name="config")
app.add_typer(db_app, name="database")
app.command()(doctor)
app.command()(update)

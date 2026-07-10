import os

from setuptools import setup

# Single source of truth for the version is the VERSION file (also read by
# utils/paths.py for CLI display). "v0.1.0-beta-1" → "0.1.0-beta-1", which
# setuptools normalizes to the PEP 440 form "0.1.0b1".
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")) as f:
    _version = f.read().strip().removeprefix("v")

setup(
    name="costaff-cli",
    version=_version,
    description="CoStaff Agent Ecosystem CLI by CoStaff",
    author="Simon Liu",
    python_requires=">=3.10",
    py_modules=["costaff"],
    install_requires=[
        "typer",
        "rich",
        "questionary",
        "python-dotenv",
        "httpx",
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "alembic",
        "cryptography",
        "pyyaml",
        "psutil",
        "psycopg2-binary",
    ],
    entry_points={
        "console_scripts": [
            "costaff=costaff:app",
        ],
    },
)

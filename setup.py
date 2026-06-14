from setuptools import setup

setup(
    name="costaff-cli",
    version="0.1.0a2",
    description="CoStaff Agent Ecosystem CLI by CoStaff",
    author="Simon Liu",
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

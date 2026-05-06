from setuptools import setup, find_packages

setup(
    name="a8_agent",
    version="0.1.0",
    description="A8 cadence draft generation and orchestration",
    author="Jamal",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "fastapi>=0.104",
        "uvicorn[standard]>=0.24",
        "asyncpg>=0.29",
        "sqlalchemy>=2.0",
        "psycopg2-binary>=2.9",
        "pydantic>=2.5",
        "python-dotenv>=1.0",
    ],
)

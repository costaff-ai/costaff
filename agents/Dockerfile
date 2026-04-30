FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Place agent under /app/agents/ so ADK web scans only that directory,
# avoiding collisions with /app/data/ (bind-mounted at runtime).
COPY costaff_agent /app/agents/costaff_agent

WORKDIR /app/agents

EXPOSE 8080

CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8080", "."]

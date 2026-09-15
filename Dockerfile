FROM python:3.14-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY chat_config.py .
COPY composants.py .
COPY logic ./logic
COPY sql ./sql
COPY mcp_server ./mcp_server
COPY www ./www

# Port 8022, et non 8000 : le serveur heberge une douzaine d'applications et
# le port 8000 est deja occupe par "guichet-entrepreneur". Un deploiement sur
# 8000 echouerait au demarrage, ou prendrait le port d'une autre application
# en service. Ce numero doit rester coherent avec docker-compose.yml (qui le
# publie sur 127.0.0.1:8022) et avec le reverse proxy de l'hote.
EXPOSE 8022

CMD ["shiny", "run", "--host", "0.0.0.0", "--port", "8022", "app.py"]

FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["python", "-m", "datamate.cli"]


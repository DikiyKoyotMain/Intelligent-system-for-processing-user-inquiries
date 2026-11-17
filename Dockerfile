FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SUPPORT_HOST=0.0.0.0
WORKDIR /app
COPY requirements-container.lock /app/requirements-container.lock
RUN pip install --no-cache-dir -r requirements-container.lock && useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser src /app/src
COPY --chown=appuser:appuser scripts /app/scripts
COPY --chown=appuser:appuser configs /app/configs
COPY --chown=appuser:appuser data/demo /app/data/demo
RUN mkdir /app/work && chown appuser:appuser /app/work
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/knowledge/ready',timeout=3)"
CMD ["python", "scripts/start_demo.py"]

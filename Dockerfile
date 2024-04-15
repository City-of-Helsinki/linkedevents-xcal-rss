FROM python:3.12 as app

WORKDIR /opt/app

RUN addgroup --system app && \
    adduser --system --group app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src /opt/app

RUN chown -R app:app /opt/app

USER app

CMD ["python3", "main.py"]

EXPOSE 8000/TCP
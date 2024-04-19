FROM python:3.12 as app

WORKDIR /opt/app

RUN addgroup --system app && \
    adduser --system --group app

COPY requirements.txt .

RUN apt-get update && apt-get install -y memcached
RUN mkdir /var/run/memcached/
RUN chown nobody:nogroup /var/run/memcached
RUN chmod 0777 /var/run/memcached

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src /opt/app

RUN chmod 0755 entrypoint.sh
RUN chown -R app:app /opt/app

USER app

CMD ["/bin/sh", "-c", "/opt/app/entrypoint.sh"]

EXPOSE 8000/TCP
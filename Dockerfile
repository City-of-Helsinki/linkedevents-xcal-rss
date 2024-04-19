FROM python:3.12 as app

WORKDIR /opt/app

RUN addgroup --system app && \
    adduser --system --group app

COPY requirements.txt .

RUN apt install -y memcached
RUN mkdir /var/run/memcached/
RUN chown nobody:nogroup /var/run/memcached
RUN chmod 0777 /var/run/memcached

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src /opt/app

RUN chown -R app:app /opt/app

USER app

CMD ["/bin/bash", "-c" "memcached -d -m 1024 -u memcache -c 1024 -P /var/run/memcached/memcached.pid -s /var/run/memcached/memcached.sock -a 0755;python3 main.py"]

EXPOSE 8000/TCP
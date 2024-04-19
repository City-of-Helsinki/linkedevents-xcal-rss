#! /bin/bash
sudo apt update && apt upgrade
sudo apt install -y memcached
sudo mkdir /var/run/memcached/
sudo chown nobody:nogroup /var/run/memcached
sudo chmod 0777 /var/run/memcached

memcached -d -m 1024 -u memcache -c 1024 -P /var/run/memcached/memcached.pid -s /var/run/memcached/memcached.sock -a 0755

pipx install poetry
poetry install
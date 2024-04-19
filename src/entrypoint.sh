#! /usr/bin/bash
memcached -d -m 1024 -u memcache -c 1024 -P /var/run/memcached/memcached.pid -s /var/run/memcached/memcached.sock -a 0755
python3 main.py
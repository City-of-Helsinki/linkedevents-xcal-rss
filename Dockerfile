# Use RHEL UBI image with Python 3.12
FROM registry.access.redhat.com/ubi8/python-39 as app

# Switch to root user to ensure permission for system changes
USER root

WORKDIR /opt/app

# Create app user and group
RUN groupadd -r app && \
    useradd -r -g app app

# Copy the requirements file
COPY requirements.txt .

# Install memcached and dependencies using yum
RUN yum -y update && \
    yum -y install memcached && \
    yum clean all

# Create and set permissions for memcached directory
RUN mkdir /var/run/memcached/ && \
    chown nobody:0 /var/run/memcached && \
    chmod 0777 /var/run/memcached

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code
COPY ./src /opt/app

# Set permissions for the entrypoint script
RUN chmod 0755 entrypoint.sh && \
    chown -R app:app /opt/app

# Switch to the app user for runtime
USER USER nobody:0

# Command to run the application
CMD ["/bin/sh", "-c", "/opt/app/entrypoint.sh"]

# Expose the application port
EXPOSE 8000/TCP

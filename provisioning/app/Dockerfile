FROM ubuntu:15.10

MAINTAINER Kisio Digital

# Update source repositories and install packages using aptitude

RUN apt-get update -y

RUN apt-get install -y wget python python-dev python-pip \
libpq-dev git postgresql-client protobuf-compiler

RUN pip install virtualenv

WORKDIR /tmp

RUN mkdir -p /var/www/chaos

ADD default_settings.py /default_settings.py

ADD requirements-dev.txt /requirements-dev.txt

ADD run-server.sh /usr/local/bin/run-server.sh

ADD Procfile.txt /Procfile.txt

ADD testing_settings.py /testing_settings.py

RUN chmod 0700 /usr/local/bin/run-server.sh

# Fix "Your terminal is not configured to receive UTF-8 encoded text" warning
ENV PYTHONIOENCODING utf-8

ENV CHAOS_CONFIG_FILE "/default_settings.py"

WORKDIR /var/www/chaos

VOLUME /var/www/chaos

EXPOSE 5000

CMD ["/usr/local/bin/run-server.sh"]

FROM arm64v8/python:3.11-slim
WORKDIR /var/jmspider
COPY ./requirement.txt /var/jmspider/requirement.txt
RUN pip install -r /var/jmspider/requirement.txt
COPY .  /var/jmspider
CMD ["/bin/sh", "/var/jmspider/run.sh"]
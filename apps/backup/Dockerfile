FROM postgres:17-alpine
COPY backup.sh /usr/local/bin/meloli-backup
RUN chmod +x /usr/local/bin/meloli-backup
ENTRYPOINT ["/usr/local/bin/meloli-backup"]

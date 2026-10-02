FROM postgres:17-alpine
COPY backup.sh /usr/local/bin/meloli-backup
COPY restore-drill.sh /usr/local/bin/meloli-restore-drill
RUN chmod +x /usr/local/bin/meloli-backup /usr/local/bin/meloli-restore-drill
ENTRYPOINT ["/usr/local/bin/meloli-backup"]

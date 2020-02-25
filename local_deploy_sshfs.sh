#!/bin/bash
function _log {
D=$(date  +"%Y%m%dT%H:%M:%S")
  echo -e $D "$@"
}
function log_error {
  _log "\e[0;31mERROR\e[0m : $@"
  exit -1
}

function log_warn {
  ISSUE=$(($ISSUE + 1 ))
  _log "\e[0;33mWARN\e[0m  : $@"
}
function log_info {
  _log "\e[1;32mINFO\e[0m  : $@"
}

function remote_exec {
  ssh -t $REMOTE_HOST "sh -lc \"set -e;$@\""
}

####### CONFIGURATION   #######
export MOUNT_POINT=/home/steki/addons
export REMOTE_HOST=hassio
#### END CONFIGURATION   ######


L=$(LANG=C df -h ${MOUNT_POINT}|grep -c hassio)

if [ $L -eq 1 ]; then
  #replace...
  log_info "already mounted"
else
  log_info "mounting sshfs"
  sshfs ${REMOTE_HOST}:/addons ${MOUNT_POINT} || ( log_error "failed sshfs mount" )
fi

rm -rf ${MOUNT_POINT}/borg-backup ||:
mkdir -p ${MOUNT_POINT}/borg-backup
cp -a *  ${MOUNT_POINT}/borg-backup/
log_info "deployed source"

CMD="ha addons reload"
remote_exec "$CMD"

CMD="ha addons rebuild local_borg-backup"
remote_exec "$CMD"


CMD="ha addons restart local_borg-backup"
remote_exec "$CMD"

sleep 2
CMD="ha addons logs local_borg-backup"
remote_exec  "$CMD"

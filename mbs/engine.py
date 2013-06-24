__author__ = 'abdul'


import traceback
import os

import time
import mbs_config
import mbs_logging

import urllib

import json

from flask import Flask
from flask.globals import request

from threading import Thread


from errors import MBSError, BackupEngineError

from utils import (ensure_dir, resolve_path, get_local_host_name,
                   document_pretty_string)

from mbs import get_mbs

from date_utils import  timedelta_total_seconds, date_now, date_minus_seconds


from task import (STATE_SCHEDULED, STATE_IN_PROGRESS, STATE_FAILED,
                  STATE_SUCCEEDED, STATE_CANCELED, EVENT_TYPE_ERROR,
                  EVENT_STATE_CHANGE, state_change_log_entry)

from backup import Backup

###############################################################################
# CONSTANTS
###############################################################################

DEFAULT_BACKUP_TEMP_DIR_ROOT = "~/backup_temp"

EVENT_START_EXTRACT = "START_EXTRACT"
EVENT_END_EXTRACT = "END_EXTRACT"
EVENT_START_ARCHIVE = "START_ARCHIVE"
EVENT_END_ARCHIVE = "END_ARCHIVE"
EVENT_START_UPLOAD = "START_UPLOAD"
EVENT_END_UPLOAD = "END_UPLOAD"

STATUS_RUNNING = "running"
STATUS_STOPPING = "stopping"
STATUS_STOPPED = "stopped"

# Failed one-off max due time (2 hours)
MAX_FAIL_DUE_TIME = 2 * 60 * 60

###############################################################################
# LOGGER
###############################################################################
logger = mbs_logging.logger

###############################################################################
########################                       ################################
######################## Backup Engine/Workers ################################
########################                       ################################
###############################################################################

###############################################################################
# BackupEngine
###############################################################################
class BackupEngine(Thread):

    ###########################################################################
    def __init__(self, id=None, max_workers=10,
                       temp_dir=None,
                       command_port=8888):
        Thread.__init__(self)
        self._id = id
        self._engine_guid = None
        self._max_workers = int(max_workers)
        self._temp_dir = resolve_path(temp_dir or DEFAULT_BACKUP_TEMP_DIR_ROOT)
        self._command_port = command_port
        self._command_server = EngineCommandServer(self)
        self._tags = None
        self._stopped = False

        # create the backup processor
        bc = get_mbs().backup_collection
        self._backup_processor = TaskQueueProcessor("Backups", bc, self,
                                                    self._max_workers)

        # create the restore processor
        rc = get_mbs().restore_collection
        self._restore_processor = TaskQueueProcessor("Restores", rc, self,
                                                     self._max_workers)


    ###########################################################################
    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, val):
        if val:
            self._id = val.encode('ascii', 'ignore')

    ###########################################################################
    @property
    def engine_guid(self):
        if not self._engine_guid:
            self._engine_guid = get_local_host_name() + "-" + self.id
        return self._engine_guid

    ###########################################################################
    @property
    def backup_collection(self):
        return get_mbs().backup_collection

    ###########################################################################
    @property
    def max_workers(self):
        return self._max_workers

    @max_workers.setter
    def max_workers(self, max_workers):
        self._max_workers = max_workers

    ###########################################################################
    @property
    def temp_dir(self):
        return self._temp_dir

    @temp_dir.setter
    def temp_dir(self, temp_dir):
        self._temp_dir = resolve_path(temp_dir)

    ###########################################################################
    @property
    def tags(self):
        return self._tags

    @tags.setter
    def tags(self, tags):
        tags = tags or {}
        self._tags = self._resolve_tags(tags)

    ###########################################################################
    @property
    def command_port(self):
        return self._command_port

    @command_port.setter
    def command_port(self, command_port):
        self._command_port = command_port

    ###########################################################################
    def run(self):
        self.info("Starting up... ")
        self.info("PID is %s" % os.getpid())
        self.info("TEMP DIR is '%s'" % self.temp_dir)
        if self.tags:
            self.info("Tags are: %s" % document_pretty_string(self.tags))
        else:
            self.info("No tags configured")

        ensure_dir(self._temp_dir)
        self._update_pid_file()
        # Start the command server
        self._start_command_server()

        # start the backup processor
        self._backup_processor.start()

        # start the restore processor
        self._restore_processor.start()

        # start the backup processor
        self._backup_processor.join()

        # start the restore processor
        self._restore_processor.join()

        self.info("Engine completed")
        self._pre_shutdown()

    ###########################################################################
    def _notify_error(self, exception):
        subject = "BackupEngine Error"
        message = ("BackupEngine '%s' Error!. Cause: %s. "
                   "\n\nStack Trace:\n%s" %
                   (self.engine_guid, exception, traceback.format_exc()))
        get_mbs().send_error_notification(subject, message, exception)


    ###########################################################################
    def _get_tag_bindings(self):
        """
            Returns a dict of binding name/value that will be used for
            resolving tags. Binding names starts with a '$'.
            e.g. "$HOST":"FOO"
        """
        return {
            "$HOST": get_local_host_name()
        }

    ###########################################################################
    def _resolve_tags(self, tags):
        resolved_tags = {}
        for name,value in tags.items():
            resolved_tags[name] = self._resolve_tag_value(value)

        return resolved_tags

    ###########################################################################
    def _resolve_tag_value(self, value):
        # if value is not a string then return it as is
        if not isinstance(value, (str, unicode)):
            return value
        for binding_name, binding_value in self._get_tag_bindings().items():
            value = value.replace(binding_name, binding_value)

        return value

    ###########################################################################
    def _kill_engine_process(self):
        self.info("Attempting to kill engine process")
        pid = self._read_process_pid()
        if pid:
            self.info("Killing engine process '%s' using signal 9" % pid)
            os.kill(int(pid), 9)
        else:
            raise BackupEngineError("Unable to determine engine process id")

    ###########################################################################
    def _update_pid_file(self):
        pid_file = open(self._get_pid_file_path(), 'w')
        pid_file.write(str(os.getpid()))
        pid_file.close()

    ###########################################################################
    def _read_process_pid(self):
        pid_file = open(self._get_pid_file_path(), 'r')
        pid = pid_file.read()
        if pid:
            return int(pid)

    ###########################################################################
    def _get_pid_file_path(self):
        pid_file_name = "engine_%s_pid.txt" % self.id
        return resolve_path(os.path.join(mbs_config.MBS_CONF_DIR, 
                                         pid_file_name))

    ###########################################################################
    # Engine stopping
    ###########################################################################
    def stop(self, force=False):
        """
            Sends a stop request to the engine using the command port
            This should be used by other processes (copies of the engine
            instance) but not the actual running engine process
        """

        if force:
            self._kill_engine_process()
            return

        url = "http://0.0.0.0:%s/stop" % self.command_port
        try:
            response = urllib.urlopen(url)
            if response.getcode() == 200:
                print response.read().strip()
            else:
                msg =  ("Error while trying to stop engine '%s' URL %s "
                        "(Response"" code %)" %
                        (self.engine_guid, url, response.getcode()))
                raise BackupEngineError(msg)
        except IOError, e:
            logger.error("Engine is not running")

    ###########################################################################
    def get_status(self):
        """
            Sends a status request to the engine using the command port
            This should be used by other processes (copies of the engine
            instance) but not the actual running engine process
        """
        url = "http://0.0.0.0:%s/status" % self.command_port
        try:
            response = urllib.urlopen(url)
            if response.getcode() == 200:
                return json.loads(response.read().strip())
            else:
                msg =  ("Error while trying to get status engine '%s' URL %s "
                        "(Response code %)" % (self.engine_guid, url,
                                               response.getcode()))
                raise BackupEngineError(msg)

        except IOError, ioe:
            return {
                    "status":STATUS_STOPPED
                }

    ###########################################################################
    @property
    def worker_count(self):
        return (self._backup_processor._worker_count +
                self._restore_processor._worker_count)
    ###########################################################################
    def _do_stop(self):
        """
            Stops the engine gracefully by waiting for all workers to finish
            and not starting any new workers.
            Returns true if it will stop immediately (i.e. no workers running)
        """
        self.info("Stopping engine gracefully. Waiting for %s workers"
                  " to finish" % self.worker_count)

        self._backup_processor._stopped = True
        self._restore_processor._stopped = True
        return self.worker_count == 0

    ###########################################################################
    def _do_get_status(self):
        """
            Gets the status of the engine
        """
        if self._backup_processor._stopped:
            status = STATUS_STOPPING
        else:
            status = STATUS_RUNNING

        return {
            "status": status,
            "workers": {
                "backups": self._backup_processor._worker_count,
                "restores": self._restore_processor._worker_count
            }
        }

    ###########################################################################
    def _pre_shutdown(self):
        self._stop_command_server()

    ###########################################################################
    # Command Server
    ###########################################################################

    def _start_command_server(self):
        self.info("Starting command server at port %s" % self._command_port)

        self._command_server.start()
        self.info("Command Server started successfully!")

    ###########################################################################
    def _stop_command_server(self):
        self._command_server.stop()

    ###########################################################################
    # Logging methods
    ###########################################################################
    def info(self, msg):
        logger.info("<BackupEngine-%s>: %s" % (self.id, msg))

    ###########################################################################
    def warning(self, msg):
        logger.warning("<BackupEngine-%s>: %s" % (self.id, msg))

    ###########################################################################
    def error(self, msg):
        logger.error("<BackupEngine-%s>: %s" % (self.id, msg))


###############################################################################
# TaskWorker
###############################################################################

class TaskQueueProcessor(Thread):
    ###########################################################################
    def __init__(self, name, task_collection, engine, max_workers=10):
        Thread.__init__(self)

        self._name = name
        self._task_collection = task_collection
        self._engine = engine
        self._sleep_time = 10
        self._stopped = False
        self._worker_count = 0
        self._max_workers = int(max_workers)
        self._tick_count = 0

    ###########################################################################
    def run(self):
        self._recover()

        while not self._stopped:
            try:
                self._tick()
                time.sleep(self._sleep_time)
            except Exception, e:
                self.error("Caught an error: '%s'.\nStack Trace:\n%s" %
                           (e, traceback.format_exc()))
                self._engine._notify_error(e)

        self.info("Exited main loop")

    ###########################################################################
    def _tick(self):
        # increase tick_counter
        self._tick_count += 1

        # try to start the next task if there are available workers
        if self._has_available_workers():
            self._start_next_task()

        # Cancel a failed task every 5 ticks and there are available
        # workers
        if self._tick_count % 5 == 0 and self._has_available_workers():
            self._clean_next_past_due_failed_task()

    ###########################################################################
    def _start_next_task(self):
        task = self.read_next_task()
        if task:
            self._start_task(task)

    ###########################################################################
    def _clean_next_past_due_failed_task(self):

        # read next failed past due task
        task = self._read_next_failed_past_due_task()
        if task:
            # clean it
            worker_id = self.next_worker_id()
            self.info("Starting cleaner worker for task '%s'" % task.id)
            TaskCleanWorker(worker_id, task, self).start()

    ###########################################################################
    def _start_task(self, task):
        self.info("Received  task %s" % task)
        worker_id = self.next_worker_id()
        self.info("Starting task %s, TaskWorker %s" %
                  (task._id, worker_id))
        TaskWorker(worker_id, task, self).start()

    ###########################################################################
    def _has_available_workers(self):
        return self._worker_count < self._max_workers

    ###########################################################################
    def next_worker_id(self):
        self._worker_count+= 1
        return self._worker_count

    ###########################################################################
    def worker_fail(self, worker, exception, trace=None):
        if isinstance(exception, MBSError):
            log_msg = exception.message
        else:
            log_msg = "Unexpected error. Please contact admin"

        details = "%s. Stack Trace: %s" % (exception, trace)
        self._task_collection.update_task(worker.task, event_type=EVENT_TYPE_ERROR,
            message=log_msg, details=details)

        self.worker_finished(worker, STATE_FAILED)

        nh = get_mbs().notification_handler
        # send a notification only if the task is not reschedulable
        if not worker.task.reschedulable and nh:
            nh.notify_on_task_failure(worker.task, exception, trace)

    ###########################################################################
    def worker_success(self, worker):
        self._task_collection.update_task(worker.task,
                                    message="Task completed successfully!")

        self.worker_finished(worker, STATE_SUCCEEDED)

    ###########################################################################
    def cleaner_finished(self, worker):
        self.worker_finished(worker, STATE_CANCELED)

    ###########################################################################
    def worker_finished(self, worker, state, message=None):

        # set end date
        worker.task.end_date = date_now()
        # decrease worker count and update state
        self._worker_count -= 1
        worker.task.state = state
        self._task_collection.update_task(worker.task,
                              properties=["state", "endDate"],
                              event_name=EVENT_STATE_CHANGE, message=message)

    ###########################################################################
    def _recover(self):
        """
        Does necessary recovery work on crashes. Fails all tasks that crashed
        while in progress and makes them reschedulable. Backup System will
        decide to cancel them or reschedule them.
        """
        self.info("Running recovery..")

        q = {
            "state": STATE_IN_PROGRESS,
            "engineGuid": self._engine.engine_guid
        }

        total_crashed = 0
        msg = ("Engine crashed while task was in progress. Failing...")
        for task in self._task_collection.find(q):
            # fail task
            self.info("Recovery: Failing task %s" % task._id)
            task.reschedulable = True
            task.state = STATE_FAILED
            task.end_date = date_now()
            # update
            self._task_collection.update_task(task,
                                              properties=["state",
                                                          "reschedulable",
                                                          "endDate"],
                                              event_type=EVENT_STATE_CHANGE,
                                              message=msg)

            total_crashed += 1



        self.info("Recovery complete! Total Crashed task: %s." %
                  total_crashed)

    ###########################################################################
    def read_next_task(self):

        log_entry = state_change_log_entry(STATE_IN_PROGRESS)
        q = self._get_scheduled_tasks_query()
        u = {"$set" : { "state" : STATE_IN_PROGRESS,
                        "engineGuid": self._engine.engine_guid},
             "$push": {"logs":log_entry.to_document()}}

        # sort by priority except every third tick, we sort by created date to
        # avoid starvation
        if self._tick_count % 5 == 0:
            s = [("createdDate", 1)]
        else:
            s = [("priority", 1)]

        c = self._task_collection

        task = c.find_and_modify(query=q, sort=s, update=u, new=True)

        return task

    ###########################################################################
    def _read_next_failed_past_due_task(self):
        min_fail_end_date = date_minus_seconds(date_now(), MAX_FAIL_DUE_TIME)
        q = { "state": STATE_FAILED,
              "engineGuid": self._engine.engine_guid,
              "$or": [
                      {
                      "plan.nextOccurrence": {"$lte": date_now()}
                  },

                      {
                      "plan": {"$exists": False},
                      "reschedulable": False,
                      "endDate": {"$lte": min_fail_end_date}
                  }


              ]
        }

        msg = "Task failed and is past due. Cancelling..."
        log_entry = state_change_log_entry(STATE_CANCELED, message=msg)
        u = {"$set" : { "state" : STATE_CANCELED},
             "$push": {
                 "logs": log_entry.to_document()
             }
        }

        return self._task_collection.find_and_modify(query=q, update=u,
                                                     new=True)

    ###########################################################################
    def _get_scheduled_tasks_query(self):
        q = {"state" : STATE_SCHEDULED}

        # add tags if specified
        if self._engine.tags:
            tag_filters = []
            for name,value in self._engine.tags.items():
                tag_prop_path = "tags.%s" % name
                tag_filters.append({tag_prop_path: value})

            q["$or"] = tag_filters
        else:
            q["$or"]= [
                    {"tags" : {"$exists": False}},
                    {"tags" : {}},
                    {"tags" : None}
            ]

        return q

    ###########################################################################
    # Logging methods
    ###########################################################################
    def info(self, msg):
        self._engine.info("%s Task Processor: %s" % (self._name, msg))

    ###########################################################################
    def warning(self, msg):
        self._engine.info("%s Task Processor: %s" % (self._name, msg))

    ###########################################################################
    def error(self, msg):
        self._engine.info("%s Task Processor: %s" % (self._name, msg))

###############################################################################
# TaskWorker
###############################################################################

class TaskWorker(Thread):

    ###########################################################################
    def __init__(self, id, task, processor):
        Thread.__init__(self)
        self._id = id
        self._task = task
        self._processor = processor

    ###########################################################################
    @property
    def task(self):
        return self._task

    ###########################################################################
    @property
    def processor(self):
        return self._processor

    ###########################################################################
    def run(self):
        task = self.task

        try:
            # increase # of tries
            task.try_count += 1

            self.info("Running task %s (try # %s)" %
                      (task._id, task.try_count))
            # set start date
            task.start_date = date_now()

            # set queue_latency_in_minutes if its not already set
            if not task.queue_latency_in_minutes:
                latency = self._calculate_queue_latency(task)
                task.queue_latency_in_minutes = latency

            # clear end date
            task.end_date = None

            # set the workspace
            workspace_dir = self._get_task_workspace_dir(task)
            task.workspace = workspace_dir

            # ensure backup workspace
            ensure_dir(task.workspace)

            # UPDATE!
            self._processor._task_collection.update_task(task,
                                         properties=["tryCount", "startDate",
                                                     "endDate", "workspace",
                                                     "queueLatencyInMinutes"])

            # run the task
            task.execute()

            # cleanup temp workspace
            task.cleanup()

            # success!
            self._processor.worker_success(self)

            self.info("Task '%s' completed successfully" % task.id)

        except Exception, e:
            # fail
            trace = traceback.format_exc()
            self.error("Task failed. Cause %s. \nTrace: %s" % (e, trace))
            self._processor.worker_fail(self, exception=e, trace=trace)


    ###########################################################################
    def _get_task_workspace_dir(self, task):
        return os.path.join(self._processor._engine.temp_dir, str(task._id))



    ###########################################################################
    def _calculate_queue_latency(self, task):
        if isinstance(task, Backup):
            occurrence_date = task.plan_occurrence or task.created_date
        else:
            occurrence_date = task.created_date

        latency_secs = timedelta_total_seconds(task.start_date -
                                               occurrence_date)

        return round(latency_secs/60, 2)

    ###########################################################################
    def info(self, msg):
        self._processor.info("Worker-%s: %s" % (self._id, msg))

    ###########################################################################
    def warning(self, msg):
        self._processor.warning("Worker-%s: %s" % (self._id, msg))

    ###########################################################################
    def error(self, msg):
        self._processor.error("Worker-%s: %s" % (self._id, msg))


###############################################################################
# TaskCleanWorker
###############################################################################

class TaskCleanWorker(TaskWorker):

    ###########################################################################
    def __init__(self, id, task, engine):
        TaskWorker.__init__(self, id, task, engine)

    ###########################################################################
    def run(self):
        try:
            self.task.cleanup()
        finally:
            self._processor.cleaner_finished(self)

###############################################################################
# EngineCommandServer
###############################################################################
class EngineCommandServer(Thread):

    ###########################################################################
    def __init__(self, engine):
        Thread.__init__(self)
        self._engine = engine
        self._flask_server = self._build_flask_server()

    ###########################################################################
    def _build_flask_server(self):
        flask_server = Flask(__name__)
        engine = self._engine
        ## build stop method
        @flask_server.route('/stop', methods=['GET'])
        def stop_engine():
            logger.info("Command Server: Received a stop command")
            try:
                if engine._do_stop():
                    return "Engine stopped successfully"
                else:
                    return ("Stop command received. Engine has %s workers "
                            "running and will stop when all workers finish" %
                            engine.worker_count)
            except Exception, e:
                return "Error while trying to stop engine: %s" % e

        ## build status method
        @flask_server.route('/status', methods=['GET'])
        def status():
            logger.info("Command Server: Received a status command")
            try:
                return document_pretty_string(engine._do_get_status())
            except Exception, e:
                return "Error while trying to get engine status: %s" % e

        ## build stop-command-server method
        @flask_server.route('/stop-command-server', methods=['GET'])
        def stop_command_server():
            logger.info("Stopping command server")
            try:
                shutdown = request.environ.get('werkzeug.server.shutdown')
                if shutdown is None:
                    raise RuntimeError('Not running with the Werkzeug Server')
                shutdown()
                return "success"
            except Exception, e:
                return "Error while trying to get engine status: %s" % e

        return flask_server

    ###########################################################################
    def run(self):
        logger.info("EngineCommandServer: Running flask server ")
        self._flask_server.run(host="0.0.0.0", port=self._engine._command_port,
                               threaded=True)

    ###########################################################################
    def stop(self):

        logger.info("EngineCommandServer: Stopping flask server ")
        port = self._engine._command_port
        url = "http://0.0.0.0:%s/stop-command-server" % port
        try:
            response = urllib.urlopen(url)
            if response.getcode() == 200:
                logger.info("EngineCommandServer: Flask server stopped "
                            "successfully")
                return response.read().strip()
            else:
                msg =  ("Error while trying to get status engine '%s' URL %s "
                        "(Response code %)" % (self.engine_guid, url,
                                               response.getcode()))
                raise BackupEngineError(msg)

        except Exception, e:
            raise BackupEngineError("Error while stopping flask server:"
                                        " %s" %e)

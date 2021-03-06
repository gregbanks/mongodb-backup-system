__author__ = 'abdul'

import traceback
import mbs_logging
from mbs import get_mbs
from errors import RetentionPolicyError
from backup_system import expire_backup
from base import MBSObject
from date_utils import date_now, date_minus_seconds

###############################################################################
# Contains Backup Retention Policies
###############################################################################

###############################################################################
# LOGGER
###############################################################################
logger = mbs_logging.logger

###############################################################################
# RetentionPolicy
###############################################################################
class RetentionPolicy(MBSObject):

    ###########################################################################
    def __init__(self):
        MBSObject.__init__(self)

    ###########################################################################

    def apply_policy(self, plan):
        """
            Applies the retention policy by deleting target references for
            expired succeeded backups (e.g. deleting backup files for expired
            backups)
        """
        policy_name = self.__class__.__name__
        for backup in self.get_expired_backups(plan):
            try:
                expire_backup(backup, date_now())

            except Exception, e:
                logger.error("%s: Error while archiving backup %s. "
                             "Trace: %s" %
                             (policy_name, backup.id, traceback.format_exc()))

                msg = ("Error while applying retention policy on backup %s. " %
                       backup.id)
                raise RetentionPolicyError(msg, cause=e,
                                           details=traceback.format_exc())

    ###########################################################################
    def get_expired_backups(self, plan):
        """
            Returns a list of backups that should expired and should be
            removed. Should be overridden by sub classes
        """
        return []

###############################################################################
# RetainLastNPolicy
###############################################################################
class RetainLastNPolicy(RetentionPolicy):
    """
        Retains the last 'n' backups
    """
    ###########################################################################
    def __init__(self):
        RetentionPolicy.__init__(self)
        self._retain_count = 0

    ###########################################################################
    @property
    def retain_count(self):
        return self._retain_count

    @retain_count.setter
    def retain_count(self, retain_count):
        self._retain_count = retain_count

    ###########################################################################
    def get_expired_backups(self, plan):
        q = {
            "plan._id": plan.id,
            "targetReference": {"$exists": True},
            # Filter out backups with targetReference.expiredDate is set
            "$or": [
                    {"targetReference.expiredDate": {"$exists": False}},
                    {"targetReference.expiredDate": None}
            ]
        }
        s = [("createdDate", -1)]

        backups = get_mbs().backup_collection.find(q, sort=s)

        if len(backups) <= self.retain_count:
            return []
        else:
            return backups[self.retain_count:]

    ###########################################################################
    def to_document(self, display_only=False):
        return {
            "_type": "RetainLastNPolicy",
            "retainCount": self.retain_count
        }


###############################################################################
# RetainTimePolicy
###############################################################################
class RetainMaxTimePolicy(RetentionPolicy):
    """
        Retains T time worth of data. i.e. Backup date is within now() - T
    """
    ###########################################################################
    def __init__(self):
        RetentionPolicy.__init__(self)
        self._max_time = 0

    ###########################################################################
    @property
    def max_time(self):
        return self._max_time

    @max_time.setter
    def max_time(self, max_time):
        self._max_time = max_time

    ###########################################################################
    def get_expired_backups(self, plan):

        earliest_date_to_keep = date_minus_seconds(date_now(), self.max_time)
        q = {
            "plan._id": plan.id,
            "targetReference": {"$exists": True},
            # Filter out backups with targetReference.expiredDate is set
            "$or": [
                    {"targetReference.expiredDate": {"$exists": False}},
                    {"targetReference.expiredDate": None}
            ],
            "startDate": {
                "$lt": earliest_date_to_keep
            }
        }

        backups = get_mbs().backup_collection.find(q)
        return backups

    ###########################################################################
    def to_document(self, display_only=False):
        return {
            "_type": "RetainMaxTimePolicy",
            "maxTime": self.max_time
        }
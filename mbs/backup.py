__author__ = 'abdul'

from task import *

###############################################################################
# Backup
###############################################################################
class Backup(MBSTask):
    def __init__(self):
        # init fields
        MBSTask.__init__(self)
        self._name = None
        self._description = None
        self._source = None
        self._source_stats = None
        self._target = None
        self._target_reference = None
        self._plan = None
        self._plan_occurrence = None
        self._backup_rate_in_mbps = None

    ###########################################################################
    def execute(self):
        """
            Override
        """
        return self.strategy.run_backup(self)

    ###########################################################################
    def cleanup(self):
        """
            Override
        """
        return self.strategy.cleanup_backup(self)

    ###########################################################################
    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = name

    ###########################################################################
    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, description):
        self._description = description

    ###########################################################################
    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, source):
        self._source = source

    ###########################################################################
    @property
    def source_stats(self):
        return self._source_stats

    @source_stats.setter
    def source_stats(self, source_stats):
        self._source_stats = source_stats

    ###########################################################################
    @property
    def target(self):
        return self._target


    @target.setter
    def target(self, target):
        self._target = target

    ###########################################################################
    @property
    def target_reference(self):
        return self._target_reference


    @target_reference.setter
    def target_reference(self, target_reference):
        self._target_reference = target_reference

    ###########################################################################
    @property
    def plan(self):
        return self._plan

    @plan.setter
    def plan(self, plan):
        self._plan = plan

    ###########################################################################
    @property
    def plan_occurrence(self):
        return self._plan_occurrence

    @plan_occurrence.setter
    def plan_occurrence(self, plan_occurrence):
        self._plan_occurrence = plan_occurrence


    ###########################################################################
    @property
    def backup_rate_in_mbps(self):
        return self._backup_rate_in_mbps

    @backup_rate_in_mbps.setter
    def backup_rate_in_mbps(self, backup_rate):
        self._backup_rate_in_mbps = backup_rate

    ###########################################################################
    def to_document(self, display_only=False):

        doc = MBSTask.to_document(self, display_only=display_only)
        doc.update({
            "_type": "Backup",
            "source": self.source.to_document(display_only=display_only),
            "target": self.target.to_document(display_only=display_only),
            "planOccurrence": self.plan_occurrence,
        })

        if self.name:
            doc["name"] = self.name

        if self.description:
            doc["description"] = self.description

        if self.plan:
            doc["plan"] = self.plan.to_document(display_only=display_only)

        if self.target_reference:
            doc["targetReference"] = self.target_reference.to_document(
                                                     display_only=display_only)

        if self.source_stats:
            doc["sourceStats"] = self.source_stats

        if self.backup_rate_in_mbps:
            doc["backupRateInMBPS"] = self.backup_rate_in_mbps

        return doc
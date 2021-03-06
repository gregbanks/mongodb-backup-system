__author__ = 'abdul'


from mbs import get_mbs
from audit import *
import mbs_logging
from date_utils import yesterday_date, datetime_to_string, date_plus_seconds

###############################################################################
# LOGGER
###############################################################################
logger = mbs_logging.logger

###############################################################################
##############################                 ################################
############################## Backup Auditors ################################
##############################                 ################################
###############################################################################

TYPE_PLAN_AUDIT = "PLAN_AUDIT"
TYPE_SINGLE_PLAN_AUDIT = "SINGLE_PLAN_AUDIT"

###############################################################################
# BackupAuditor
# Creates an audit report about backups taken as of a specific day.
#
class BackupAuditor(object):

    ###########################################################################
    def __init__(self):
        pass

    ###########################################################################
    def daily_audit_report(self, audit_date):
        pass

    ###########################################################################
    def yesterday_audit_reports_as_of(self):
        return self.daily_audit_report(yesterday_date())

###############################################################################
# PlanBackupAuditor
# Creates an audit report about backup plans taken yesterday.

class PlanAuditor(BackupAuditor):
    ###########################################################################
    def __init__(self):
        BackupAuditor.__init__(self)

    ###########################################################################
    # plan auditing
    ###########################################################################
    def daily_audit_report(self, audit_date):

        logger.info("PlanAuditor: Generating %s audit report for '%s'" %
                    (TYPE_PLAN_AUDIT,  datetime_to_string(audit_date)))

        audit_end_date = date_plus_seconds(audit_date, 3600 * 24)
        all_plans_report = AuditReport()
        all_plans_report.audit_date = audit_date
        all_plans_report.audit_type = TYPE_PLAN_AUDIT

        total_plans = 0
        failed_plan_reports = []
        all_warned_audits = []
        total_warnings = 0
        for plan in get_mbs().plan_collection.find():
            # skip recently added plans whose created date is after audit date
            # and their next occurrence is not in auditing range
            if (plan.created_date > audit_date and plan.next_occurrence and
                plan.next_occurrence > audit_end_date) :
                logger.info("PlanAuditor: Skipping auditing plan '%s' since"
                            " its created date '%s' is later than audit date "
                            "'%s'" % (plan.id,
                                      datetime_to_string(plan.created_date),
                                      datetime_to_string(audit_date)))
                continue

            plan_report = self._create_plan_audit_report(plan, audit_date)

            if plan_report.has_failures():
                failed_plan_reports.append(plan_report)
            if plan_report.has_warnings():
                # only append to warned audits if report doesn't have failures
                if not plan_report.has_failures():
                    all_warned_audits.extend(plan_report.warned_audits)

                total_warnings += 1

            total_plans += 1

        total_failures = len(failed_plan_reports)

        if failed_plan_reports:
            all_plans_report.failed_audits = failed_plan_reports
        if all_warned_audits:
            all_plans_report.warned_audits = all_warned_audits

        all_plans_report.total_audits = total_plans
        all_plans_report.total_failures = total_failures
        all_plans_report.total_success = total_plans - total_failures
        all_plans_report.total_warnings = total_warnings

        logger.info("PlanAuditor: Generated report:\n%s " % all_plans_report)

        return all_plans_report

    ###########################################################################
    def _create_plan_audit_report(self, plan, audit_date):

        plan_report = PlanAuditReport()
        plan_report.plan = plan
        plan_report.audit_date = audit_date
        plan_report.audit_type = TYPE_SINGLE_PLAN_AUDIT

        failed_audits = []
        warned_audits = []
        total_audits = 0
        total_warnings = 0
        for plan_occurrence in plan.natural_occurrences_as_of(audit_date):
            audit_entry = self._audit_plan_occurrence(plan, plan_occurrence)
            if audit_entry.failed():
                failed_audits.append(audit_entry)

            if audit_entry.warned():
                # only append to warned audits if audit entry succeeded
                if audit_entry.succeeded():
                    warned_audits.append(audit_entry)
                total_warnings += 1

            total_audits += 1

        total_failures = len(failed_audits)

        if failed_audits:
            plan_report.failed_audits = failed_audits

        if warned_audits:
            plan_report.warned_audits = warned_audits

        plan_report.total_failures = total_failures
        plan_report.total_audits = total_audits
        plan_report.total_success = total_audits - total_failures
        plan_report.warned_audits = warned_audits
        plan_report.total_warnings = total_warnings

        return plan_report

    ###########################################################################
    def _audit_plan_occurrence(self, plan, plan_occurrence):
        backup = self._lookup_backup_by_plan_occurrence(plan,
            plan_occurrence)

        audit_entry = PlanAuditEntry()

        if backup:
            audit_entry.backup_id = backup.id
            audit_entry.state = backup.state
            audit_entry.errors = backup.get_errors()
            audit_entry.warnings = backup.get_warnings()
        else:
            audit_entry.state = "NEVER SCHEDULED"


        audit_entry.plan_occurrence = plan_occurrence

        return audit_entry

    ###########################################################################
    def _lookup_backup_by_plan_occurrence(self, plan, plan_occurrence):

        q = {
            "plan._id": plan._id,
            "planOccurrence":plan_occurrence,
            }
        c = get_mbs().backup_collection

        return c.find_one(q)


###############################################################################
class GlobalAuditor():

    ###########################################################################
    def __init__(self, audit_collection, notification_handler=None):
        self._auditors = []
        self._audit_collection = audit_collection
        self._notification_handler = notification_handler

    ###########################################################################
    def register_auditor(self, auditor):
        self._auditors.append(auditor)

    ###########################################################################
    def generate_daily_audit_reports(self, date):
        reports = []
        for auditor in self._auditors:
            report = auditor.daily_audit_report(date)
            logger.info("GlobalAuditor: Saving audit report: \n%s" % report)
            self._audit_collection.save_document(report.to_document())
            reports.append(report)

        # send notification if specified
        if self._notification_handler:
            self._send_notification(date, reports)

    ###########################################################################
    def generate_yesterday_audit_reports(self):
        self.generate_daily_audit_reports(yesterday_date())

    ###########################################################################
    def _send_notification(self, date, reports):
        subject = "Backup Audit Reports for %s" % datetime_to_string(date)
        reports_str = map(str, reports)
        message = "\n\n\n".join(reports_str)
        self._notification_handler.send_notification(subject, message)

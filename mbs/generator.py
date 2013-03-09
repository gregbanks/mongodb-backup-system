__author__ = 'abdul'

import mbs_logging

###############################################################################
# LOGGER
###############################################################################
logger = mbs_logging.logger

###############################################################################
# PlanGenerator
# An abstraction of something that generate/removes backup plans. This is used
# By the plan manager
###############################################################################
class PlanGenerator(object):

    ###########################################################################
    def __init__(self):
        pass

    ###########################################################################
    @property
    def name(self):
        return ""
    ###########################################################################
    def get_plans_to_save(self):
        return []

    ###########################################################################
    def get_plans_to_remove(self):
        return []

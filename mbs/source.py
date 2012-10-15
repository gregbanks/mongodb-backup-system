__author__ = 'abdul'

from utils import document_pretty_string, is_cluster_mongo_uri, parse_mongo_uri
from errors import ConfigurationError

###############################################################################
# Backup Source Classes
###############################################################################
class BackupSource(object):

    ###########################################################################
    def __init__(self):
        pass

    ###########################################################################
    @property
    def source_uri(self):
        pass

    ###########################################################################
    @property
    def username(self):
        pass

    ###########################################################################
    @property
    def password(self):
        pass

    ###########################################################################
    def is_cluster_source(self):
        return False

    ###########################################################################
    def to_document(self):
        pass

    ###########################################################################
    def is_valid(self):
        errors = self.validate()
        if errors:
            return False
        else:
            return True

    ###########################################################################
    def validate(self):
        """
         Returns an array containing validation messages (if any). Empty if no
         validation errors
        """
        return []

    ###########################################################################
    def __str__(self):
        return document_pretty_string(self.to_document())

###############################################################################
# ServerSource
###############################################################################
class ServerSource(BackupSource):

    ###########################################################################
    def __init__(self):
        BackupSource.__init__(self)
        self._address = None
        self._admin_username = None
        self._admin_password = None

    ###########################################################################
    @property
    def address(self):
        return self._address

    @address.setter
    def address(self, address):
        self._address = address

    ###########################################################################
    @property
    def username(self):
        return self.admin_username

    ###########################################################################
    @property
    def password(self):
        return self.admin_password

    ###########################################################################
    @property
    def admin_username(self):
        return self._admin_username

    @admin_username.setter
    def admin_username(self, admin_username):
        self._admin_username = admin_username

    ###########################################################################
    @property
    def admin_password(self):
        return self._admin_password

    @admin_password.setter
    def admin_password(self, admin_password):
        self._admin_password = admin_password

    ###########################################################################
    @property
    def source_uri(self):
        return "mongodb://%s" % self.address

    ###########################################################################
    def to_document(self):
        return {
            "_type": "ServerSource",
            "address": self.address,
            "adminUsername": self.admin_username,
            "adminPassword": self.admin_password
        }

    ###########################################################################
    def validate(self):
        errors = []
        if not self.address:
            errors.append("Missing 'address' property")

        if not self.admin_username:
            errors.append("Missing 'adminUsername' property")

        if not self.password:
            errors.append("Missing 'password' property")

        return errors

###############################################################################
# Database Source
###############################################################################
class DatabaseSource(BackupSource):

    ###########################################################################
    def __init__(self):
        BackupSource.__init__(self)
        self._database_uri = None

    ###########################################################################
    @property
    def database_uri(self):
        return self._database_uri

    @database_uri.setter
    def  database_uri(self, database_uri):
        self._database_uri = database_uri

    ###########################################################################
    @property
    def source_uri(self):
        return self.database_uri

    ###########################################################################
    def to_document(self):
        return {
            "_type": "DatabaseSource",
            "databaseUri": self.database_uri
        }

    ###########################################################################
    def is_cluster_source(self):
        return is_cluster_mongo_uri(self.database_uri)


    ###########################################################################
    def validate(self):
        errors = []
        if not self.database_uri:
            errors.append("Missing 'databaseUri' property")

        try:
            parse_mongo_uri(self.database_uri)
        except Exception, e:
            errors.append("Invalid 'databaseUri'.%s" % e)

        return errors
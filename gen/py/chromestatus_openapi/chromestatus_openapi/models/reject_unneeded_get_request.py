from datetime import date, datetime  # noqa: F401

from typing import List, Dict  # noqa: F401

from chromestatus_openapi.models.base_model import Model
from chromestatus_openapi import util


class RejectUnneededGetRequest(Model):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.
    """

    def __init__(self, message=None):  # noqa: E501
        """RejectUnneededGetRequest - a model defined in OpenAPI

        :param message: The message of this RejectUnneededGetRequest.  # noqa: E501
        :type message: str
        """
        self.openapi_types = {
            'message': str
        }

        self.attribute_map = {
            'message': 'message'
        }

        self._message = message

    @classmethod
    def from_dict(cls, dikt) -> 'RejectUnneededGetRequest':
        """Returns the dict as a model

        :param dikt: A dict.
        :type: dict
        :return: The RejectUnneededGetRequest of this RejectUnneededGetRequest.  # noqa: E501
        :rtype: RejectUnneededGetRequest
        """
        return util.deserialize_model(dikt, cls)

    @property
    def message(self) -> str:
        """Gets the message of this RejectUnneededGetRequest.


        :return: The message of this RejectUnneededGetRequest.
        :rtype: str
        """
        return self._message

    @message.setter
    def message(self, message: str):
        """Sets the message of this RejectUnneededGetRequest.


        :param message: The message of this RejectUnneededGetRequest.
        :type message: str
        """

        self._message = message
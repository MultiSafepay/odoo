# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from datetime import date, datetime
from decimal import Decimal


class _Serializer:
    """Serialize SDK response objects into JSON-safe Cloud POS payloads.

    This class translates complex Python objects returned by the MultiSafepay SDK
    into primitive, JSON-serializable dictionaries. Extracting this serialization
    logic ensures the Single Responsibility Principle by decoupling the Odoo data
    layer from the underlying SDK object structures.
    """

    @classmethod
    def serialize_response_data(cls, response):
        """Extract and serialize response data from SDK response wrappers.

        :param response: SDK response object.
        :return: Serialized plain dictionary containing response attributes.
        :rtype: dict
        """
        if not response:
            return {}
        if hasattr(response, "get_data") and callable(response.get_data):
            return cls.serialize_model(response.get_data())
        if hasattr(response, "get_body_data") and callable(response.get_body_data):
            return cls.serialize_model(response.get_body_data())
        data = getattr(response, "data", None)
        if data is not None:
            return cls.serialize_model(data)
        return {}

    @classmethod
    def serialize_model(cls, sdk_model):
        """Serialize supported SDK models into plain JSON-safe data.

        :param sdk_model: SDK model object or raw dictionary.
        :return: Serialized plain dictionary of model fields.
        :rtype: dict
        """
        if sdk_model is None:
            return {}
        if hasattr(sdk_model, "model_dump"):
            return cls.json_safe_payload(sdk_model.model_dump(mode="python"))
        if hasattr(sdk_model, "dict") and callable(sdk_model.dict):
            try:
                return cls.json_safe_payload(sdk_model.dict())
            except TypeError:
                pass
        if isinstance(sdk_model, dict):
            return cls.json_safe_payload(dict(sdk_model))
        return {}

    @classmethod
    def json_safe_payload(cls, payload):
        """Recursively convert SDK payload values into JSON-safe primitives.

        :param payload: Element to serialize recursively.
        :return: JSON-safe primitive value.
        """
        if isinstance(payload, dict):
            return {
                str(key): cls.json_safe_payload(value) for key, value in payload.items()
            }
        if isinstance(payload, (list, tuple, set)):
            return [cls.json_safe_payload(value) for value in payload]
        if isinstance(payload, Decimal):
            if payload == payload.to_integral_value():
                return int(payload)
            return float(payload)
        if isinstance(payload, (date, datetime)):
            return payload.isoformat()
        if isinstance(payload, (str, int, float, bool)) or payload is None:
            return payload
        value = getattr(payload, "value", None)
        if value is not None:
            return cls.json_safe_payload(value)
        return str(payload)

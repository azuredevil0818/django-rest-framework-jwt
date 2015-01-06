import jwt

from calendar import timegm
from datetime import datetime, timedelta

from django.contrib.auth import authenticate
from rest_framework import serializers
from .compat import Serializer

from rest_framework_jwt import utils
from rest_framework_jwt.settings import api_settings


jwt_payload_handler = api_settings.JWT_PAYLOAD_HANDLER
jwt_encode_handler = api_settings.JWT_ENCODE_HANDLER
jwt_decode_handler = api_settings.JWT_DECODE_HANDLER
jwt_get_user_id_from_payload = api_settings.JWT_PAYLOAD_GET_USER_ID_HANDLER
jwt_response_payload_handler = api_settings.JWT_RESPONSE_PAYLOAD_HANDLER


class JSONWebTokenSerializer(Serializer):
    """
    Serializer class used to validate a username and password.

    'username' is identified by the custom UserModel.USERNAME_FIELD.

    Returns a JSON Web Token that can be used to authenticate later calls.
    """

    password = serializers.CharField(write_only=True)

    def __init__(self, *args, **kwargs):
        """Dynamically add the USERNAME_FIELD to self.fields."""
        super(JSONWebTokenSerializer, self).__init__(*args, **kwargs)
        self.fields[self.username_field] = serializers.CharField()

    @property
    def username_field(self):
        User = utils.get_user_model()

        try:
            return User.USERNAME_FIELD
        except AttributeError:
            return 'username'

    def validate(self, attrs):
        credentials = {self.username_field: attrs.get(self.username_field),
                       'password': attrs.get('password')}
        if all(credentials.values()):
            user = authenticate(**credentials)

            if user:
                if not user.is_active:
                    msg = 'User account is disabled.'
                    raise serializers.ValidationError(msg)

                token_payload = jwt_payload_handler(user)

                # Include original issued at time for a brand new token,
                # to allow token refresh
                if api_settings.JWT_ALLOW_REFRESH:
                    token_payload['orig_iat'] = timegm(
                        datetime.utcnow().utctimetuple()
                    )
                
                # Obtain the token and construct the payload.
                payload = {
                    'token': jwt_encode_handler(token_payload)
                }

                # Attach additional payload response data.
                data = jwt_response_payload_handler(user)
                if isinstance(data, dict):
                    payload.update(data)

                return payload
            else:
                msg = 'Unable to login with provided credentials.'
                raise serializers.ValidationError(msg)
        else:
            msg = 'Must include "{0}" and "password"'.format(
                self.username_field)
            raise serializers.ValidationError(msg)


class RefreshJSONWebTokenSerializer(Serializer):
    """
    Check an access token
    """
    token = serializers.CharField()

    def validate(self, attrs):
        User = utils.get_user_model()
        token = attrs['token']

        # Check payload valid (based off of JSONWebTokenAuthentication,
        # may want to refactor)
        try:
            token_payload = jwt_decode_handler(token)
        except jwt.ExpiredSignature:
            msg = 'Signature has expired.'
            raise serializers.ValidationError(msg)
        except jwt.DecodeError:
            msg = 'Error decoding signature.'
            raise serializers.ValidationError(msg)

        # Make sure user exists (may want to refactor this)
        try:
            user_id = jwt_get_user_id_from_payload(token_payload)

            if user_id is not None:
                user = User.objects.get(pk=user_id, is_active=True)
            else:
                msg = 'Invalid payload'
                raise serializers.ValidationError(msg)
        except User.DoesNotExist:
            msg = "User doesn't exist"
            raise serializers.ValidationError(msg)

        # Get and check 'orig_iat'
        orig_iat = token_payload.get('orig_iat')

        if orig_iat:
            # Verify expiration
            refresh_limit = api_settings.JWT_REFRESH_EXPIRATION_DELTA

            if isinstance(refresh_limit, timedelta):
                refresh_limit = (refresh_limit.days * 24 * 3600 +
                                 refresh_limit.seconds)

            expiration_timestamp = orig_iat + int(refresh_limit)
            now_timestamp = timegm(datetime.utcnow().utctimetuple())

            if now_timestamp > expiration_timestamp:
                msg = 'Refresh has expired'
                raise serializers.ValidationError(msg)
        else:
            msg = 'orig_iat field is required'
            raise serializers.ValidationError(msg)

        token_payload = jwt_payload_handler(user)
        token_payload['orig_iat'] = orig_iat

        # Obtain the token and construct the payload.
        payload = {
            'token': jwt_encode_handler(token_payload)
        }

        # Attach additional payload response data.
        data = jwt_response_payload_handler(user)
        if isinstance(data, dict):
            payload.update(data)

        return payload

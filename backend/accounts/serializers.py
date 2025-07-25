from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
import logging
from core.mask_email import mask_email
from .models import Notification

User = get_user_model()
logger = logging.getLogger(__name__)

class PasswordResetConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, required=True, min_length=8)

    def validate_password(self, value):
        """Ensure password meets security standards."""
        try:
            validate_password(value)
        except serializers.ValidationError as e:
            logger.warning(f"Password reset failed due to weak password: {str(e)}")
            raise serializers.ValidationError(str(e))
        return value

    def validate(self, data):
        """Ensure both password fields match."""
        if data['password'] != data['confirm_password']:
            logger.warning("Passwords do not match during password reset.")
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data

    

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims (Add any additional user details to the token if you want)
        token['first_name'] = user.first_name
        token['last_name'] = user.last_name
        token['department'] = str(user.department) if user.department else 'None'
        token['email'] = user.email
        token['user_id'] = user.id
        
        logger.info(f"Token generated for email: {mask_email(user.email)}")
        return token
    
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Get the user instance
        user = self.user
        
        # Generate refresh and access tokens
        refresh = self.get_token(user)
        access = refresh.access_token
        
        # Add custom claims to response
        data['refresh'] = str(refresh)
        data['access'] = str(access)
        data['email'] = user.email
        data['full_name'] = user.get_full_name
        data['role'] = user.role
        data['phone_number'] = user.phone_number
        data['department'] = str(user.department) if user.department else None
        data['position'] = str(user.position) if user.position else None
        
        return data


class LoginSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(max_length=155, min_length=6)
    password = serializers.CharField(max_length=68, write_only=True)

    class Meta:
        model = User
        fields = ['email', 'password']

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        request = self.context.get('request')
        
        logger.info(f"Login attempted by {email}")
        
        user = authenticate(request, email=email, password=password)
        if not user:
            logger.warning(f"Failed login attempt for email: {mask_email(email)} - Invalid credentials")
            raise AuthenticationFailed("Invalid credentials. Please try again.")
        
        if not user.is_active:
            logger.warning(f"Failed login attempt for email: {mask_email(email)} - Account is inactive")
            raise AuthenticationFailed("Account is inactive. Please contact support.")

        # Generate tokens using custom claims
        tokens_serializer = CustomTokenObtainPairSerializer(data={"email": email, "password": password})
        tokens_serializer.is_valid(raise_exception=True)
        tokens = tokens_serializer.validated_data
        
        # Add user to validated data
        attrs['user'] = user
        
        # Return tokens and user data
        return {
            **tokens,
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': user.get_full_name,
                'role': user.role,
                'department': user.department,
                'position': user.position,
                'phone_number': user.phone_number,
                'is_superuser': user.is_superuser,
            }
        }

class LogoutUserSerializer(serializers.Serializer):
    """
    Serializer for logging out a user
    """
    refresh = serializers.CharField()

    default_error_messages = {
        'bad_token': ('Token is invalid or expired.')
    }

    def validate(self, attrs):
        self.token = attrs['refresh'].strip('"')
        return attrs

    def save(self, **kwargs):
        try:
            token = RefreshToken(self.token)
            token.blacklist()
        except TokenError:
            self.fail('bad_token')


class UserMeSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'role', 'first_name', 'last_name', 'phone_number', 'full_name', 'position', 'is_superuser']

    def get_full_name(self, obj):
        return obj.get_full_name

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone_number',
            'role', 'department', 'position',
            'is_active', 'is_staff', 'is_superuser', 'last_login', 'date_joined'
        ]
        read_only_fields = ['id', 'last_login', 'date_joined']
    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user

class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ResendVerificationEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message', 
            'is_read', 'created_at', 'read_at', 
            'related_object_id', 'related_object_type'
        ]
        read_only_fields = ['created_at', 'read_at']
    
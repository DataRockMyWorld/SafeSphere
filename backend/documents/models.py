from django.db import models
from accounts.models import User
import uuid
import re
from django.utils import timezone

### ISO Clause Reference Model

class ISOClause(models.Model):
    class_code = models.CharField(max_length=10, unique=True)
    title = models.TextField()
    description = models.TextField()
    
    def __str__(self):
        return f"{self.class_code} - {self.title}"
    
    
### Document Tag 
class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    
    def __str__(self):
        return self.name
    
    
    
 
### Document Model
class Document(models.Model):
    DOC_TYPES = [
        ("POLICY", "Policy"),
        ("SYSTEM DOCUMENT", "System Document"),
        ("PROCEDURE", "Procedure"),
        ("FORM", "Form"),
        ("SSOW", "SSOW"),
        ("OTHER", "Other"),
    ]
    
    STAGE_CHOICES = [
        ("DRAFT", "Draft"),
        ("HSSE_REVIEW", "HSSE Manager Review"),
        ("OPS_REVIEW", "OPS Manager Review"),
        ("MD_APPROVAL", "MD Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected")
    ]
    
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    content = models.TextField(blank=True, help_text="Document content for inline editing")
    document_type = models.CharField(max_length=20, choices=DOC_TYPES)
    category = models.CharField(max_length=100, blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    file = models.FileField(upload_to='documents/')
    iso_clauses = models.ManyToManyField(ISOClause, blank=True)
    version = models.CharField(max_length=10, default="1.0")
    revision_number = models.DecimalField(max_digits=4, decimal_places=1, default=1.0)
    status = models.CharField(max_length=20, choices=STAGE_CHOICES, default='DRAFT')
    expiry_date = models.DateField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='docs_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='docs_verified')
    verified_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='docs_approved')
    approved_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    template = models.ForeignKey('DocumentTemplate', on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    metadata = models.JSONField(default=dict, help_text="Document-specific metadata and content")

    def __str__(self):
        return self.title

    def can_transition_to(self, new_status):
        """Validate if the document can transition to the new status."""
        valid_transitions = {
            'DRAFT': ['HSSE_REVIEW', 'REJECTED'],
            'HSSE_REVIEW': ['OPS_REVIEW', 'REJECTED'],
            'OPS_REVIEW': ['MD_APPROVAL', 'REJECTED'],
            'MD_APPROVAL': ['APPROVED', 'REJECTED'],
            'REJECTED': ['DRAFT'],
            'APPROVED': ['DRAFT']  # For new versions
        }
        return new_status in valid_transitions.get(self.status, [])

    def transition_to(self, new_status, user, comment=''):
        """Safely transition the document to a new status."""
        if not self.can_transition_to(new_status):
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        
        self.status = new_status
        self.save()
        
        # Create workflow entry
        action_map = {
            'HSSE_REVIEW': 'SUBMIT',
            'OPS_REVIEW': 'VERIFY',
            'MD_APPROVAL': 'APPROVE',
            'APPROVED': 'APPROVE',
            'REJECTED': 'REJECT'
        }
        
        ApprovalWorkflow.objects.create(
            document=self,
            position=user.position,
            action=action_map.get(new_status, 'SUBMIT'),
            performed_by=user,
            comment=comment
        )

    def is_editable(self, user):
        """Check if the document can be edited by the given user."""
        if self.status == 'DRAFT':
            return user == self.created_by or user.position == 'HSSE MANAGER'
        return False

    def is_hsse_reviewable(self, user):
        """Check if the document can be reviewed by HSSE Manager."""
        return (
            self.status == 'HSSE_REVIEW' and
            user.position == 'HSSE MANAGER'
        )

    def is_ops_reviewable(self, user):
        """Check if the document can be reviewed by OPS Manager."""
        return (
            self.status == 'OPS_REVIEW' and
            user.position == 'OPS MANAGER'
        )

    def is_md_approvable(self, user):
        """Check if the document can be approved by MD."""
        return (
            self.status == 'MD_APPROVAL' and
            user.position == 'MD'
        )

    def is_rejectable(self, user):
        """Check if the document can be rejected by the given user."""
        return (
            self.status in ['HSSE_REVIEW', 'OPS_REVIEW', 'MD_APPROVAL'] and
            user.position in ['HSSE MANAGER', 'OPS MANAGER', 'MD']
        )

    def get_workflow_history(self):
        """Get the complete workflow history of the document."""
        return self.approvalworkflow_set.all().order_by('timestamp')

    def get_current_version(self):
        """Get the current version string."""
        return f"{self.version}.{self.revision_number}"

    def create_new_version(self):
        """Create a new version of the document."""
        if self.status != 'APPROVED':
            raise ValueError("Only approved documents can have new versions")
        
        # Increment version number
        major, minor = map(int, self.version.split('.'))
        self.version = f"{major + 1}.0"
        self.revision_number = 1.0
        self.status = 'DRAFT'
        self.save()

    def create_new_version_for_change_request(self):
        """Create a new version of the document for change request approval."""
        # Increment version number
        major, minor = map(int, self.version.split('.'))
        self.version = f"{major + 1}.0"
        self.revision_number = 1.0
        self.status = 'DRAFT'
        self.created_by = self.change_requests.filter(status='APPROVED').first().responded_by
        self.save()

    def validate_against_template(self):
        """Validate this document against its template."""
        if self.template:
            return self.template.validate_document(self)
        return []

# =============================
# Approval Workflow Log
# =============================
class ApprovalWorkflow(models.Model):
    ACTIONS = [('SUBMIT', 'Submitted'), ('VERIFY', 'Verified'), ('APPROVE', 'Approved'), ('REJECT', 'Rejected')]

    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    position = models.CharField(max_length=20, choices=User.POSITION_CHOICES)
    action = models.CharField(max_length=10, choices=ACTIONS)
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True)

    def __str__(self):
        return f"{self.action} by {self.performed_by} ({self.position})"


# =============================
# Change Request
# =============================
class ChangeRequest(models.Model):
    STATUS = [('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='change_requests')
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='change_requests_made')
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS, default='PENDING')
    admin_response = models.TextField(blank=True)
    responded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='change_requests_responded')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Change Request for {self.document.title} by {self.requested_by}"

    def can_be_approved_by(self, user):
        """Only HSSE Manager can approve change requests."""
        return user.position == 'HSSE MANAGER'

    def can_be_rejected_by(self, user):
        """Only HSSE Manager can reject change requests."""
        return user.position == 'HSSE MANAGER'

    def approve(self, user, response=''):
        """Approve the change request."""
        if not self.can_be_approved_by(user):
            raise ValueError("Only HSSE Manager can approve change requests")
        
        self.status = 'APPROVED'
        self.admin_response = response
        self.responded_by = user
        self.responded_at = timezone.now()
        self.save()
        
        # Create new version of the document for editing
        self.document.create_new_version_for_change_request()

    def reject(self, user, response=''):
        """Reject the change request."""
        if not self.can_be_rejected_by(user):
            raise ValueError("Only HSSE Manager can reject change requests")
        
        self.status = 'REJECTED'
        self.admin_response = response
        self.responded_by = user
        self.responded_at = timezone.now()
        self.save()

    def save(self, *args, **kwargs):
        """Override save to create notifications."""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Create notification for new change requests
        if is_new:
            try:
                from accounts.models import Notification
                Notification.create_change_request_notification(self)
            except Exception as e:
                # Log error but don't fail the save
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to create change request notification: {e}")

    def can_transition_to(self, new_status):
        """Validate if the document can transition to the new status."""
        valid_transitions = {
            'DRAFT': ['VERIFICATION', 'REJECTED'],
            'VERIFICATION': ['APPROVAL', 'REJECTED'],
            'APPROVAL': ['APPROVED', 'REJECTED'],
            'REJECTED': ['DRAFT'],
            'APPROVED': ['DRAFT']  # For new versions
        }
        return new_status in valid_transitions.get(self.status, [])

    def transition_to(self, new_status, user, comment=''):
        """Safely transition the document to a new status."""
        if not self.can_transition_to(new_status):
            raise ValueError(f"Cannot transition from {self.status} to {new_status}")
        
        self.status = new_status
        self.save()
        
        # Create workflow entry
        action_map = {
            'VERIFICATION': 'SUBMIT',
            'APPROVAL': 'VERIFY',
            'APPROVED': 'APPROVE',
            'REJECTED': 'REJECT'
        }
        
        ApprovalWorkflow.objects.create(
            document=self,
            position=user.position,
            action=action_map.get(new_status, 'SUBMIT'),
            performed_by=user,
            comment=comment
        )

    def is_editable(self, user):
        """Check if the document can be edited by the given user."""
        if self.status == 'DRAFT':
            return user == self.created_by
        return False

    def is_verifiable(self, user):
        """Check if the document can be verified by the given user."""
        return (
            self.status == 'VERIFICATION' and
            user.position in ['OPS MANAGER', 'HSSE MANAGER']
        )

    def is_approvable(self, user):
        """Check if the document can be approved by the given user."""
        return (
            self.status == 'APPROVAL' and
            user.position == 'MD'
        )

    def is_rejectable(self, user):
        """Check if the document can be rejected by the given user."""
        return (
            self.status in ['VERIFICATION', 'APPROVAL'] and
            user.position in ['OPS MANAGER', 'HSSE MANAGER', 'MD']
        )

    def get_workflow_history(self):
        """Get the complete workflow history of the document."""
        return self.approvalworkflow_set.all().order_by('timestamp')

    def get_current_version(self):
        """Get the current version string."""
        return f"{self.version}.{self.revision_number}"

    def create_new_version(self):
        """Create a new version of the document."""
        if self.status != 'APPROVED':
            raise ValueError("Only approved documents can have new versions")
        
        # Increment version number
        major, minor = map(int, self.version.split('.'))
        self.version = f"{major + 1}.0"
        self.revision_number = 1.0
        self.status = 'DRAFT'
        self.save()

    def validate_against_template(self):
        """Validate this document against its template."""
        if self.template:
            return self.template.validate_document(self)
        return []

# =============================
# Document Template
# =============================
class DocumentTemplate(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    document_type = models.CharField(max_length=20, choices=Document.DOC_TYPES)
    department = models.CharField(max_length=20, choices=User.DEPARTMENT_CHOICES)
    version = models.CharField(max_length=10, default="1.0")
    is_active = models.BooleanField(default=True)
    
    # Template structure
    sections = models.JSONField(default=dict, help_text="JSON structure defining document sections and fields")
    required_fields = models.JSONField(default=list, help_text="List of required field names")
    validation_rules = models.JSONField(default=dict, help_text="JSON structure defining field validation rules")
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='templates_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='templates_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.name} (v{self.version})"
    
    def create_document_from_template(self, user, title, description=""):
        """Create a new document from this template."""
        if not self.is_active:
            raise ValueError("Cannot create document from inactive template")
            
        # Create new document with template data
        document = Document.objects.create(
            title=title,
            description=description,
            document_type=self.document_type,
            department=self.department,
            version="1.0",
            revision_number=1.0,
            created_by=user
        )
        
        # Add template metadata to document
        document.metadata = {
            'template_id': self.id,
            'template_version': self.version,
            'sections': self.sections,
            'required_fields': self.required_fields,
            'validation_rules': self.validation_rules
        }
        document.save()
        
        return document
    
    def validate_document(self, document):
        """Validate a document against this template's rules."""
        errors = []
        
        # Check required fields
        for field in self.required_fields:
            if not document.metadata.get(field):
                errors.append(f"Required field '{field}' is missing")
        
        # Check validation rules
        for field, rules in self.validation_rules.items():
            value = document.metadata.get(field)
            if value:
                for rule_type, rule_value in rules.items():
                    if rule_type == 'min_length' and len(value) < rule_value:
                        errors.append(f"Field '{field}' must be at least {rule_value} characters")
                    elif rule_type == 'max_length' and len(value) > rule_value:
                        errors.append(f"Field '{field}' must be at most {rule_value} characters")
                    elif rule_type == 'pattern' and not re.match(rule_value, value):
                        errors.append(f"Field '{field}' does not match required pattern")
        
        return errors

# =============================
# Record
# =============================
class Record(models.Model):
    """
    Stores submitted form data as an uploaded file.
    Includes an approval workflow.
    """
    STATUS_CHOICES = [
        ('PENDING_REVIEW', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form_document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name='records', limit_choices_to={'document_type': 'FORM'})
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='records_submitted')
    submitted_file = models.FileField(upload_to='records/%Y/%m/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING_REVIEW')
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Approval fields
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='records_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    def __str__(self):
        return f"Record for {self.form_document.title} submitted by {self.submitted_by.get_full_name if self.submitted_by else 'Unknown'}"

    def can_be_reviewed_by(self, user):
        """Only HSSE Manager can review records."""
        return user.position == 'HSSE MANAGER'

    def approve(self, user):
        if not self.can_be_reviewed_by(user):
            raise ValueError("You do not have permission to approve this record.")
        
        self.status = 'APPROVED'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.rejection_reason = ''
        self.save()

    def reject(self, user, reason):
        if not self.can_be_reviewed_by(user):
            raise ValueError("You do not have permission to reject this record.")
        
        self.status = 'REJECTED'
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.rejection_reason = reason
        self.save()
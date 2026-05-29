"""
Outbound Email Relay Module

Provides outbound email delivery capabilities for the mail server.
"""

from .mx_lookup import MXLookup
from .delivery import OutboundSMTPSender
from .smtp2go_delivery import SMTP2GODelivery
from .queue_processor import OutboundQueueProcessor
from .storage import queue_outbound_email, get_delivery_status
from .rate_limiter import OutboundRateLimiter
from .dkim_signer import DKIMSigner, load_dkim_config

__all__ = [
	'MXLookup',
	'OutboundSMTPSender',
	'SMTP2GODelivery',
	'OutboundQueueProcessor',
	'queue_outbound_email',
	'get_delivery_status',
	'OutboundRateLimiter',
	'DKIMSigner',
	'load_dkim_config'
]

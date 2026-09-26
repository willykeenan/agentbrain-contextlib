"""ContextLib: a project library that outlives every agent session.

Apache-2.0, copyright KE Studios.
"""
from agentbrain_contextlib.brief import build_brief
from agentbrain_contextlib.capture import capture_result
from agentbrain_contextlib.index import Index
from agentbrain_contextlib.library import Library, ledger_hash, writer_slug
from agentbrain_contextlib.records import (
    PREFIX,
    REVIEW_DAYS,
    STATUSES,
    TYPE_DIR,
    TYPES,
    new_id,
    parse_record,
    render_record,
    validate,
)
from agentbrain_contextlib.scanner import scan_text

__version__ = '0.1.0'

__all__ = [
    'TYPES',
    'STATUSES',
    'PREFIX',
    'TYPE_DIR',
    'REVIEW_DAYS',
    'parse_record',
    'render_record',
    'new_id',
    'validate',
    'scan_text',
    'Library',
    'ledger_hash',
    'writer_slug',
    'Index',
    'build_brief',
    'capture_result',
    '__version__',
]

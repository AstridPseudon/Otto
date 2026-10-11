"""Exact current required manager-guide selection shared by directive paths."""
from collections.abc import Mapping

from herzchen.contracts import ResourceRef
from herzchen.content.instructions import validate_instruction_content
from .owner_readers import json_value


def resolve_required_instruction_adoption(adoptions, trusted_ref, content_reader):
    """Resolve one required adoption by an exact trusted full revision pin.

    Display labels such as ``BASE`` are not selectors. The controller's current
    guide pin or an authenticated application receipt supplies the authority.
    """
    if not isinstance(trusted_ref, Mapping):
        raise ValueError('trusted manager guide reference is unavailable')
    ref = ResourceRef.from_dict(trusted_ref)
    if not all((ref.authority, ref.kind, ref.id, ref.revision)):
        raise ValueError('trusted manager guide must include a full revision reference')
    full_ref = ref.to_dict()
    matches = [row for row in adoptions if isinstance(row, Mapping)
               and row.get('required') is True and row.get('resource_ref') == full_ref]
    if len(matches) != 1:
        raise ValueError('exactly one required adoption of the trusted manager guide is needed')
    row = matches[0]
    observed = json_value(content_reader.read(ref))
    if (not isinstance(observed, Mapping) or observed.get('identity') != full_ref
            or observed.get('revision') != ref.revision):
        raise ValueError('trusted manager guide read does not match its exact immutable revision')
    content = observed.get('content')
    digest = validate_instruction_content(content)
    if row.get('resource_name') != content.get('name') or row.get('content_digest') != digest:
        raise ValueError('trusted manager guide adoption label or digest does not match its content')
    return row, observed, digest

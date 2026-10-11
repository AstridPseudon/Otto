"""Atomic supervision and shared-document removal in the owner service."""
from herzchen.contracts import ResourceRef
from otto.portfolio.shared_documents import remove_project_associations


def detach_project(session, project, args):
    from .portfolio import dependency_service
    dependencies = dependency_service(session, args)
    dependencies.authorize(project.ref)
    service = getattr(args, 'service_status', None) or {}
    from otto.portfolio.status import manager_activity
    if manager_activity(session.store, project.ref, service_status=service)['state'] == 'running':
        return {'outcome': 'error', 'error': {'code': 'manager_running',
                'message': "cannot detach while the project's manager is running"}, 'provider_called': False}
    portfolio = ResourceRef.from_dict(session.host['portfolio_ref'])
    with session.store.transaction():
        result = session.owner.orchestration_port.detach_existing_project(
            actor=dependencies.actor, request_id='portfolio-detach:' + project.ref.id + ':' + str(project.version),
            project_ref=project.ref, expected_project_version=project.version)
        unlinks = remove_project_associations(session.owner, project.ref, portfolio, actor=dependencies.actor)
    return {**result, 'document_receipts': unlinks, 'provider_called': False}

"""Fixed original W0 view; consumes activation without materializing or starting it."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from herzchen.contracts import ResourceRef
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.manager_journey_service import ManagerJourneyService
from registered_view_attachment import attach_registered_view, protected_host_relay, activation_boundary

HERE = Path(__file__).resolve().parent
PROJECT = 'project-68aca4e5bce229bddab0b89a6b52'
RUN = 'otto-work-model-W0-host-ergonomics'
SUPERVISOR = 'assignment-69cc129cb7fdadf8cc7015ce9b31'
PRINCIPAL = 'claude-code-orchestrator'
VIEW = 'claude-work-model-W0'


def shared_class():
    spec = importlib.util.spec_from_file_location('otto.hostctl.W0_shared_serve', HERE / 'w0_shared_host_service.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HostOwnerService


def legacy_attach(common, *, manifest):
    from otto.hostctl.config import load
    from otto.hostctl.serve import _registration
    from otto.hostctl.cli import receipt_path
    from otto.portfolio.operating_setup import read_setup
    host, clients = common.host_clients.shared_host, common.host_clients
    router, owner = clients.router, common.scoped_clients.owner
    config = load(Path('/Users/hannahomalley/.otto'))
    entry = config.get('hosts', {}).get('claude-code') or {}
    if entry.get('principal') != PRINCIPAL or entry.get('root_assignment_ref', {}).get('id') != SUPERVISOR:
        raise PermissionError('original admitted Claude host identity is required')
    project = owner.graph.current(ResourceRef(owner.store.authority, 'work.project', PROJECT))
    registration = project.payload.get('custom', {}).get('otto_host_registration', {})
    if registration.get('run_id') != RUN:
        raise PermissionError('original W0 registration is required')
    supervisor = owner.assignments.get(ResourceRef.from_dict(entry['root_assignment_ref']))
    relation = project.payload.get('metadata', {}).get('otto_orchestrator', {})
    if (supervisor.ref.id != SUPERVISOR or supervisor.principal != PRINCIPAL
            or supervisor.role != 'orchestrator' or supervisor.generation != entry['root_generation']
            or relation.get('assignment_ref') != supervisor.ref.to_dict()
            or relation.get('generation') != supervisor.generation):
        raise PermissionError('original current W0 supervision is required')
    path = receipt_path(Path(config['home']), 'activate-'+RUN)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise PermissionError('bounded original W0 activation receipt required')
    receipt = _registration(config, RUN)
    if receipt.get('run_id') != RUN or receipt.get('project_ref', {}).get('id') != PROJECT:
        raise PermissionError('existing original W0 activation receipt is required')
    manager = receipt['steps']['manager']
    if manager['binding']['model'] != 'claude-haiku-5-5' or manager['binding']['reasoning'] != 'medium':
        raise PermissionError('original W0 manager model/effort differs')
    # The existing owner authorizes exactly this original additional service
    # scope. It does not add W0 to the main root's issued four/nine policy.
    grant = owner.project_read_grant
    owner.project_read_grant = ProjectReadGrant(owner.owner_actor,
        tuple(sorted(set(grant.project_ids) | {PROJECT})),
        'otto.W0-existing-activated-view.v1', manifest['source_commit'])
    port = router.due_port
    session = SimpleNamespace(config=config, owner=owner, due_port=port, binding=owner.binding,
        store=router.store, actor=owner.owner_actor, portfolio=owner.portfolio(due_port=port),
        execution_application=lambda adapter, manager_actor=None: owner.execution_application(
            due_port=port, adapter=adapter, manager_actor=manager_actor))
    server = shared_class()(session, project, shared_host=host,
                            shared_native_ingress=host.caller_binding_reader)
    setup = read_setup(server.portfolio.operations, project.ref.to_dict())
    if setup is None or not isinstance(setup.get('roles', {}).get('manager'), str):
        raise PermissionError('original W0 activation operating setup must be prepared before view installation')
    if server.state.get('schedule_id') is None:
        server.state['schedule_id'] = setup['roles']['manager']
    current = owner.assignments.get(ResourceRef.from_dict(server.state['assignment_ref']))
    if current.ref.id != manager['assignment_ref']['id'] or current.generation != manager['generation']:
        raise PermissionError('original W0 manager identity/generation differs')
    server.state['orchestrator_assignment_ref'] = supervisor.ref.to_dict()
    # Canonical generated run input and the original mandate workspace may be
    # distinct. The maintained adapter constructor represents both explicitly.
    run = server.render_run_view().resolve()
    workspace = Path(server.worktree()).resolve()
    server.paths['socket'] = host.socket_path
    from otto.agents.claude_adapter import ClaudeWorkerAdapter, ClaudeNativeResultVerifier
    from otto.agents.claude_cli import LauncherPin
    from otto.hostctl.adapters import claude_settings, native_state_root
    settings = claude_settings(config)
    launcher = LauncherPin.inspect(settings['launcher'], qualified=settings.get('qualified_versions'))
    def factory(*, principal, model, reasoning, **_):
        if model not in settings['models'] or reasoning not in settings['efforts']:
            raise PermissionError('original W0 model/effort lacks the existing admitted adapter')
        return ClaudeWorkerAdapter(owner=principal, source=str(run), worktree=str(workspace),
            launcher_pin=launcher, state_root=str(native_state_root(config)), requested_model=model,
            requested_reasoning=reasoning, roles=('manager', 'worker'),
            authentication=settings.get('authentication', 'existing-user'),
            native_caller_socket=str(host.socket_path), native_process_observer=host.caller_binding_reader.observe,
            manager_write_roots=(), manager_env={'OTTO_CALLER_SOCKET': str(host.socket_path), 'OTTO_PROJECT': RUN})
    server.adapter_factory = factory
    session.execution_application = lambda adapter, manager_actor=None: owner.execution_application(
        due_port=port, adapter=adapter, manager_actor=manager_actor,
        native_result_verifier=ClaudeNativeResultVerifier(), issue_delivery=server.help_delivery)
    service = ManagerJourneyService(server=server, host=host, run_path=run, workspace=workspace,
        orchestrator_principal=PRINCIPAL, help_reply_authorizer=server.reply_authorizer())
    from retired_original_view_hold import qualify as qualify_retired, fence as fence_retired
    original_due = port.read_due(server.state['schedule_id'])
    application = service._execution(principal=original_due['recipient'],model=original_due['requested_model'],
        reasoning=original_due['requested_reasoning'],evidence_id='W0-retained-original-custody')
    retired = qualify_retired(application,original_due)
    if retired is not None:fence_retired(service,retired)
    expanded, proof = attach_registered_view(router=router, service=service,
        native_ingress=host.caller_binding_reader, view_key=VIEW, expected_project_id=PROJECT,
        expected_supervisor_ref=supervisor.ref.to_dict(), expected_supervisor_principal=PRINCIPAL,
        expected_run_id=RUN)
    rows = [row for row in proof['host_recovery']['occurrences']
            if row['schedule_id'] == proof['schedule_id']]
    prepared = len(rows) == 1 and rows[0]['outcome'] == 'prepared'
    raw = port.read_due(proof['schedule_id'])
    terminal = (len(rows) == 1 and rows[0].get('historical_terminal_projection') is True
                and raw.get('completion_state') == 'succeeded' and raw.get('stop_state') == 'completed')
    if not prepared and not terminal and retired is None:
        raise PermissionError('original W0 first occurrence did not qualify prepared before provider')
    clients.router = expanded
    clients.protected_relay = protected_host_relay(clients, service, proof, previous=clients.protected_relay)
    server._save_state()
    # Exact queue eligibility is a separate projection from running counts.
    old_status = clients._status
    def status(state='serving'):
        return {**old_status(state), 'execution_changing_boundary': activation_boundary(host)}
    clients._status = status
    return {**proof, 'source_commit': manifest['source_commit'],
            **(retired or {}), 'current_context_qualified': prepared and retired is None, 'historical_terminal_projection': terminal,
            'canonical_run_view': str(run), 'workspace': str(workspace),
            'main_root_scope_unchanged': True, 'activation_repeated': False, 'provider_called': False}


def attach(common, *, manifest):
    from w0_codex_view_join import result, attach as codex_attach
    if result(common.scoped_clients.owner) is None:
        return legacy_attach(common, manifest=manifest)
    return codex_attach(common, manifest=manifest)

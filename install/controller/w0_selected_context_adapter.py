"""W0 production renderer using the admitted physical context, not another view's BASE.
Canonical brief/digest/mandate remain unchanged. Verify finite immutable files
before construction and every useful-delivery rendering.
"""
import hashlib,json
from pathlib import Path
from otto.agents.herzchen_adapter import HerzchenCodexAdapter
CONTROLLER=Path('/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-onboarding-20261010/controller')
def selected(base):
 manifest=base.verify_install();install=manifest['selected_pack_materialization'];root=CONTROLLER/install['relative_root']
 relative=Path(install['relative_root']);pins=manifest['pack_hashes']
 if relative.is_absolute()or len(relative.parts)!=1 or '..'in relative.parts or root.is_symlink():raise PermissionError('selected physical pack root escaped')
 if not isinstance(pins,dict)or not 1<=len(pins)<=256:raise PermissionError('selected physical pack membership is not bounded')
 total=0
 actual={str(path.relative_to(root))for path in root.rglob('*')if path.is_file()}
 if actual!=set(pins):raise PermissionError('selected physical pack membership changed')
 for name,pin in pins.items():
  path=root/name;size=path.stat().st_size;total+=size
  if Path(name).is_absolute()or '..'in Path(name).parts or path.is_symlink()or not path.resolve().is_relative_to(root.resolve()):raise PermissionError('selected physical pack file escaped')
  if size>4*1024*1024 or total>16*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=pin:raise PermissionError('selected physical pack bytes changed')
 return {'root':str(root),'file_sha256':pins,'source_commit':install['source_commit'],'selected_pack_ref':install['selected_pack_ref']}
RETIRED_PREINITIALIZATION='role-84cd74ba0bd9fea6770f164288a4'
def pre_render_owner_authorized(self,request,*,existing_session=False):
 # Parse/render before any paid initializer; delegate the unchanged native guard.
 typed,digest_value,brief=self._typed_request('resume'if existing_session else'invoke',request)
 projection=self._request_projection(brief,digest_value,request)
 self.render_verified_invocation(brief,digest_value,request,model_projection=projection)
 return HerzchenCodexAdapter._invoke_owner_authorized(self,request,existing_session=existing_session)
def qualifies_retained_preinitialization_adapter(adapter,due):
 # Only reconstruction of the already authenticated historical84 report may
 # use this exact wrapper; initial acquisition retains the strict base guard.
 import w0_same_manager_migration as migration
 return (due.schedule_id==RETIRED_PREINITIALIZATION and due.project_ref==migration.PROJECT
  and due.role=='manager' and due.generation==2
  and due.assignment_ref['id']==migration.MANAGER
  and type(adapter)._invoke_owner_authorized is pre_render_owner_authorized)
def adapter_type(base):
 selected(base) # before an initializer can be invoked
 class W0PhysicalContextAdapter(HerzchenCodexAdapter):
  adapter_identity='otto.usage.installed-codex-cli.v1'
  _invoke_owner_authorized=pre_render_owner_authorized
  @staticmethod
  def render_verified_invocation(brief,digest_value,request,*,model_projection=None):
   context=selected(base)
   # Match the maintained shared per-view projection. It describes the exact
   # installed immutable pack; it does not claim another view's resource adoption.
   projection={'schema':'otto.closed-host.selected-pack-location.v1','root':context['root'],
    'source_commit':context['source_commit'],'selected_pack_ref':context['selected_pack_ref'],
    'instruction':'Canonical W0 BASE/mandate/resource refs control task authority. The listed immutable installed pack paths are physical context locations; candidate contents remain implementation only.',
    'files':{name:str(Path(context['root'])/name)for name in context['file_sha256']}}
   rendered=HerzchenCodexAdapter.render_verified_invocation(brief,digest_value,request,model_projection=model_projection)
   return '<otto-selected-pack-location>\n'+json.dumps(projection,sort_keys=True)+'\n</otto-selected-pack-location>\n'+rendered
 return W0PhysicalContextAdapter

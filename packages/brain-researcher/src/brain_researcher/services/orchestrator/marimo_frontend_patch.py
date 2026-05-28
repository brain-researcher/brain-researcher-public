"""Patch known marimo frontend bugs in built assets.

This module carries narrow compatibility patches for the marimo 0.23.x bundles
used by BR's single-user runtime image.

1. The upstream ``cell-editor`` bundle leaves staged ``update_cell`` state
   behind when inline AI fixes are accepted or rejected from the cell editor,
   which causes stale "Showing fix" diff banners to reappear after a
   reconnect/resume.
2. The upstream session/header path keeps using a rejected websocket session id
   for later HTTP requests, which can surface spurious "kernel not found"
   behavior in a tab that was refused because another tab already owns the
   kernel.

The patches are intentionally small and version-gated by exact source snippets
so builds fail loudly if the upstream bundle layout changes.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from pathlib import Path


_IMPORT_OLD = 'import{A as tm,E as ai,O as nm,T as rm,a as ii,d as om,n as am,o as im,r as si,s as sm,x as lm}from"./add-cell-with-ai-3_AIzd22.js";'
_IMPORT_EXPERIMENTAL = 'import{A as tm,E as ai,O as nm,T as rm,S as stagedActionsHook,a as ii,d as om,n as am,o as im,r as si,s as sm,x as lm}from"./add-cell-with-ai-3_AIzd22.js";'

_STATE_OLD = (
    "[w,y]=yn(km),E=(0,F.useId)(),C=ef(),{initialPrompt:I,triggerImmediately:D,"
    "cellId:B}=t??{},x=B===e,S=ie(lm).get(e),W;(S==null?void 0:S.type)==="
    '"update_cell"&&(W=S.previousCode);let{completion:te'
)
_STATE_EXPERIMENTAL = (
    "[w,y]=yn(km),E=(0,F.useId)(),C=ef(),{initialPrompt:I,triggerImmediately:D,"
    "cellId:B}=t??{},x=B===e,{removeStagedCell:stagedRemoveCell}=stagedActionsHook(),"
    'S=ie(lm).get(e),W;(S==null?void 0:S.type)==="update_cell"&&(W=S.previousCode);'
    "let{completion:te"
)
_STATE_NEW = (
    "[w,y]=yn(km),[cellEditorStagedMap,updateStagedCells]=yn(lm),E=(0,F.useId)(),"
    "C=ef(),{initialPrompt:I,triggerImmediately:D,cellId:B}=t??{},x=B===e,"
    'S=cellEditorStagedMap.get(e),W;(S==null?void 0:S.type)==="update_cell"&&'
    "(W=S.previousCode);let{completion:te"
)

_HANDLERS_OLD = 'L=()=>{s(N),ae("")},q=()=>{i(),ae("")},'
_HANDLERS_EXPERIMENTAL = (
    'L=()=>{s(N),(S==null?void 0:S.type)==="update_cell"&&stagedRemoveCell(e),ae("")},'
    'q=()=>{i(),(S==null?void 0:S.type)==="update_cell"&&stagedRemoveCell(e),ae("")},'
)
_HANDLERS_NEW = (
    'L=()=>{s(N),(S==null?void 0:S.type)==="update_cell"&&updateStagedCells(T=>{let j='
    'new Map(T);return j.delete(e),j}),ae("")},q=()=>{i(),(S==null?void 0:S.type)==='
    '"update_cell"&&updateStagedCells(T=>{let j=new Map(T);return j.delete(e),j}),'
    'ae("")},'
)

_SESSION_RUNTIME_OLD = (
    'var ut=(()=>{let t=new URL(window.location.href).searchParams.get(j.sessionId);'
    'return q(t)?(z(u=>{u.has(j.kiosk)||u.delete(j.sessionId)}),D.debug("Connecting '
    'to existing session",{sessionId:t}),t):(D.debug("Starting a new session",{sessionId:t}),'
    'K())})();function ft(){return ut}export{it as a,V as c,nt as i,N as l,q as n,'
    'ot as o,st as r,z as s,ft as t};'
)
_SESSION_RUNTIME_NEW = (
    'var ut=(()=>{let t=new URL(window.location.href).searchParams.get(j.sessionId);'
    'return q(t)?(window.sessionStorage.setItem("brHubSessionId",t),z(u=>{u.has(j.kiosk)'
    '||u.delete(j.sessionId)}),D.debug("Connecting '
    'to existing session",{sessionId:t}),t):(D.debug("Starting a new session",{sessionId:t}),'
    'K())})();function setBrSessionId(t){ut=t||"",t?window.sessionStorage.setItem('
    '"brHubSessionId",t):window.sessionStorage.removeItem("brHubSessionId")}function ft(){'
    'return ut}'
    'export{it as a,V as c,nt as i,N as l,q as n,ot as o,st as r,z as s,ft as t,'
    'setBrSessionId as u};'
)
_SESSION_VALIDATOR_OLD = 'function q(t){return t?/^s_[\\da-z]{6}$/.test(t):!1}'
_SESSION_VALIDATOR_NEW = (
    'function q(t){return t?/^(?:s_[\\da-z]{6}|studio_[A-Za-z0-9]+)$/.test(t):!1}'
)

_CONFIG_HEADERS_OLD = (
    'headers(){let t={"Marimo-Session-Id":R(),"Marimo-Server-Token":'
    'this.config.serverToken??"","x-runtime-url":this.httpURL.toString()};return '
    'this.config.authToken&&(t.Authorization=`Bearer ${this.config.authToken}`),t}'
    'sessionHeaders(){return{"Marimo-Session-Id":R()}}'
)
_CONFIG_HEADERS_NEW = (
    'headers(){let t=R(),e={"Marimo-Server-Token":this.config.serverToken??"",'
    '"x-runtime-url":this.httpURL.toString()};return t&&(e["Marimo-Session-Id"]=t),'
    'this.config.authToken&&(e.Authorization=`Bearer ${this.config.authToken}`),e}'
    'sessionHeaders(){let t=R();return t?{"Marimo-Session-Id":t}:{}}'
)

_PANELS_SESSION_IMPORT_OLD = 'import{i as xt}from"./session-DdnWW30b.js";'
_PANELS_SESSION_IMPORT_NEW = (
    'import{i as xt,u as setBrSessionId}from"./session-DdnWW30b.js";'
)
_PANELS_ON_OPEN_OLD = 'V=async()=>{t.current=!0,w({state:p.OPEN})}'
_PANELS_ON_OPEN_NEW = 'V=async()=>{setBrSessionId(n),t.current=!0,w({state:p.OPEN})}'
_PANELS_ALREADY_CONNECTED_OLD = (
    'case"MARIMO_ALREADY_CONNECTED":w({state:p.CLOSED,code:L.ALREADY_RUNNING,reason:'
    '"another browser tab is already connected to the kernel",canTakeover:!0}),'
    'W.close();return;'
)
_PANELS_ALREADY_CONNECTED_NEW = (
    'case"MARIMO_ALREADY_CONNECTED":setBrSessionId(""),w({state:p.CLOSED,'
    'code:L.ALREADY_RUNNING,reason:"another browser tab is already connected to the '
    'kernel",canTakeover:!0}),W.close();return;'
)
_PANELS_KERNEL_NOT_FOUND_OLD = (
    'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":case"MARIMO_NO_SESSION_ID":'
    'case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":w({state:p.CLOSED,'
    'code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),W.close();return;'
)
_PANELS_KERNEL_NOT_FOUND_NEW = (
    'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":case"MARIMO_NO_SESSION_ID":'
    'case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":setBrSessionId(""),w({state:p.CLOSED,'
    'code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),W.close();return;'
)
_PANELS_MALFORMED_QUERY_OLD = (
    'case"MARIMO_MALFORMED_QUERY":w({state:p.CLOSED,code:L.MALFORMED_QUERY,reason:"the '
    'kernel did not recognize a request; please file a bug with marimo"});return;'
)
_PANELS_MALFORMED_QUERY_NEW = (
    'case"MARIMO_MALFORMED_QUERY":setBrSessionId(""),w({state:p.CLOSED,'
    'code:L.MALFORMED_QUERY,reason:"the kernel did not recognize a request; please '
    'file a bug with marimo"});return;'
)
_PANELS_STARTUP_ERROR_OLD = (
    'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){w({state:p.CLOSED,'
    'code:L.KERNEL_STARTUP_ERROR,reason:"Failed to start kernel sandbox"}),'
    'W.close();return}'
)
_PANELS_STARTUP_ERROR_NEW = (
    'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){setBrSessionId(""),w({state:p.CLOSED,'
    'code:L.KERNEL_STARTUP_ERROR,reason:"Failed to start kernel sandbox"}),'
    'W.close();return}'
)
_PANELS_ON_ERROR_OLD = (
    'onError:h=>{v.warn("WebSocket error",h),w({state:p.CLOSED,'
    'code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),xA()}})'
)
_PANELS_ON_ERROR_NEW = (
    'onError:h=>{if(!xt())return;v.warn("WebSocket error",h),setBrSessionId(""),'
    'w({state:p.CLOSED,code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),xA()}})'
)
_PANELS_ALREADY_CONNECTED_CASE = 'case"MARIMO_ALREADY_CONNECTED":'
_PANELS_KERNEL_NOT_FOUND_CASES = (
    'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":case"MARIMO_NO_SESSION_ID":'
    'case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":'
)
_PANELS_MALFORMED_QUERY_CASE = 'case"MARIMO_MALFORMED_QUERY":'
_PANELS_STARTUP_ERROR_CASE = 'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){'
_PANELS_SESSION_IMPORT_RE = re.compile(
    r'import\{i as (?P<getter>[A-Za-z_$][\w$]*)(?P<setter>,u as setBrSessionId)?\}'
    r'from"(?P<path>\./session-[^"]+\.js)";'
)
_PANELS_WS_SESSION_ID_RE = re.compile(
    r'getWsURL\((?P<session_id>[A-Za-z_$][\w$]*)\)\.toString\(\)'
)
_PANELS_ON_OPEN_RE = re.compile(
    r'(?P<prefix>[A-Za-z_$][\w$]*=async\(\)=>\{)'
    r'(?P<current_ref>[A-Za-z_$][\w$]*)\.current=!0,'
    r'(?P<state_setter>[A-Za-z_$][\w$]*)\(\{state:(?P<state_enum>[A-Za-z_$][\w$]*)\.OPEN\}\)\}'
)
_PANELS_ON_ERROR_RE = re.compile(
    r'onError:(?P<error_arg>[A-Za-z_$][\w$]*)=>\{'
)

_AI_PROVIDER_REGISTRY_OLD = (
    'function yt(t){let e=t.get(Ni),a=t.get(Pi),r=t.get(Ti);return new To().register(new '
    'Fu(a)).register(new zu(r,a)).register(new Lu(t)).register(new Mu(t)).register(new '
    'So(e.connectionsMap,a))}'
)
_AI_PROVIDER_REGISTRY_NEW = (
    'let brHubResources=[],brHubResourcesPromise=null,brHubSections={TOOL:{name:"Tools",'
    'rank:6},DATASET:{name:"Datasets",rank:7},WORKFLOW:{name:"Workflows",rank:8},'
    'KG:{name:"Knowledge Graph",rank:9}};'
    'function brReadSessionId(t){try{let e=new URL(t,window.location.href).searchParams.get'
    '("session_id")||"";return e&&window.sessionStorage.setItem("brHubSessionId",e),e}'
    'catch{return""}}function brHubSessionId(){return brReadSessionId(window.location.href)||'
    'brReadSessionId(document.referrer)||window.sessionStorage.getItem("brHubSessionId")||""}'
    'async function brEnsureHubResources(){if(brHubResources.length>0)return brHubResources;'
    'if(brHubResourcesPromise)return brHubResourcesPromise;let t=brHubSessionId();return '
    't?(brHubResourcesPromise=fetch('
    '`/api/hub/sessions/${encodeURIComponent(t)}/resources`,{credentials:"same-origin"})'
    '.then(async e=>{if(!e.ok)throw new Error(`BR hub resources ${e.status}`);let a=await '
    'e.json(),r=Array.isArray(a==null?void 0:a.resources)?a.resources:[];return '
    'brHubResources=r.filter(s=>s&&typeof s.uri=="string"&&typeof s.type=="string"),'
    'brHubResources}).catch(e=>(se.warn("Failed to load BR hub resources",e),'
    'brHubResources=[])).finally(()=>{brHubResourcesPromise=null}),brHubResourcesPromise)'
    ':[]}class BrHubResourceProvider extends Ft{constructor(t,e,a,r){super();this.contextType=t,'
    'this.title=e,this.section=a,this.rank=r,this.mentionPrefix="@"}getItems(){return '
    'brHubResources.filter(t=>t.type===this.contextType)}parseContextIds(t){let e=RegExp('
    '`${this.mentionPrefix}(${this.contextType}):\\\\/\\\\/([^\\\\s]+)`,"g"),a=[...t.matchAll(e)],'
    'r=s=>`${s[1]}://${s[2]}`;return[...new Set(a.map(([t,...s])=>r(s)))]}formatCompletion(t){'
    'let e=`@${t.uri}`,a=t.details||t.description||t.name;return{label:e,'
    'displayLabel:t.name,detail:t.description||"",boost:this.rank,type:this.contextType,'
    'apply:e,section:this.section,info:a}}formatContext(t){let e=t.data&&typeof '
    't.data=="object"?t.data:{};return Zt({type:this.contextType,data:e,details:t.details||'
    't.description||""})}async getAttachments(){return[]}}function yt(t){let e=t.get(Ni),'
    'a=t.get(Pi),r=t.get(Ti);return new To().register(new Fu(a)).register(new zu(r,a))'
    '.register(new Lu(t)).register(new Mu(t)).register(new So(e.connectionsMap,a))'
    '.register(new BrHubResourceProvider("tool","Tools",brHubSections.TOOL,St.HIGH))'
    '.register(new BrHubResourceProvider("dataset","Datasets",brHubSections.DATASET,'
    'St.MEDIUM)).register(new BrHubResourceProvider("workflow","Workflows",'
    'brHubSections.WORKFLOW,St.MEDIUM)).register(new BrHubResourceProvider('
    '"kg","Knowledge Graph",brHubSections.KG,St.MEDIUM))}'
)
_AI_AUTOCOMPLETE_OLD = (
    'autocomplete:xc(async()=>{let s=yt(a).getAllItems();return s.length===0?Pc:s},s=>{var '
    'n;return s.type===si?$c:((n=yt(a).getProvider(s.type))==null?void 0:n.formatCompletion'
    '(s))||{}})'
)
_AI_AUTOCOMPLETE_NEW = (
    'autocomplete:xc(async()=>{await brEnsureHubResources();let s=yt(a).getAllItems();return '
    's.length===0?Pc:s},s=>{var n;return s.type===si?$c:((n=yt(a).getProvider(s.type))'
    '==null?void 0:n.formatCompletion(s))||{}})'
)
_AI_CONTEXT_REQUEST_OLD = (
    'async function Wu({input:t}){let e="",a=[];if(t.includes("@")){let r=yt(Gr),s='
    'r.parseAllContextIds(t);e=r.formatContextForAI(s);try{a=await r.getAttachmentsForContext'
    '(s),se.debug("Included attachments",a.length)}catch(n){se.error("Error getting '
    'attachments:",n)}}return{body:{includeOtherCode:rs(""),context:{plainText:e,schema:[],'
    'variables:[]}},attachments:a}}'
)
_AI_CONTEXT_REQUEST_NEW = (
    'async function Wu({input:t}){let e="",a=[];if(t.includes("@")){await '
    'brEnsureHubResources();let r=yt(Gr),s=r.parseAllContextIds(t);e=r.formatContextForAI(s);'
    'try{a=await r.getAttachmentsForContext(s),se.debug("Included attachments",a.length)}'
    'catch(n){se.error("Error getting attachments:",n)}}return{body:{includeOtherCode:rs("")'
    ',context:{plainText:e,schema:[],variables:[]}},attachments:a}}'
)


def patch_cell_editor_source(source: str) -> str:
    """Return patched marimo cell-editor bundle source."""

    patched = source

    if _IMPORT_EXPERIMENTAL in patched:
        patched = patched.replace(_IMPORT_EXPERIMENTAL, _IMPORT_OLD, 1)

    if _STATE_NEW not in patched:
        if _STATE_EXPERIMENTAL in patched:
            patched = patched.replace(_STATE_EXPERIMENTAL, _STATE_NEW, 1)
        elif _STATE_OLD in patched:
            patched = patched.replace(_STATE_OLD, _STATE_NEW, 1)
        else:
            raise ValueError("Could not find marimo staged state block to patch")

    if _HANDLERS_NEW not in patched:
        if _HANDLERS_EXPERIMENTAL in patched:
            patched = patched.replace(_HANDLERS_EXPERIMENTAL, _HANDLERS_NEW, 1)
        elif _HANDLERS_OLD in patched:
            patched = patched.replace(_HANDLERS_OLD, _HANDLERS_NEW, 1)
        else:
            raise ValueError("Could not find marimo inline handler block to patch")

    return patched


def patch_session_source(source: str) -> str:
    """Return patched marimo session bundle source."""

    patched = source

    if _SESSION_VALIDATOR_OLD in patched:
        patched = patched.replace(_SESSION_VALIDATOR_OLD, _SESSION_VALIDATOR_NEW, 1)

    if "setBrSessionId as u" in patched:
        return patched

    if _SESSION_RUNTIME_OLD not in patched:
        raise ValueError("Could not find marimo session runtime block to patch")

    return patched.replace(_SESSION_RUNTIME_OLD, _SESSION_RUNTIME_NEW, 1)


def patch_config_source(source: str) -> str:
    """Return patched marimo config bundle source."""

    if _CONFIG_HEADERS_NEW in source:
        return source

    if _CONFIG_HEADERS_OLD not in source:
        raise ValueError("Could not find marimo runtime headers block to patch")

    return source.replace(_CONFIG_HEADERS_OLD, _CONFIG_HEADERS_NEW, 1)


def patch_panels_source(source: str) -> str:
    """Return patched marimo panels bundle source."""

    patched = source

    import_match = _PANELS_SESSION_IMPORT_RE.search(patched)
    if import_match is None:
        raise ValueError("Could not find marimo panels session import to patch")

    session_getter = import_match.group("getter")
    if import_match.group("setter") is None:
        patched = patched.replace(
            import_match.group(0),
            f'import{{i as {session_getter},u as setBrSessionId}}'
            f'from"{import_match.group("path")}";',
            1,
        )

    ws_session_match = _PANELS_WS_SESSION_ID_RE.search(patched)
    if ws_session_match is None:
        raise ValueError("Could not find marimo websocket session id block to patch")
    session_id_var = ws_session_match.group("session_id")

    if f"setBrSessionId({session_id_var})" not in patched:
        on_open_match = _PANELS_ON_OPEN_RE.search(patched)
        if on_open_match is None:
            raise ValueError("Could not find marimo panels on-open block to patch")
        patched = patched.replace(
            on_open_match.group(0),
            (
                f'{on_open_match.group("prefix")}setBrSessionId({session_id_var}),'
                f'{on_open_match.group("current_ref")}.current=!0,'
                f'{on_open_match.group("state_setter")}('
                f'{{state:{on_open_match.group("state_enum")}.OPEN}})'
                "}"
            ),
            1,
        )

    replacements = (
        (
            _PANELS_ALREADY_CONNECTED_CASE,
            'case"MARIMO_ALREADY_CONNECTED":setBrSessionId(""),',
            "already-connected",
        ),
        (
            _PANELS_KERNEL_NOT_FOUND_CASES,
            f'{_PANELS_KERNEL_NOT_FOUND_CASES}setBrSessionId(""),',
            "kernel-not-found",
        ),
        (
            _PANELS_MALFORMED_QUERY_CASE,
            'case"MARIMO_MALFORMED_QUERY":setBrSessionId(""),',
            "malformed-query",
        ),
        (
            _PANELS_STARTUP_ERROR_CASE,
            'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){setBrSessionId(""),',
            "startup-error",
        ),
    )

    for old, new, label in replacements:
        if new in patched:
            continue
        if old not in patched:
            raise ValueError(f"Could not find marimo panels {label} block to patch")
        patched = patched.replace(old, new, 1)

    if f"if(!{session_getter}())return;setBrSessionId(\"\")" not in patched:
        on_error_match = _PANELS_ON_ERROR_RE.search(patched)
        if on_error_match is None:
            raise ValueError("Could not find marimo panels on-error block to patch")
        patched = patched.replace(
            on_error_match.group(0),
            (
                f'onError:{on_error_match.group("error_arg")}=>{{'
                f'if(!{session_getter}())return;setBrSessionId(""),'
            ),
            1,
        )

    return patched


def patch_add_cell_with_ai_source(source: str) -> str:
    """Return patched marimo add-cell-with-ai bundle source."""

    patched = source

    if "function brEnsureHubResources()" not in patched:
        if _AI_PROVIDER_REGISTRY_OLD not in patched:
            raise ValueError("Could not find marimo AI provider registry block to patch")
        patched = patched.replace(_AI_PROVIDER_REGISTRY_OLD, _AI_PROVIDER_REGISTRY_NEW, 1)

    if _AI_AUTOCOMPLETE_NEW not in patched:
        if _AI_AUTOCOMPLETE_OLD not in patched:
            raise ValueError("Could not find marimo AI autocomplete block to patch")
        patched = patched.replace(_AI_AUTOCOMPLETE_OLD, _AI_AUTOCOMPLETE_NEW, 1)

    if _AI_CONTEXT_REQUEST_NEW not in patched:
        if _AI_CONTEXT_REQUEST_OLD not in patched:
            raise ValueError("Could not find marimo AI context request block to patch")
        patched = patched.replace(_AI_CONTEXT_REQUEST_OLD, _AI_CONTEXT_REQUEST_NEW, 1)

    return patched


def _resolve_marimo_root(marimo_root: Path | None = None) -> Path:
    """Resolve the installed marimo package root."""

    if marimo_root is None:
        import marimo  # type: ignore[import-untyped]

        marimo_root = Path(marimo.__file__).resolve().parent

    return marimo_root


def find_asset(
    asset_glob: str,
    marimo_root: Path | None = None,
    *,
    required_marker: str | None = None,
) -> Path:
    """Locate a single built marimo asset matching ``asset_glob``.

    When multiple hashed bundles share a prefix, ``required_marker`` narrows the
    result to the bundle that contains a known source snippet.
    """

    marimo_root = _resolve_marimo_root(marimo_root)

    assets_dir = marimo_root / "_static" / "assets"
    matches = sorted(assets_dir.glob(asset_glob))
    if not matches:
        raise FileNotFoundError(
            f"No asset matching {asset_glob!r} found under {assets_dir}"
        )
    if required_marker is not None:
        matches = [
            path for path in matches if required_marker in path.read_text(errors="ignore")
        ]
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected exactly one marimo asset matching {asset_glob!r}, "
            f"found {len(matches)} under {assets_dir}"
        )
    return matches[0]


def patch_asset(asset_path: Path, patcher: Callable[[str], str]) -> bool:
    """Patch the asset in place. Returns True when the file changed."""

    original = asset_path.read_text()
    patched = patcher(original)
    if patched == original:
        return False
    asset_path.write_text(patched)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch installed marimo frontend bundles in place."
    )
    parser.add_argument(
        "--marimo-root",
        type=Path,
        default=None,
        help="Override the marimo package root (defaults to the installed package).",
    )
    args = parser.parse_args()

    marimo_root = _resolve_marimo_root(args.marimo_root)
    patch_plan = (
        ("add-cell-with-ai-*.js", "No resources", patch_add_cell_with_ai_source),
        ("cell-editor-*.js", "update_cell", patch_cell_editor_source),
        ("session-*.js", "Connecting to existing session", patch_session_source),
        ("config-*.js", "x-runtime-url", patch_config_source),
        ("panels-*.js", "MARIMO_ALREADY_CONNECTED", patch_panels_source),
    )

    for asset_glob, marker, patcher in patch_plan:
        asset_path = find_asset(asset_glob, marimo_root, required_marker=marker)
        changed = patch_asset(asset_path, patcher)
        status = "patched" if changed else "already-patched"
        print(f"{status}: {asset_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

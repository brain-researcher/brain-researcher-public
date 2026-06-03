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


_JS_IDENT = r"[A-Za-z_$][\w$]*"

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
_CELL_EDITOR_STATE_RE = re.compile(
    rf"(?P<binding>\[(?P<state_value>{_JS_IDENT}),(?P<state_setter>{_JS_IDENT})\]="
    rf"(?P<hook>{_JS_IDENT})\((?P<state_atom>{_JS_IDENT})\),)"
    rf"(?P<between>.*?)"
    rf"(?P<staged_var>{_JS_IDENT})=(?P<reader>{_JS_IDENT})"
    rf"\((?P<staged_atom>{_JS_IDENT})\)\.get\((?P<cell_id>{_JS_IDENT})\),"
    rf"(?P<previous_var>{_JS_IDENT});"
    rf"\((?P=staged_var)==null\?void 0:(?P=staged_var)\.type\)==="
    r'"update_cell"&&'
    rf"\((?P=previous_var)=(?P=staged_var)\.previousCode\);let\{{completion:",
    re.DOTALL,
)
_CELL_EDITOR_PATCHED_STATE_RE = re.compile(
    rf"\[cellEditorStagedMap,updateStagedCells\]=(?P<hook>{_JS_IDENT})"
    rf"\((?P<staged_atom>{_JS_IDENT})\),"
    rf"(?P<between>.*?)"
    rf"(?P<staged_var>{_JS_IDENT})=cellEditorStagedMap\.get"
    rf"\((?P<cell_id>{_JS_IDENT})\),(?P<previous_var>{_JS_IDENT});"
    rf"\((?P=staged_var)==null\?void 0:(?P=staged_var)\.type\)==="
    r'"update_cell"&&'
    rf"\((?P=previous_var)=(?P=staged_var)\.previousCode\);let\{{completion:",
    re.DOTALL,
)
_CELL_EDITOR_HANDLERS_RE = re.compile(
    rf"(?P<prefix>;let\{{theme:(?P<theme>{_JS_IDENT})\}}="
    rf"(?P<theme_fn>{_JS_IDENT})\(\),)"
    rf"(?P<accept_handler>{_JS_IDENT})=\(\)=>\{{"
    rf"(?P<accept_call>{_JS_IDENT}\({_JS_IDENT}\)),"
    rf"(?P<clear_call>{_JS_IDENT}\(\"\"\))\}},"
    rf"(?P<decline_handler>{_JS_IDENT})=\(\)=>\{{"
    rf"(?P<decline_call>{_JS_IDENT}\(\)),(?P=clear_call)\}},",
)
_CELL_EDITOR_HANDLER_MARKER = "updateStagedCells(brStagedCells=>"

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
_PANELS_STARTUP_ERROR_RETURN_CASE = 'case"MARIMO_KERNEL_STARTUP_ERROR":'

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
_AI_DATASOURCE_IMPORT_RE = re.compile(
    r'import\{(?P<body>[^}]+)\}from"\./datasource-[^"]+\.js";'
)
_AI_PROVIDER_REGISTRY_RE = re.compile(
    rf"function (?P<registry_fn>{_JS_IDENT})\((?P<store>{_JS_IDENT})\)\{{"
    rf"let (?P<connections>{_JS_IDENT})=(?P=store)\.get"
    rf"\((?P<connections_token>{_JS_IDENT})\),"
    rf"(?P<tables>{_JS_IDENT})=(?P=store)\.get"
    rf"\((?P<tables_token>{_JS_IDENT})\),"
    rf"(?P<variables>{_JS_IDENT})=(?P=store)\.get"
    rf"\((?P<variables_token>{_JS_IDENT})\);"
    rf"return new (?P<registry_class>{_JS_IDENT})\(\)"
    rf"\.register\(new (?P<tables_provider>{_JS_IDENT})\((?P=tables)\)\)"
    rf"\.register\(new (?P<variables_provider>{_JS_IDENT})"
    rf"\((?P=variables),(?P=tables)\)\)"
    rf"\.register\(new (?P<errors_provider>{_JS_IDENT})\((?P=store)\)\)"
    rf"\.register\(new (?P<cell_outputs_provider>{_JS_IDENT})\((?P=store)\)\)"
    rf"\.register\(new (?P<datasource_provider>{_JS_IDENT})"
    rf"\((?P=connections)\.connectionsMap,(?P=tables)\)\)\}}"
)
_AI_AUTOCOMPLETE_RE = re.compile(
    rf"autocomplete:(?P<autocomplete_fn>{_JS_IDENT})\(async\(\)=>\{{"
    rf"let (?P<items>{_JS_IDENT})=(?P<registry_fn>{_JS_IDENT})"
    rf"\((?P<store>{_JS_IDENT})\)\.getAllItems\(\);"
    rf"return (?P=items)\.length===0\?(?P<empty_items>{_JS_IDENT}):(?P=items)\}},"
    rf"(?P<item>{_JS_IDENT})=>\{{var (?P<provider>{_JS_IDENT});"
    rf"return (?P=item)\.type===(?P<empty_type>{_JS_IDENT})\?"
    rf"(?P<empty_completion>{_JS_IDENT}):\(\((?P=provider)="
    rf"(?P=registry_fn)\((?P=store)\)\.getProvider\((?P=item)\.type\)\)==null"
    rf"\?void 0:(?P=provider)\.formatCompletion\((?P=item)\)\)\|\|\{{\}}\}}\)"
)
_AI_CONTEXT_REQUEST_RE = re.compile(
    rf"async function (?P<function_name>{_JS_IDENT})\(\{{input:(?P<input>{_JS_IDENT})\}}\)"
    rf"\{{let (?P<context>{_JS_IDENT})=\"\",(?P<attachments>{_JS_IDENT})=\[\];"
    rf"if\((?P=input)\.includes\(\"@\"\)\)\{{"
    rf"let (?P<registry>{_JS_IDENT})=(?P<registry_fn>{_JS_IDENT})"
    rf"\((?P<store>{_JS_IDENT})\),"
    rf"(?P<context_ids>{_JS_IDENT})=(?P=registry)\.parseAllContextIds"
    rf"\((?P=input)\);"
    rf"(?P=context)=(?P=registry)\.formatContextForAI\((?P=context_ids)\);"
    rf"try\{{(?P=attachments)=await (?P=registry)\.getAttachmentsForContext"
    rf"\((?P=context_ids)\),(?P<logger>{_JS_IDENT})\.debug"
    rf"\(\"Included attachments\",(?P=attachments)\.length\)\}}"
    rf"catch\((?P<error>{_JS_IDENT})\)\{{(?P=logger)\.error"
    rf"\(\"Error getting attachments:\",(?P=error)\)\}}\}}"
    rf"return\{{body:\{{includeOtherCode:(?P<include_other_code>{_JS_IDENT})"
    rf"\(\"\"\),context:\{{plainText:(?P=context),schema:\[\],variables:\[\]\}}\}},"
    rf"attachments:(?P=attachments)\}}\}}"
)
_AI_AUTOCOMPLETE_PATCHED_RE = re.compile(
    rf"autocomplete:{_JS_IDENT}\(async\(\)=>\{{await brEnsureHubResources\(\);"
    rf"let {_JS_IDENT}={_JS_IDENT}\({_JS_IDENT}\)\.getAllItems\(\);"
)
_AI_CONTEXT_REQUEST_PATCHED_RE = re.compile(
    rf"if\({_JS_IDENT}\.includes\(\"@\"\)\)\{{await brEnsureHubResources\(\);"
    rf"let {_JS_IDENT}={_JS_IDENT}\({_JS_IDENT}\),"
    rf"{_JS_IDENT}={_JS_IDENT}\.parseAllContextIds\({_JS_IDENT}\);"
)


def patch_cell_editor_source(source: str) -> str:
    """Return patched marimo cell-editor bundle source."""

    patched = source

    if _IMPORT_EXPERIMENTAL in patched:
        patched = patched.replace(_IMPORT_EXPERIMENTAL, _IMPORT_OLD, 1)

    staged_var: str | None = None
    cell_id_var: str | None = None

    if "cellEditorStagedMap,updateStagedCells" not in patched:
        state_match = _CELL_EDITOR_STATE_RE.search(patched)
        if state_match is None:
            raise ValueError("Could not find marimo staged state block to patch")

        staged_var = state_match.group("staged_var")
        cell_id_var = state_match.group("cell_id")
        state_replacement = (
            f'{state_match.group("binding")}'
            f'[cellEditorStagedMap,updateStagedCells]='
            f'{state_match.group("hook")}({state_match.group("staged_atom")}),'
            f'{state_match.group("between")}'
            f'{staged_var}=cellEditorStagedMap.get({cell_id_var}),'
            f'{state_match.group("previous_var")};'
            f'({staged_var}==null?void 0:{staged_var}.type)==="update_cell"&&'
            f'({state_match.group("previous_var")}={staged_var}.previousCode);'
            "let{completion:"
        )
        patched = patched.replace(state_match.group(0), state_replacement, 1)

    if _CELL_EDITOR_HANDLER_MARKER not in patched:
        if staged_var is None or cell_id_var is None:
            state_match = _CELL_EDITOR_PATCHED_STATE_RE.search(patched)
            if state_match is None:
                raise ValueError("Could not find patched marimo staged state block")
            staged_var = state_match.group("staged_var")
            cell_id_var = state_match.group("cell_id")

        handler_match = _CELL_EDITOR_HANDLERS_RE.search(patched)
        if handler_match is None:
            raise ValueError("Could not find marimo inline handler block to patch")

        clear_staged = (
            f'({staged_var}==null?void 0:{staged_var}.type)==="update_cell"&&'
            "updateStagedCells(brStagedCells=>{"
            "let brNext=new Map(brStagedCells);"
            f"return brNext.delete({cell_id_var}),brNext"
            "})"
        )
        handler_replacement = (
            f'{handler_match.group("prefix")}'
            f'{handler_match.group("accept_handler")}=()=>{{'
            f'{handler_match.group("accept_call")},{clear_staged},'
            f'{handler_match.group("clear_call")}}},'
            f'{handler_match.group("decline_handler")}=()=>{{'
            f'{handler_match.group("decline_call")},{clear_staged},'
            f'{handler_match.group("clear_call")}}},'
        )
        patched = patched.replace(handler_match.group(0), handler_replacement, 1)

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


def _panels_insert_session_clear_after_case(
    source: str, case_anchor: str, label: str
) -> str:
    """Insert setBrSessionId("") in a direct or return-style switch case."""

    if (
        f'{case_anchor}setBrSessionId("")' in source
        or f'{case_anchor}return setBrSessionId("")' in source
    ):
        return source

    return_anchor = f"{case_anchor}return"
    if return_anchor in source:
        return source.replace(
            return_anchor, f'{case_anchor}return setBrSessionId(""),', 1
        )

    if case_anchor in source:
        return source.replace(case_anchor, f'{case_anchor}setBrSessionId(""),', 1)

    raise ValueError(f"Could not find marimo panels {label} block to patch")


def _panels_insert_startup_error_clear(source: str) -> str:
    """Patch the startup-error path across old inline and new transition layouts."""

    old_inline_new = f'{_PANELS_STARTUP_ERROR_CASE}setBrSessionId(""),'
    return_case_new = (
        f'{_PANELS_STARTUP_ERROR_RETURN_CASE}return setBrSessionId(""),'
    )
    if old_inline_new in source or return_case_new in source:
        return source

    if _PANELS_STARTUP_ERROR_CASE in source:
        return source.replace(_PANELS_STARTUP_ERROR_CASE, old_inline_new, 1)

    return _panels_insert_session_clear_after_case(
        source, _PANELS_STARTUP_ERROR_RETURN_CASE, "startup-error"
    )


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

    for case_anchor, label in (
        (_PANELS_ALREADY_CONNECTED_CASE, "already-connected"),
        (_PANELS_KERNEL_NOT_FOUND_CASES, "kernel-not-found"),
        (_PANELS_MALFORMED_QUERY_CASE, "malformed-query"),
    ):
        patched = _panels_insert_session_clear_after_case(patched, case_anchor, label)

    patched = _panels_insert_startup_error_clear(patched)

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


def _parse_named_import_aliases(import_body: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for part in import_body.split(","):
        part = part.strip()
        if not part:
            continue
        if " as " in part:
            exported, local = part.split(" as ", 1)
        else:
            exported = local = part
        aliases[exported.strip()] = local.strip()
    return aliases


def _get_datasource_import_aliases(source: str) -> dict[str, str]:
    import_match = _AI_DATASOURCE_IMPORT_RE.search(source)
    if import_match is None:
        raise ValueError("Could not find marimo AI datasource import block")

    aliases = _parse_named_import_aliases(import_match.group("body"))
    required_exports = {
        "a": "context formatter",
        "o": "base provider class",
        "r": "boost enum",
        "s": "provider registry class",
        "t": "datasource provider class",
    }
    missing = [
        description
        for export_name, description in required_exports.items()
        if export_name not in aliases
    ]
    if missing:
        raise ValueError(
            "Could not derive marimo AI datasource aliases for "
            + ", ".join(missing)
        )
    return aliases


def _verify_ai_provider_roles(
    source: str, registry_match: re.Match[str], aliases: dict[str, str]
) -> None:
    base_provider_class = aliases["o"]
    context_formatter = aliases["a"]
    boost_enum = aliases["r"]

    if registry_match.group("registry_class") != aliases["s"]:
        raise ValueError("Derived AI registry class does not match datasource import")
    if registry_match.group("datasource_provider") != aliases["t"]:
        raise ValueError(
            "Derived datasource provider class does not match datasource import"
        )

    for group_name, label in (
        ("tables_provider", "tables provider"),
        ("variables_provider", "variables provider"),
        ("errors_provider", "errors provider"),
        ("cell_outputs_provider", "cell-output provider"),
    ):
        provider = registry_match.group(group_name)
        provider_extends_re = re.compile(
            rf"{re.escape(provider)}=class extends {re.escape(base_provider_class)}"
        )
        if provider_extends_re.search(source) is None:
            raise ValueError(f"Could not verify marimo AI {label} base class")

    if f"return {context_formatter}({{type:this.contextType" not in source:
        raise ValueError("Could not verify marimo AI context formatter alias")
    if f"{boost_enum}.HIGH" not in source or f"{boost_enum}.MEDIUM" not in source:
        raise ValueError("Could not verify marimo AI boost enum alias")


def _render_ai_provider_registry_patch(
    registry_match: re.Match[str], aliases: dict[str, str], logger: str
) -> str:
    store = registry_match.group("store")
    connections = registry_match.group("connections")
    tables = registry_match.group("tables")
    variables = registry_match.group("variables")
    registry_fn = registry_match.group("registry_fn")
    base_provider_class = aliases["o"]
    context_formatter = aliases["a"]
    boost_enum = aliases["r"]

    return (
        'let brHubResources=[],brHubResourcesPromise=null,'
        'brHubSections={TOOL:{name:"Tools",rank:6},'
        'DATASET:{name:"Datasets",rank:7},'
        'WORKFLOW:{name:"Workflows",rank:8},'
        'KG:{name:"Knowledge Graph",rank:9}};'
        'function brReadSessionId(t){try{let e=new URL(t,window.location.href)'
        '.searchParams.get("session_id")||"";return e&&window.sessionStorage'
        '.setItem("brHubSessionId",e),e}catch{return""}}'
        'function brHubSessionId(){return brReadSessionId(window.location.href)||'
        'brReadSessionId(document.referrer)||window.sessionStorage'
        '.getItem("brHubSessionId")||""}'
        'async function brEnsureHubResources(){if(brHubResources.length>0)'
        'return brHubResources;if(brHubResourcesPromise)return brHubResourcesPromise;'
        'let t=brHubSessionId();return t?(brHubResourcesPromise=fetch('
        '`/api/hub/sessions/${encodeURIComponent(t)}/resources`,'
        '{credentials:"same-origin"}).then(async e=>{if(!e.ok)throw new Error('
        '`BR hub resources ${e.status}`);let a=await e.json(),'
        'r=Array.isArray(a==null?void 0:a.resources)?a.resources:[];'
        'return brHubResources=r.filter(s=>s&&typeof s.uri=="string"&&'
        'typeof s.type=="string"),brHubResources}).catch(e=>('
        f'{logger}.warn("Failed to load BR hub resources",e),brHubResources=[]))'
        '.finally(()=>{brHubResourcesPromise=null}),brHubResourcesPromise):[]}'
        f'class BrHubResourceProvider extends {base_provider_class}'
        '{constructor(t,e,a,r){super();this.contextType=t,this.title=e,'
        'this.section=a,this.rank=r,this.mentionPrefix="@"}'
        'getItems(){return brHubResources.filter(t=>t.type===this.contextType)}'
        'parseContextIds(t){let e=RegExp('
        '`${this.mentionPrefix}(${this.contextType}):\\\\/\\\\/([^\\\\s]+)`,"g"),'
        'a=[...t.matchAll(e)],r=s=>`${s[1]}://${s[2]}`;'
        'return[...new Set(a.map(([t,...s])=>r(s)))]}'
        'formatCompletion(t){let e=`@${t.uri}`,a=t.details||t.description||t.name;'
        'return{label:e,displayLabel:t.name,detail:t.description||"",'
        f'boost:this.rank,type:this.contextType,apply:e,section:this.section,'
        'info:a}}formatContext(t){let e=t.data&&typeof t.data=="object"?t.data:{};'
        f'return {context_formatter}('
        '{type:this.contextType,data:e,details:t.details||t.description||""})}'
        'async getAttachments(){return[]}}'
        f'function {registry_fn}({store}){{let {connections}={store}.get('
        f'{registry_match.group("connections_token")}),'
        f'{tables}={store}.get({registry_match.group("tables_token")}),'
        f'{variables}={store}.get({registry_match.group("variables_token")});'
        f'return new {registry_match.group("registry_class")}()'
        f'.register(new {registry_match.group("tables_provider")}({tables}))'
        f'.register(new {registry_match.group("variables_provider")}'
        f'({variables},{tables}))'
        f'.register(new {registry_match.group("errors_provider")}({store}))'
        f'.register(new {registry_match.group("cell_outputs_provider")}({store}))'
        f'.register(new {registry_match.group("datasource_provider")}'
        f'({connections}.connectionsMap,{tables}))'
        f'.register(new BrHubResourceProvider("tool","Tools",'
        f'brHubSections.TOOL,{boost_enum}.HIGH))'
        f'.register(new BrHubResourceProvider("dataset","Datasets",'
        f'brHubSections.DATASET,{boost_enum}.MEDIUM))'
        f'.register(new BrHubResourceProvider("workflow","Workflows",'
        f'brHubSections.WORKFLOW,{boost_enum}.MEDIUM))'
        f'.register(new BrHubResourceProvider("kg","Knowledge Graph",'
        f'brHubSections.KG,{boost_enum}.MEDIUM))}}'
    )


def patch_add_cell_with_ai_source(source: str) -> str:
    """Return patched marimo add-cell-with-ai bundle source."""

    patched = source

    if "function brEnsureHubResources()" not in patched:
        registry_match = _AI_PROVIDER_REGISTRY_RE.search(patched)
        if registry_match is None:
            raise ValueError("Could not find marimo AI provider registry block to patch")
        context_match = _AI_CONTEXT_REQUEST_RE.search(patched)
        if context_match is None:
            raise ValueError("Could not find marimo AI context request block to patch")
        datasource_aliases = _get_datasource_import_aliases(patched)
        _verify_ai_provider_roles(patched, registry_match, datasource_aliases)
        patched = patched.replace(
            registry_match.group(0),
            _render_ai_provider_registry_patch(
                registry_match, datasource_aliases, context_match.group("logger")
            ),
            1,
        )

    if _AI_AUTOCOMPLETE_PATCHED_RE.search(patched) is None:
        autocomplete_match = _AI_AUTOCOMPLETE_RE.search(patched)
        if autocomplete_match is None:
            raise ValueError("Could not find marimo AI autocomplete block to patch")
        autocomplete_replacement = (
            f'autocomplete:{autocomplete_match.group("autocomplete_fn")}'
            f'(async()=>{{await brEnsureHubResources();'
            f'let {autocomplete_match.group("items")}='
            f'{autocomplete_match.group("registry_fn")}'
            f'({autocomplete_match.group("store")}).getAllItems();'
            f'return {autocomplete_match.group("items")}.length===0?'
            f'{autocomplete_match.group("empty_items")}:'
            f'{autocomplete_match.group("items")}}},'
            f'{autocomplete_match.group("item")}=>{{'
            f'var {autocomplete_match.group("provider")};'
            f'return {autocomplete_match.group("item")}.type==='
            f'{autocomplete_match.group("empty_type")}?'
            f'{autocomplete_match.group("empty_completion")}:'
            f'(({autocomplete_match.group("provider")}='
            f'{autocomplete_match.group("registry_fn")}'
            f'({autocomplete_match.group("store")}).getProvider('
            f'{autocomplete_match.group("item")}.type))==null?void 0:'
            f'{autocomplete_match.group("provider")}.formatCompletion('
            f'{autocomplete_match.group("item")}))||{{}}}})'
        )
        patched = patched.replace(
            autocomplete_match.group(0), autocomplete_replacement, 1
        )

    if _AI_CONTEXT_REQUEST_PATCHED_RE.search(patched) is None:
        context_match = _AI_CONTEXT_REQUEST_RE.search(patched)
        if context_match is None:
            raise ValueError("Could not find marimo AI context request block to patch")
        context_replacement = (
            f'async function {context_match.group("function_name")}'
            f'({{input:{context_match.group("input")}}}){{'
            f'let {context_match.group("context")}="",'
            f'{context_match.group("attachments")}=[];'
            f'if({context_match.group("input")}.includes("@")){{'
            f'await brEnsureHubResources();'
            f'let {context_match.group("registry")}='
            f'{context_match.group("registry_fn")}({context_match.group("store")}),'
            f'{context_match.group("context_ids")}='
            f'{context_match.group("registry")}.parseAllContextIds('
            f'{context_match.group("input")});'
            f'{context_match.group("context")}='
            f'{context_match.group("registry")}.formatContextForAI('
            f'{context_match.group("context_ids")});'
            f'try{{{context_match.group("attachments")}=await '
            f'{context_match.group("registry")}.getAttachmentsForContext('
            f'{context_match.group("context_ids")}),'
            f'{context_match.group("logger")}.debug("Included attachments",'
            f'{context_match.group("attachments")}.length)}}'
            f'catch({context_match.group("error")}){{'
            f'{context_match.group("logger")}.error("Error getting attachments:",'
            f'{context_match.group("error")})}}}}'
            f'return{{body:{{includeOtherCode:'
            f'{context_match.group("include_other_code")}(""),'
            f'context:{{plainText:{context_match.group("context")},'
            f'schema:[],variables:[]}}}},'
            f'attachments:{context_match.group("attachments")}}}}}'
        )
        patched = patched.replace(context_match.group(0), context_replacement, 1)

    return patched


# useCellActions is the cells-store export aliased ``D`` (the AI "Add to Notebook"
# flow does ``{createNewCell}=D()``). Its react-compiler memo wrapper is
# ``<hook>=function(e){...,<impl>(a)}`` and ``<impl>(a)`` returns the actions
# object. Derive <hook> from the ``X as D`` export and <impl> from that wrapper so
# we publish the RIGHT object (several unrelated hooks share the generic
# ``n[1]=a),Y(a)}`` memo shape, so a generic anchor matches the wrong one).
_CELLS_D_EXPORT_RE = re.compile(r"([A-Za-z_$][\w$]*) as D[,}]")


def _cells_usecellactions_impl(source: str) -> str:
    export_match = _CELLS_D_EXPORT_RE.search(source)
    if export_match is None:
        raise ValueError("Could not find marimo useCellActions (D) export to patch")
    hook = export_match.group(1)
    wrapper = re.compile(re.escape(hook) + r"=function\(e\)\{.*?,([A-Za-z_$]+)\(a\)\}")
    wrapper_match = wrapper.search(source)
    if wrapper_match is None:
        raise ValueError("Could not find marimo useCellActions memo wrapper to patch")
    return wrapper_match.group(1)
# Lazy bridge the embedding hub page calls (same-origin) to append a cell through
# the browser's LIVE marimo session — the exact createNewCell(__end__) call the AI
# "Add to Notebook" flow uses (newCellId omitted; marimo mints it, like the
# cell.createBelow keymap).
_CELLS_BRIDGE_FN = (
    ";window.__brAppendCell=function(code){"
    "var a=window.__brCellActions;"
    'if(!a||typeof a.createNewCell!=="function")'
    'throw new Error("br:cell-actions-unavailable");'
    'return a.createNewCell({cellId:"__end__",code:String(code),before:false})};'
)


def patch_cells_store_source(source: str) -> str:
    """Expose live cell-append to the same-origin hub page for "Attach in notebook".

    A server-side POST to marimo's transaction API cannot target the live kernel
    session the browser owns, so Attach must run client-side like "Add to
    Notebook". ``createNewCell`` is only reachable via the ``useCellActions`` hook,
    so publish that hook's result to ``window.__brCellActions`` on every call
    (the notebook's cell editors render the hook continuously) and expose
    ``window.__brAppendCell(code)`` that the parent hub page invokes via the
    same-origin iframe ``contentWindow``.
    """

    if "__brAppendCell" in source:
        return source
    impl = _cells_usecellactions_impl(source)
    anchor = f",{impl}(a)}}"
    if source.count(anchor) != 1:
        raise ValueError(
            f"Ambiguous marimo useCellActions anchor {anchor!r} "
            f"(count={source.count(anchor)})"
        )
    publish = f",(window.__brCellActions={impl}(a))}}"
    patched = source.replace(anchor, publish, 1)
    return patched + _CELLS_BRIDGE_FN


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
    # NOTE: the session/config/panels session-id patches (patch_session_source,
    # patch_config_source, patch_panels_source) were RETIRED. They imposed the
    # studio session id (studio_xxx) onto marimo's frontend by widening the
    # session-id validator and threading setBrSessionId through the panels
    # bundle. That coupling was brittle: it matched exact minified tokens, and on
    # any build-hash drift the patches applied only partially -> setBrSessionId
    # ended up undefined -> the panels module threw during websocket bring-up ->
    # 0 cells rendered (the "blank notebook" bug). marimo now OWNS its session id
    # (stock validator, mints its own s_xxxxxx); the orchestrator DISCOVERS that
    # id via GET /api/sessions for "Attach in notebook". The patch_*_source
    # functions remain below as dead code for now and can be deleted in a
    # follow-up. Only resource/cell-editor/cells-bridge patches stay applied.
    patch_plan = (
        ("add-cell-with-ai-*.js", "No resources", patch_add_cell_with_ai_source),
        ("cell-editor-*.js", "update_cell", patch_cell_editor_source),
        ("cells-*.js", "createNewCell", patch_cells_store_source),
    )

    for asset_glob, marker, patcher in patch_plan:
        asset_path = find_asset(asset_glob, marimo_root, required_marker=marker)
        changed = patch_asset(asset_path, patcher)
        status = "patched" if changed else "already-patched"
        print(f"{status}: {asset_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

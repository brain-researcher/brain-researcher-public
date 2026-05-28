from brain_researcher.services.orchestrator.marimo_frontend_patch import (
    patch_add_cell_with_ai_source,
    patch_cell_editor_source,
    patch_config_source,
    patch_panels_source,
    patch_session_source,
)


def test_patch_cell_editor_source_injects_staged_remove_on_inline_fix_actions() -> None:
    source = (
        'import{A as tm,E as ai,O as nm,T as rm,a as ii,d as om,n as am,o as im,'
        'r as si,s as sm,x as lm}from"./add-cell-with-ai-3_AIzd22.js";'
        '[w,y]=yn(km),E=(0,F.useId)(),C=ef(),{initialPrompt:I,triggerImmediately:D,'
        'cellId:B}=t??{},x=B===e,S=ie(lm).get(e),W;(S==null?void 0:S.type)==="update_cell"&&'
        '(W=S.previousCode);let{completion:te'
        'L=()=>{s(N),ae("")},q=()=>{i(),ae("")},'
    )

    patched = patch_cell_editor_source(source)

    assert (
        "[cellEditorStagedMap,updateStagedCells]=yn(lm),E=(0,F.useId)(),C=ef(),"
        "{initialPrompt:I,triggerImmediately:D,cellId:B}=t??{},x=B===e,"
        "S=cellEditorStagedMap.get(e)"
        in patched
    )
    assert (
        'L=()=>{s(N),(S==null?void 0:S.type)==="update_cell"&&'
        'updateStagedCells(T=>{let j=new Map(T);return j.delete(e),j}),ae("")}'
        in patched
    )
    assert (
        'q=()=>{i(),(S==null?void 0:S.type)==="update_cell"&&'
        'updateStagedCells(T=>{let j=new Map(T);return j.delete(e),j}),ae("")}'
        in patched
    )
    assert "stagedActionsHook" not in patched


def test_patch_cell_editor_source_is_idempotent() -> None:
    source = (
        'import{A as tm,E as ai,O as nm,T as rm,a as ii,d as om,n as am,o as im,'
        'r as si,s as sm,x as lm}from"./add-cell-with-ai-3_AIzd22.js";'
        '[w,y]=yn(km),E=(0,F.useId)(),C=ef(),{initialPrompt:I,triggerImmediately:D,'
        'cellId:B}=t??{},x=B===e,S=ie(lm).get(e),W;(S==null?void 0:S.type)==="update_cell"&&'
        '(W=S.previousCode);let{completion:te'
        'L=()=>{s(N),ae("")},q=()=>{i(),ae("")},'
    )

    once = patch_cell_editor_source(source)
    twice = patch_cell_editor_source(once)

    assert twice == once


def test_patch_add_cell_with_ai_source_registers_br_hub_resources() -> None:
    source = (
        'function yt(t){let e=t.get(Ni),a=t.get(Pi),r=t.get(Ti);return new To().register(new '
        'Fu(a)).register(new zu(r,a)).register(new Lu(t)).register(new Mu(t)).register(new '
        'So(e.connectionsMap,a))}'
        'Pc=[{uri:"",name:"No resources",type:si,data:{}}],$c={info:"Variables, dataframes, and '
        'tables will appear here.",apply:()=>{}};function Lc(t){let{language:e,store:a,onAddFiles:r}'
        '=t;return[e.data.of({autocomplete:xc(async()=>{let s=yt(a).getAllItems();return '
        's.length===0?Pc:s},s=>{var n;return s.type===si?$c:((n=yt(a).getProvider(s.type))==null?'
        'void 0:n.formatCompletion(s))||{}})})]}'
        'async function Wu({input:t}){let e="",a=[];if(t.includes("@")){let r=yt(Gr),s='
        'r.parseAllContextIds(t);e=r.formatContextForAI(s);try{a=await r.getAttachmentsForContext'
        '(s),se.debug("Included attachments",a.length)}catch(n){se.error("Error getting '
        'attachments:",n)}}return{body:{includeOtherCode:rs(""),context:{plainText:e,schema:[],'
        'variables:[]}},attachments:a}}'
    )

    patched = patch_add_cell_with_ai_source(source)

    assert "function brEnsureHubResources()" in patched
    assert 'function brReadSessionId(t){try{let e=new URL(t,window.location.href).searchParams.get("session_id")||"";return e&&window.sessionStorage.setItem("brHubSessionId",e),e}catch{return""}}' in patched
    assert 'function brHubSessionId(){return brReadSessionId(window.location.href)||brReadSessionId(document.referrer)||window.sessionStorage.getItem("brHubSessionId")||""}' in patched
    assert 'fetch(`/api/hub/sessions/${encodeURIComponent(t)}/resources`' in patched
    assert '.register(new BrHubResourceProvider("tool","Tools",brHubSections.TOOL,St.HIGH))' in patched
    assert '.register(new BrHubResourceProvider("dataset","Datasets",brHubSections.DATASET,St.MEDIUM))' in patched
    assert '.register(new BrHubResourceProvider("workflow","Workflows",brHubSections.WORKFLOW,St.MEDIUM))' in patched
    assert '.register(new BrHubResourceProvider("kg","Knowledge Graph",brHubSections.KG,St.MEDIUM))' in patched
    assert 'parseContextIds(t){let e=RegExp(`${this.mentionPrefix}(${this.contextType}):\\\\/\\\\/([^\\\\s]+)`,"g")' in patched
    assert 'formatCompletion(t){let e=`@${t.uri}`,a=t.details||t.description||t.name;return{label:e,' in patched
    assert 'autocomplete:xc(async()=>{await brEnsureHubResources();let s=yt(a).getAllItems();return s.length===0?Pc:s}' in patched
    assert 'async function Wu({input:t}){let e="",a=[];if(t.includes("@")){await brEnsureHubResources();let r=yt(Gr),s=' in patched


def test_patch_session_source_exports_mutable_session_setter() -> None:
    source = (
        'function q(t){return t?/^s_[\\da-z]{6}$/.test(t):!1}'
        'var ut=(()=>{let t=new URL(window.location.href).searchParams.get(j.sessionId);'
        'return q(t)?(z(u=>{u.has(j.kiosk)||u.delete(j.sessionId)}),D.debug("Connecting '
        'to existing session",{sessionId:t}),t):(D.debug("Starting a new session",'
        '{sessionId:t}),K())})();function ft(){return ut}export{it as a,V as c,nt as i,'
        'N as l,q as n,ot as o,st as r,z as s,ft as t};'
    )

    patched = patch_session_source(source)

    assert 'function q(t){return t?/^(?:s_[\\da-z]{6}|studio_[A-Za-z0-9]+)$/.test(t):!1}' in patched
    assert 'window.sessionStorage.setItem("brHubSessionId",t)' in patched
    assert (
        'function setBrSessionId(t){ut=t||"",t?window.sessionStorage.setItem("brHubSessionId",t):'
        'window.sessionStorage.removeItem("brHubSessionId")}'
        in patched
    )
    assert "setBrSessionId as u" in patched


def test_patch_config_source_omits_empty_session_headers() -> None:
    source = (
        'headers(){let t={"Marimo-Session-Id":R(),"Marimo-Server-Token":'
        'this.config.serverToken??"","x-runtime-url":this.httpURL.toString()};return '
        'this.config.authToken&&(t.Authorization=`Bearer ${this.config.authToken}`),t}'
        'sessionHeaders(){return{"Marimo-Session-Id":R()}}'
    )

    patched = patch_config_source(source)

    assert 'let t=R(),e={"Marimo-Server-Token":this.config.serverToken??"",' in patched
    assert 't&&(e["Marimo-Session-Id"]=t)' in patched
    assert 'sessionHeaders(){let t=R();return t?{"Marimo-Session-Id":t}:{}}' in patched


def test_patch_panels_source_clears_rejected_session_and_restores_on_open() -> None:
    source = (
        'import{i as xt}from"./session-DdnWW30b.js";'
        'let H;A[30]!==E||A[31]!==n?(H=()=>E.getWsURL(n).toString(),A[30]=E,A[31]=n,'
        'A[32]=H):H=A[32];V=async()=>{t.current=!0,w({state:p.OPEN})}'
        'case"MARIMO_ALREADY_CONNECTED":w({state:p.CLOSED,code:L.ALREADY_RUNNING,reason:'
        '"another browser tab is already connected to the kernel",canTakeover:!0}),'
        'W.close();return;'
        'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":case"MARIMO_NO_SESSION_ID":'
        'case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":w({state:p.CLOSED,'
        'code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),W.close();return;'
        'case"MARIMO_MALFORMED_QUERY":w({state:p.CLOSED,code:L.MALFORMED_QUERY,reason:'
        '"the kernel did not recognize a request; please file a bug with marimo"});return;'
        'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){w({state:p.CLOSED,'
        'code:L.KERNEL_STARTUP_ERROR,reason:"Failed to start kernel sandbox"}),'
        'W.close();return}'
        'onError:h=>{v.warn("WebSocket error",h),w({state:p.CLOSED,'
        'code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),xA()}})'
    )

    patched = patch_panels_source(source)

    assert 'import{i as xt,u as setBrSessionId}from"./session-DdnWW30b.js";' in patched
    assert 'V=async()=>{setBrSessionId(n),t.current=!0,w({state:p.OPEN})}' in patched
    assert 'case"MARIMO_ALREADY_CONNECTED":setBrSessionId(""),w({state:p.CLOSED,' in patched
    assert (
        'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":case"MARIMO_NO_SESSION_ID":'
        'case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":setBrSessionId(""),w({state:p.CLOSED,'
        'code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),W.close();return;'
        in patched
    )
    assert 'case"MARIMO_MALFORMED_QUERY":setBrSessionId(""),w({state:p.CLOSED,' in patched
    assert (
        'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){setBrSessionId(""),w({state:p.CLOSED,'
        'code:L.KERNEL_STARTUP_ERROR,reason:"Failed to start kernel sandbox"}),'
        'W.close();return}'
        in patched
    )
    assert (
        'onError:h=>{if(!xt())return;setBrSessionId(""),v.warn("WebSocket error",h),'
        'w({state:p.CLOSED,code:L.KERNEL_DISCONNECTED,reason:"kernel not found"}),xA()}})'
        in patched
    )


def test_patch_panels_source_handles_fresh_install_bundle_shape() -> None:
    source = (
        'import{i as Ra}from"./session-DdnWW30b.js";'
        'let H;A[30]!==E||A[31]!==o?(H=()=>E.getWsURL(o).toString(),A[30]=E,A[31]=o,'
        'A[32]=H):H=A[32];let U;A[33]===w?U=A[34]:(U=async()=>{e.current=!0,'
        'w({state:p.OPEN})},A[33]=w,A[34]=U);'
        'let W=Bt({static:K,url:H,onOpen:U,waitToConnect:V,onMessage:q,onClose:h=>{'
        'switch(D.warn("WebSocket closed",h.code,h.reason),h.reason){'
        'case"MARIMO_ALREADY_CONNECTED":w({state:p.CLOSED,code:P.ALREADY_RUNNING,'
        'reason:"another browser tab is already connected to the kernel",'
        'canTakeover:!0}),W.close();return;'
        'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":'
        'case"MARIMO_NO_SESSION_ID":case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":'
        'w({state:p.CLOSED,code:P.KERNEL_DISCONNECTED,reason:"kernel not found"}),'
        'W.close();return;'
        'case"MARIMO_MALFORMED_QUERY":w({state:p.CLOSED,code:P.MALFORMED_QUERY,'
        'reason:"the kernel did not recognize a request; please file a bug with marimo"});'
        'return;default:if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){'
        'w({state:p.CLOSED,code:P.KERNEL_STARTUP_ERROR,'
        'reason:"Failed to start kernel sandbox"}),W.close();return}'
        'w({state:p.CONNECTING}),BA(h.code,h.reason)}},'
        'onError:h=>{D.warn("WebSocket error",h),w({state:p.CLOSED,'
        'code:P.KERNEL_DISCONNECTED,reason:"kernel not found"}),BA()}})'
    )

    patched = patch_panels_source(source)

    assert 'import{i as Ra,u as setBrSessionId}from"./session-DdnWW30b.js";' in patched
    assert 'U=async()=>{setBrSessionId(o),e.current=!0,w({state:p.OPEN})}' in patched
    assert 'case"MARIMO_ALREADY_CONNECTED":setBrSessionId(""),w({state:p.CLOSED,' in patched
    assert (
        'case"MARIMO_WRONG_KERNEL_ID":case"MARIMO_NO_FILE_KEY":case"MARIMO_NO_SESSION_ID":'
        'case"MARIMO_NO_SESSION":case"MARIMO_SHUTDOWN":setBrSessionId(""),'
        'w({state:p.CLOSED,code:P.KERNEL_DISCONNECTED,reason:"kernel not found"}),'
        'W.close();return;'
        in patched
    )
    assert 'case"MARIMO_MALFORMED_QUERY":setBrSessionId(""),w({state:p.CLOSED,' in patched
    assert (
        'if(h.reason==="MARIMO_KERNEL_STARTUP_ERROR"){setBrSessionId(""),'
        'w({state:p.CLOSED,code:P.KERNEL_STARTUP_ERROR,reason:"Failed to start kernel sandbox"}),'
        'W.close();return}'
        in patched
    )
    assert (
        'onError:h=>{if(!Ra())return;setBrSessionId(""),D.warn("WebSocket error",h),'
        'w({state:p.CLOSED,code:P.KERNEL_DISCONNECTED,reason:"kernel not found"}),BA()}})'
        in patched
    )

import gzip
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator.marimo_frontend_patch import (
    patch_add_cell_with_ai_source,
    patch_cell_editor_source,
    patch_cells_store_source,
    patch_config_source,
    patch_panels_source,
    patch_session_source,
)

# Real (unpatched) marimo 0.23.8 bundles, captured so the cell-editor and
# add-cell-with-ai patchers are exercised against the actual minified shapes they
# target (the patchers verify cross-bundle provider structure, so hand-written
# minified snippets are too brittle). Refresh these on a marimo version bump.
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "marimo_frontend"


def _load_bundle(name: str) -> str:
    return gzip.decompress((_FIXTURES / name).read_bytes()).decode("utf-8")


def test_patch_cells_store_source_exposes_br_append_cell() -> None:
    # Minified useCellActions memo-wrapper shape (impl name = rn) + a trailing export.
    source = (
        "y_=function(e){let n=(0,pc.c)(2),a;return n[0]===e?a=n[1]:"
        "(a=e===void 0?{}:e,n[0]=e,n[1]=a),rn(a)}export{y_ as D};"
    )
    patched = patch_cells_store_source(source)
    # Publishes the live actions on every hook call...
    assert "n[1]=a),(window.__brCellActions=rn(a))}" in patched
    # ...and exposes the same-origin bridge that appends a cell at the end.
    assert "window.__brAppendCell=function(code)" in patched
    assert 'cellId:"__end__"' in patched
    assert "createNewCell" in patched
    # Idempotent.
    assert patch_cells_store_source(patched) == patched


def test_patch_cells_store_source_fails_loud_on_unknown_shape() -> None:
    with pytest.raises(ValueError):
        patch_cells_store_source("export{y_ as D};// no useCellActions memo wrapper")


def test_patch_cell_editor_source_against_real_bundle() -> None:
    source = _load_bundle("cell_editor_0_23_8.js.gz")
    patched = patch_cell_editor_source(source)
    # Staged-cell map binding + delete-on-accept/decline are injected.
    assert patched != source
    assert "cellEditorStagedMap" in patched or "updateStagedCells" in patched
    assert "stagedActionsHook" not in patched
    # Idempotent.
    assert patch_cell_editor_source(patched) == patched


def test_patch_cell_editor_source_fails_loud_on_unknown_shape() -> None:
    with pytest.raises(ValueError):
        patch_cell_editor_source("// no staged-state block here")


def test_patch_add_cell_with_ai_source_against_real_bundle() -> None:
    source = _load_bundle("add_cell_with_ai_0_23_8.js.gz")
    patched = patch_add_cell_with_ai_source(source)
    assert patched != source
    # BR hub-resource providers (tool/dataset/workflow/KG) registered into AI @-context.
    assert "function brEnsureHubResources()" in patched
    assert 'new BrHubResourceProvider("tool"' in patched
    assert 'new BrHubResourceProvider("kg"' in patched
    assert "await brEnsureHubResources()" in patched
    # Idempotent.
    assert patch_add_cell_with_ai_source(patched) == patched


def test_patch_add_cell_with_ai_source_fails_loud_on_unknown_shape() -> None:
    with pytest.raises(ValueError):
        patch_add_cell_with_ai_source("// no datasource import or provider registry")


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

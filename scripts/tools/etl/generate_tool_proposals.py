import yaml, pathlib, ast, csv
from collections import defaultdict

root = pathlib.Path('.').resolve()
cap_files = [root/'configs/catalog/capabilities.yaml', root/'configs/catalog/capabilities.generated.yaml', root/'configs/catalog/capabilities.gemini_cli.yaml']

# load family ops mapping
def load_family_ops():
    fam_path = root/'configs/catalog/tool_families.yaml'
    fam_map = defaultdict(list)
    if not fam_path.exists():
        return fam_map
    data = yaml.safe_load(fam_path.read_text()) or []
    if isinstance(data, list):
        for fam in data:
            if isinstance(fam, dict):
                for op, tid in (fam.get('ops') or {}).items():
                    fam_map[tid].append(op)
    return fam_map

family_ops = load_family_ops()

# utility to get docstring first line from module/function/class
def extract_doc_firstline(py_path: pathlib.Path, func_name: str):
    try:
        src = py_path.read_text()
    except Exception:
        return ''
    try:
        tree = ast.parse(src)
    except Exception:
        return ''
    # module docstring
    mod_doc = ast.get_docstring(tree) or ''
    # search for function/class
    found = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == func_name:
            found = ast.get_docstring(node) or ''
            break
    doc = found or mod_doc
    if not doc:
        return ''
    first = doc.strip().split('\n')[0].strip()
    return first

# heuristic intent mapping by package/id keywords
intent_keywords = {
    'ica': 'fsl_melodic_ica',
    'dual_regression': 'fsl_dual_regression',
    'registration': 'registration',
    'flirt': 'registration',
    'fnirt': 'registration',
    'bet': 'brain_extraction',
    'preprocess': 'fmri_preprocessing',
    'xcpd': 'xcpd_postprocessing',
    'hyperalignment': 'hyperalignment_fmri',
    'perfusion': 'asl_perfusion',
    'gnn': 'gnn_connectivity_analysis',
    'multimodal': 'multimodal_integration',
    'rag': 'rag_search',
    'llm': 'llm_chat',
    'gemini': 'llm_chat',
    'google_search': 'web_search',
}

def guess_intents(tool_id: str, package: str):
    intents = []
    low = tool_id.lower()
    for k,v in intent_keywords.items():
        if k in low:
            intents.append(v)
    if package in ('gemini','google','ai','rag'):
        intents.append('llm_chat')
    return list(dict.fromkeys(intents))

# load capabilities

proposal_desc = []
proposal_intents = []

for cap_path in cap_files:
    data = yaml.safe_load(cap_path.read_text())
    tools = []
    if isinstance(data, dict):
        tools = data.get('tools') or []
    elif isinstance(data, list):
        tools = data
    for t in tools:
        if not isinstance(t, dict):
            continue
        tid = t.get('id')
        pkg = t.get('package')
        src = cap_path.name
        # description proposal if placeholder
        desc = t.get('description') or ''
        placeholder = ' tool' in desc and len(desc.split())<=4
        if placeholder:
            py = t.get('python') or {}
            module = py.get('module')
            func = py.get('function')
            docline = ''
            if module and func:
                py_path = root/('brain_researcher'+'/'+module.split('brain_researcher.')[-1].replace('.', '/')+'.py')
                docline = extract_doc_firstline(py_path, func)
            proposed = docline if docline else f"{pkg or 'tool'} {tid}"
            proposal_desc.append({'tool_id': tid, 'source': src, 'current_desc': desc, 'proposed_desc': proposed, 'module': module, 'function': func})
        # intents proposal
        cur_intents = t.get('intents') or []
        if not cur_intents:
            fam_ops = family_ops.get(tid)
            proposed = fam_ops if fam_ops else guess_intents(tid, pkg or '')
            if proposed:
                proposal_intents.append({'tool_id': tid, 'source': src, 'current_intents': ';'.join(cur_intents), 'proposed_intents': ';'.join(proposed)})

# write CSVs
out_dir = root/'docs'
out_dir.mkdir(exist_ok=True)
with open(out_dir/'tool_descriptions_proposed.csv','w',newline='') as f:
    writer=csv.DictWriter(f, fieldnames=['tool_id','source','current_desc','proposed_desc','module','function'])
    writer.writeheader(); writer.writerows(proposal_desc)
with open(out_dir/'tool_intents_proposed.csv','w',newline='') as f:
    writer=csv.DictWriter(f, fieldnames=['tool_id','source','current_intents','proposed_intents'])
    writer.writeheader(); writer.writerows(proposal_intents)

print(f"description proposals: {len(proposal_desc)}; intent proposals: {len(proposal_intents)}")

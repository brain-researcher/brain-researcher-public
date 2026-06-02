import os

directories_to_scan = ['src', 'tests', 'apps', 'scripts']
files_updated = 0

for d in directories_to_scan:
    if os.path.exists(d):
        for root, dirs, files in os.walk(d):
            if '__pycache__' in root or '.pytest_cache' in root or 'node_modules' in root:
                continue
            for fname in files:
                if fname.endswith('.py') or fname.endswith('.sh') or fname.endswith('.md'):
                    fp = os.path.join(root, fname)
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()

                    new_content = content
                    new_content = new_content.replace('from brain_researcher.services.br_kg.etl.', 'from brain_researcher.services.br_kg.etl.')
                    new_content = new_content.replace('import brain_researcher.services.br_kg.etl.', 'import brain_researcher.services.br_kg.etl.')
                    new_content = new_content.replace('from brain_researcher.services.br_kg.etl ', 'from brain_researcher.services.br_kg.etl ')
                    new_content = new_content.replace('import etl\n', 'import brain_researcher.services.br_kg.etl\n')

                    new_content = new_content.replace('"brain_researcher/services/br_kg/etl/', '"brain_researcher/services/br_kg/etl/')
                    new_content = new_content.replace("'brain_researcher/services/br_kg/etl/", "'brain_researcher/services/br_kg/etl/")
                    new_content = new_content.replace('python -m brain_researcher.services.br_kg.etl', 'python -m brain_researcher.services.br_kg.etl')
                    new_content = new_content.replace('python src/brain_researcher/services/br_kg/etl/', 'python src/brain_researcher/services/br_kg/etl/')

                    if new_content != content:
                        with open(fp, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f'Updated {fp}')
                        files_updated += 1

print(f'Total files updated: {files_updated}')

#!/usr/bin/env python3
"""Analyze Cognitive Atlas tasks and match them to existing ONVOC anchors."""

import json
import re
import yaml
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict

def slugify(name: str) -> str:
    """Convert task name to slug."""
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s/]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')

def normalize_text(text: str) -> str:
    """Normalize text for matching."""
    return text.lower().strip()

def build_anchor_lookups(anchors: List[Dict]) -> Tuple[Dict, Dict, Dict, Dict]:
    """Build lookup structures for anchors."""
    anchor_slugs: Dict[str, Set[str]] = defaultdict(set)
    anchor_keywords: Dict[str, List[str]] = defaultdict(list)
    anchor_regex: Dict[str, List[re.Pattern]] = defaultdict(list)
    anchor_labels: Dict[str, str] = {}
    
    for anchor in anchors:
        uri = anchor.get('onvoc_uri', '')
        if not uri:
            continue
        
        anchor_labels[uri] = anchor.get('label', uri)
        
        # Collect slugs
        for task in anchor.get('seed_tasks', []):
            if 'slug' in task:
                anchor_slugs[uri].add(slugify(task['slug']))
        matchers = anchor.get('matchers', {})
        for slug in matchers.get('slugs', []):
            anchor_slugs[uri].add(slugify(slug))
        
        # Collect keywords
        keywords = []
        keywords.extend(matchers.get('keywords_any', []))
        keywords.extend(matchers.get('keywords_all', []))
        anchor_keywords[uri] = [normalize_text(kw) for kw in keywords]
        
        # Collect regex
        for pattern_str in matchers.get('regex', []):
            try:
                anchor_regex[uri].append(re.compile(pattern_str, re.IGNORECASE))
            except:
                pass
    
    return anchor_slugs, anchor_keywords, anchor_regex, anchor_labels

def match_task(
    task_name: str,
    task_alias: str,
    task_def: str,
    anchor_slugs: Dict[str, Set[str]],
    anchor_keywords: Dict[str, List[str]],
    anchor_regex: Dict[str, List[re.Pattern]],
) -> List[Tuple[str, float, str]]:
    """Match a task to anchors, returning list of (uri, score, reason)."""
    task_slug = slugify(task_name)
    task_text = f'{task_name} {task_alias} {task_def}'.lower()
    
    matches = []
    
    # Check slug matches
    for uri, slugs in anchor_slugs.items():
        if task_slug in slugs:
            matches.append((uri, 0.9, f'slug_exact:{task_slug}'))
        # Also check if task slug contains any anchor slug
        for slug in slugs:
            if slug in task_slug or task_slug in slug:
                if slug != task_slug:  # Already counted exact match
                    matches.append((uri, 0.7, f'slug_partial:{slug}'))
    
    # Check keyword matches
    for uri, keywords in anchor_keywords.items():
        matched_kws = []
        for kw in keywords:
            if kw in task_text:
                matched_kws.append(kw)
        if matched_kws:
            score = min(0.25 * len(matched_kws), 0.5)  # Cap at 0.5
            matches.append((uri, score, f'keywords:{",".join(matched_kws[:3])}'))
    
    # Check regex matches
    for uri, patterns in anchor_regex.items():
        for pattern in patterns:
            if pattern.search(task_text):
                matches.append((uri, 0.25, f'regex:{pattern.pattern[:30]}'))
                break  # Only count once per anchor
    
    return matches

def main():
    # Load tasks
    task_file = Path('data/niclip/data/cognitive_atlas/task_snapshot-02-19-25.json')
    with open(task_file) as f:
        tasks = json.load(f)
    
    print(f'Loaded {len(tasks)} tasks')
    
    # Load mapping rules
    with open('configs/mapping_rules.yaml') as f:
        manual_rules = yaml.safe_load(f)
    
    with open('configs/mapping_rules.generated.yaml') as f:
        generated_rules = yaml.safe_load(f)
    
    # Combine anchors
    all_anchors = []
    if 'anchors' in manual_rules:
        all_anchors.extend(manual_rules['anchors'])
    if 'anchors' in generated_rules:
        all_anchors.extend(generated_rules['anchors'])
    
    print(f'Total anchors: {len(all_anchors)}')
    
    # Build lookups
    anchor_slugs, anchor_keywords, anchor_regex, anchor_labels = build_anchor_lookups(all_anchors)
    
    print(f'Anchors with slugs: {sum(1 for s in anchor_slugs.values() if s)}')
    print(f'Anchors with keywords: {sum(1 for k in anchor_keywords.values() if k)}')
    print(f'Anchors with regex: {sum(1 for r in anchor_regex.values() if r)}')
    
    # Match all tasks
    matched_tasks = []
    unmapped_tasks = []
    match_details = defaultdict(list)
    
    for task in tasks:
        name = task.get('name', '')
        alias = task.get('alias', '')
        definition = task.get('definition_text', '')
        
        matches = match_task(name, alias, definition, anchor_slugs, anchor_keywords, anchor_regex)
        
        if matches:
            # Get best match
            best_match = max(matches, key=lambda x: x[1])
            matched_tasks.append({
                'name': name,
                'alias': alias,
                'slug': slugify(name),
                'matched_uri': best_match[0],
                'matched_label': anchor_labels.get(best_match[0], ''),
                'score': best_match[1],
                'reason': best_match[2],
                'all_matches': matches
            })
            match_details[best_match[0]].append(name)
        else:
            unmapped_tasks.append({
                'name': name,
                'alias': alias,
                'slug': slugify(name),
                'definition': definition[:200] if definition else ''
            })
    
    print(f'\n=== RESULTS ===')
    print(f'Matched tasks: {len(matched_tasks)} ({100*len(matched_tasks)/len(tasks):.1f}%)')
    print(f'Unmapped tasks: {len(unmapped_tasks)} ({100*len(unmapped_tasks)/len(tasks):.1f}%)')
    
    # Show top matched anchors
    print(f'\n=== TOP MATCHED ANCHORS ===')
    top_anchors = sorted(match_details.items(), key=lambda x: len(x[1]), reverse=True)[:20]
    for uri, task_names in top_anchors:
        label = anchor_labels.get(uri, uri)
        print(f'{label} ({uri}): {len(task_names)} tasks')
        if len(task_names) <= 5:
            for tn in task_names:
                print(f'  - {tn}')
    
    # Analyze unmapped tasks
    print(f'\n=== UNMAPPED TASK ANALYSIS ===')
    
    # Group by common patterns
    unmapped_by_pattern = defaultdict(list)
    for task in unmapped_tasks:
        name_lower = task['name'].lower()
        slug = task['slug']
        
        # Categorize
        if any(term in name_lower for term in ['questionnaire', 'scale', 'inventory', 'index', 'checklist']):
            unmapped_by_pattern['questionnaires'].append(task)
        elif any(term in name_lower for term in ['test', 'battery', 'assessment']):
            unmapped_by_pattern['tests_batteries'].append(task)
        elif any(term in name_lower for term in ['memory', 'recall', 'recognition', 'encoding']):
            unmapped_by_pattern['memory'].append(task)
        elif any(term in name_lower for term in ['decision', 'choice', 'reward', 'reinforcement']):
            unmapped_by_pattern['decision_reward'].append(task)
        elif any(term in name_lower for term in ['emotion', 'affect', 'fear', 'anger', 'happy']):
            unmapped_by_pattern['emotion'].append(task)
        elif any(term in name_lower for term in ['pain', 'nociception', 'thermal', 'heat']):
            unmapped_by_pattern['pain_nociception'].append(task)
        elif any(term in name_lower for term in ['language', 'reading', 'naming', 'speech']):
            unmapped_by_pattern['language'].append(task)
        elif any(term in name_lower for term in ['attention', 'vigilance', 'alertness']):
            unmapped_by_pattern['attention'].append(task)
        elif any(term in name_lower for term in ['working memory', 'wm', 'n-back']):
            unmapped_by_pattern['working_memory'].append(task)
        else:
            unmapped_by_pattern['other'].append(task)
    
    for pattern, task_list in sorted(unmapped_by_pattern.items(), key=lambda x: len(x[1]), reverse=True):
        print(f'\n{pattern}: {len(task_list)} tasks')
        for task in task_list[:10]:  # Show first 10
            print(f'  - {task["name"]} ({task["slug"]})')
        if len(task_list) > 10:
            print(f'  ... and {len(task_list) - 10} more')
    
    # Save results
    output_dir = Path('outputs')
    output_dir.mkdir(exist_ok=True)
    
    # Save matched tasks
    with open(output_dir / 'ca_tasks_matched.json', 'w') as f:
        json.dump(matched_tasks, f, indent=2)
    
    # Save unmapped tasks
    with open(output_dir / 'ca_tasks_unmapped.json', 'w') as f:
        json.dump(unmapped_tasks, f, indent=2)
    
    print(f'\n=== SAVED RESULTS ===')
    print(f'Matched tasks: outputs/ca_tasks_matched.json')
    print(f'Unmapped tasks: outputs/ca_tasks_unmapped.json')

if __name__ == '__main__':
    main()


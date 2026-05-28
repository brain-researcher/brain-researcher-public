# Task Mapping Extension Guide

This guide explains how to extend the taxonomy-to-ONVOC mapping system to improve Cognitive Atlas task matching coverage.

## Current Status

- **Total CA tasks**: 965
- **Mapped CA tasks**: 126
- **Coverage**: 13.1%
- **Conflicts**: 0

The remaining 839 tasks fall into clusters that haven't been seeded yet (questionnaires, neuropsych batteries, perceptual paradigms, etc.).

## Files to Edit

### 1. Primary File: `configs/taxonomy/crosswalks/families__to__onvoc.v1.yaml`

**This is the main file you edit.** It maps taxonomy families (`tf_*`) to ONVOC anchors.

**Structure for each entry:**
```yaml
  - family_id: tf_<family_name>
    onvoc_uri: ONVOC_XXXXXXXX   # Choose appropriate ONVOC node
    seeds:
      slugs:
        - task-slug-1
        - task-slug-2
        # Pull these from configs/taxonomy/families/<family>.yaml
    keywords_any:
      - "keyword 1"
      - "keyword 2"
      # Terms you expect in CA task names/descriptions
    regex:
      - "\\bpattern\\b"  # Optional: regex patterns
    exclude:  # Optional: exclude patterns
      keywords:
        - "false positive term"
    accept:  # Optional: override defaults
      min_score: 0.85
      min_margin: 0.10
```

**Example from existing file:**
```yaml
  - family_id: tf_detection_discrimination
    onvoc_uri: ONVOC_0000434   # Perception
    seeds:
      slugs:
        - yes-no-detection
        - two-afc-detection
        - orientation-discrimination
        - contrast-sensitivity
        - motion-coherence
        - temporal-order-judgment
        - simultaneity-judgment
        - flicker-fusion
        - binocular-rivalry
        - auditory-masking
    keywords_any:
      - "detection"
      - "discrimination"
      - "threshold"
      - "psychometric"
      - "temporal order"
      - "simultaneity"
      - "flicker fusion"
      - "masking"
      - "crowding"
      - "motion coherence"
      - "orientation discrimination"
      - "auditory masking"
```

### 2. Reference Files: `configs/taxonomy/families/*.yaml`

**These files contain the detailed family definitions.** Use them to:
- Extract canonical task slugs (from `paradigms[].name`, `aliases`, or `examples`)
- Understand what keywords are relevant
- See what tasks belong to each family

**Available families:**
- `tf_attention_selective.yaml`
- `tf_conflict_inhibition.yaml`
- `tf_detection_discrimination.yaml`
- `tf_interoception_challenge.yaml`
- `tf_language_semantic.yaml`
- `tf_localizers_baseline.yaml`
- `tf_ltm_declarative.yaml`
- `tf_motor_action.yaml`
- `tf_neurofeedback.yaml`
- `tf_preference_affective.yaml`
- `tf_rule_category_learning.yaml`
- `tf_social_cognition.yaml`
- `tf_spatial_navigation.yaml`
- `tf_task_switching.yaml`
- `tf_timing_order.yaml`
- `tf_value_based_decision.yaml`
- `tf_working_memory.yaml`

**How to extract slugs from family files:**
1. Look for `examples:` field (e.g., `examples: [heartbeat_counting, heartbeat_discrimination_synchrony]`)
2. Look for `paradigms[].name` and `paradigms[].aliases` fields
3. Convert to kebab-case slugs (e.g., "Heartbeat Counting" → `heartbeat-counting`)

### 3. Manual Overrides: `configs/mapping_rules.yaml` (Optional)

**Only edit if you need to:**
- Override generated anchor settings
- Add extra slugs beyond what the crosswalk supplies
- Tweak weights or thresholds for specific anchors

**Note:** Manual entries with the same `onvoc_uri` will supersede generated ones.

### 4. Generated File: `configs/mapping_rules.generated.yaml` (DO NOT EDIT)

**This file is auto-generated.** After editing the crosswalk, regenerate it by running:
```bash
python scripts/tools/etl/sync_taxonomy_to_mapping.py compile
```

## Workflow

### Step 1: Identify Missing Families

Look at unmapped CA tasks to identify which families need crosswalk entries. Examples from the terminal output:
- **Questionnaires/Clinical scales**: `barratt-impulsiveness-scale`, `brief-psychiatric-rating-scale`, `anxiety-sensitivity-index-3`
- **Neuropsych batteries**: Various standardized tests
- **Perceptual paradigms**: `bistability`, `bistable-percept-paradigm`, `auditory-masking`
- **Task switching**: `2nd-order-rule-acquisition`, `ANT task`, `AX-DPX`

### Step 2: Choose Appropriate ONVOC URI

Look up ONVOC nodes in `configs/mapping_rules.yaml` or the ONVOC tree. Common mappings:
- Questionnaires → `ONVOC_0000519` (Health) or `ONVOC_0000429` (Emotion)
- Neuropsych batteries → `ONVOC_0000520` (Intelligence) or `ONVOC_0000433` (Memory)
- Perceptual tasks → `ONVOC_0000434` (Perception)
- Task switching → `ONVOC_0000468` (Cognitive Flexibility)
- Category learning → `ONVOC_0000432` (Learning)

### Step 3: Extract Slugs from Family Files

For each family you want to add, read the corresponding file in `configs/taxonomy/families/`:

```bash
# Example: Check what tasks are in tf_rule_category_learning
cat configs/taxonomy/families/tf_rule_category_learning.yaml | grep -A 5 "name:\|aliases:\|examples:"
```

Extract slugs from:
- `examples:` lists
- `paradigms[].name` fields
- `paradigms[].aliases` arrays

Convert to kebab-case (lowercase with hyphens).

### Step 4: Add Entry to Crosswalk

Add a new entry to `configs/taxonomy/crosswalks/families__to__onvoc.v1.yaml`:

```yaml
  - family_id: tf_rule_category_learning
    onvoc_uri: ONVOC_0000432   # Learning
    seeds:
      slugs:
        - rule-based-learning
        - shj-types
        - prototype-learning
        - exemplar-learning
        # ... more slugs from family file
    keywords_any:
      - "category learning"
      - "rule learning"
      - "prototype"
      - "exemplar"
      - "probabilistic learning"
      - "information integration"
      - "shj"
    regex:
      - "\\b(shj|shepard[- ]hovland[- ]jenkins)\\b"
```

**Tips:**
- Keep keywords precise to avoid false positives
- Use `keywords_any` for flexible matching
- Use `regex` for pattern-based matching (e.g., acronyms)
- Add `exclude.keywords` if needed to filter false positives

### Step 5: Regenerate Mapping Rules

After adding entries, regenerate the generated file:

```bash
python scripts/tools/etl/sync_taxonomy_to_mapping.py compile
```

This reads the crosswalk and creates `configs/mapping_rules.generated.yaml`.

### Step 6: Re-run Mapper

Run the mapper with both rule files:

```bash
python scripts/tools/etl/onvoc_mapper.py propose \
  --config configs/mapping_rules.yaml \
  --generated-rules configs/mapping_rules.generated.yaml \
  --settings configs/mapping_settings.yaml \
  --sources cognitive_atlas
```

### Step 7: Check Coverage

Query the database to check new coverage:

```cypher
// Total CA tasks
MATCH (t:Task {source: "cognitive_atlas"})
RETURN count(t) as total

// Mapped tasks
MATCH (t:Task {source: "cognitive_atlas"})-[:MAPS_TO]->(f:Family)
RETURN count(DISTINCT t) as mapped

// Coverage percentage
MATCH (t:Task {source: "cognitive_atlas"})
OPTIONAL MATCH (t)-[:MAPS_TO]->(f:Family)
WITH count(t) as total, count(f) as mapped
RETURN total, mapped, round(100.0 * mapped / total, 1) as coverage_pct
```

## Example: Adding a New Family

Let's say you want to add `tf_interoception_challenge`:

1. **Read the family file:**
   ```bash
   cat configs/taxonomy/families/tf_interoception_challenge.yaml | head -20
   ```

2. **Extract slugs from `examples:` field:**
   - `heartbeat_counting` → `heartbeat-counting`
   - `heartbeat_discrimination_synchrony` → `heartbeat-discrimination-synchrony`
   - `heartbeat_tracking` → `heartbeat-tracking`
   - etc.

3. **Choose ONVOC URI:** Look for "Interoception" or related concept. If not found, use `ONVOC_0000500` (Interoception) or `ONVOC_0000434` (Perception).

4. **Add to crosswalk:**
   ```yaml
   - family_id: tf_interoception_challenge
     onvoc_uri: ONVOC_0000500   # Interoception
     seeds:
       slugs:
         - heartbeat-counting
         - heartbeat-discrimination-synchrony
         - heartbeat-tracking
         - respiratory-load-detection
         - hypercapnia-co2
         - breath-hold
         - cold-pressor
         - thermal-pain
     keywords_any:
       - "interoception"
       - "interoceptive"
       - "heartbeat"
       - "cardiac"
       - "breath hold"
       - "cold pressor"
       - "hypercapnia"
       - "respiratory load"
     regex:
       - "\\bheartbeat (counting|discrimination|tracking)\\b"
   ```

5. **Regenerate and test:**
   ```bash
   python scripts/tools/etl/sync_taxonomy_to_mapping.py compile
   python scripts/tools/etl/onvoc_mapper.py propose --config configs/mapping_rules.yaml --generated-rules configs/mapping_rules.generated.yaml --settings configs/mapping_settings.yaml --sources cognitive_atlas
   ```

## Priority Families to Add

Based on unmapped CA tasks, prioritize:

1. **Questionnaires/Clinical scales** → Map to `ONVOC_0000519` (Health) or `ONVOC_0000429` (Emotion)
   - Examples: `barratt-impulsiveness-scale`, `brief-psychiatric-rating-scale`, `anxiety-sensitivity-index-3`

2. **Neuropsych batteries** → Map to `ONVOC_0000520` (Intelligence) or `ONVOC_0000433` (Memory)
   - Various standardized test batteries

3. **Task switching variants** → Extend `tf_task_switching` or create new entries
   - Examples: `2nd-order-rule-acquisition`, `ANT task`, `AX-DPX`

4. **Perceptual paradigms** → Extend `tf_detection_discrimination` or create new entries
   - Examples: `bistability`, `bistable-percept-paradigm`, `auditory-masking`

5. **Category learning** → Add `tf_rule_category_learning` entry

6. **Interoception** → Add `tf_interoception_challenge` entry

## Tips

- **Start small**: Add 1-2 families at a time, regenerate, test, and check coverage
- **Be precise**: Use specific keywords to avoid false positives
- **Use excludes**: If an anchor matches too broadly, add `exclude.keywords`
- **Check conflicts**: After each batch, verify no conflicts were introduced
- **Iterate**: Every 20-30 new seeds typically pulls in another few dozen CA tasks

## Files Summary

| File | Purpose | Edit? |
|------|---------|-------|
| `configs/taxonomy/crosswalks/families__to__onvoc.v1.yaml` | Main crosswalk mapping | ✅ **YES** |
| `configs/taxonomy/families/*.yaml` | Family definitions (reference) | 📖 **READ ONLY** |
| `configs/mapping_rules.yaml` | Manual overrides | ⚠️ **OPTIONAL** |
| `configs/mapping_rules.generated.yaml` | Auto-generated rules | ❌ **NO** |
| `scripts/tools/etl/sync_taxonomy_to_mapping.py` | Sync script | ❌ **NO** |

## Next Steps

1. Pick a high-priority family (e.g., questionnaires or neuropsych batteries)
2. Read the corresponding family file to extract slugs
3. Add entry to crosswalk with appropriate ONVOC URI
4. Regenerate mapping rules
5. Re-run mapper and check coverage
6. Repeat for next family

import { describe, expect, it } from 'vitest'

import {
  computeMappedConceptsFromSubgraph,
  inferExplorerNodeKind,
  isCognitiveAtlasConcept,
  isConceptMappingEdgeType,
  isContrastStatmapEdgeType,
  isDatasetStatmapEdgeType,
  passesConceptMappingConfidence,
} from '@/components/knowledge-graph/node-kinds'

describe('node-kinds', () => {
  it('classifies task-like labels used by BR-KG explorer', () => {
    expect(
      inferExplorerNodeKind({
        id: 'task_1',
        labels: ['TaskAnalysis'],
      }),
    ).toBe('task')
  })

  it('classifies ONVOC concept variants consistently', () => {
    expect(
      inferExplorerNodeKind({
        id: 'ONVOC_0000462',
        labels: ['OnvocClass'],
      }),
    ).toBe('concept')
  })

  it('classifies tool and study labels used in explorer nodes', () => {
    expect(
      inferExplorerNodeKind({
        id: 'tool:fsl:flirt',
        labels: ['ToolVersion'],
      }),
    ).toBe('tool')
    expect(
      inferExplorerNodeKind({
        id: 'study:pmid:123',
        labels: ['Study'],
      }),
    ).toBe('study')
  })

  it('detects cognitive atlas concepts by source and id prefix', () => {
    expect(
      isCognitiveAtlasConcept({
        id: 'trm_4a3fd79d096be',
        labels: ['Concept'],
        meta: {},
      }),
    ).toBe(true)
    expect(
      isCognitiveAtlasConcept({
        id: 'x1',
        labels: ['Concept'],
        meta: { source: 'cognitive_atlas' },
      }),
    ).toBe(true)
  })

  it('keeps dataset/statmap and contrast/statmap edge compatibility sets', () => {
    expect(isDatasetStatmapEdgeType('GENERATED_FROM')).toBe(true)
    expect(isDatasetStatmapEdgeType('HAS_RESOURCE')).toBe(true)
    expect(isContrastStatmapEdgeType('MEASURES_CONTRAST')).toBe(true)
    expect(isContrastStatmapEdgeType('DERIVED_FROM')).toBe(true)
  })

  it('keeps concept mapping edge allowlist constrained to MAPS_TO/SAME_AS', () => {
    expect(isConceptMappingEdgeType('MAPS_TO')).toBe(true)
    expect(isConceptMappingEdgeType('SAME_AS')).toBe(true)
    expect(isConceptMappingEdgeType('MEASURES')).toBe(false)
    expect(isConceptMappingEdgeType('RELATED_TO')).toBe(false)
  })

  it('applies concept mapping confidence threshold only when confidence is present', () => {
    expect(passesConceptMappingConfidence(undefined, 'MAPS_TO')).toBe(true)
    expect(passesConceptMappingConfidence('0.85', 'MAPS_TO')).toBe(true)
    expect(passesConceptMappingConfidence(0.84, 'MAPS_TO')).toBe(false)
    expect(passesConceptMappingConfidence(0.9, 'SAME_AS')).toBe(true)
    expect(passesConceptMappingConfidence(0.89, 'SAME_AS')).toBe(false)
  })

  it('derives mapped concepts from direct selected-concept mapping edges only', () => {
    const mapped = computeMappedConceptsFromSubgraph(
      'onvoc_memory',
      [
        { id: 'onvoc_memory', label: 'Memory', kind: 'concept', source: 'onvoc' },
        { id: 'x_custom', label: 'Custom Concept', kind: 'concept', source: 'custom' },
        { id: 'same_as_neighbor', label: 'SameAs Concept', kind: 'concept', source: 'cognitive_atlas' },
        { id: 'trm_12345', label: 'CA Concept', kind: 'concept', source: 'custom' },
        { id: 'low_conf', label: 'Low Confidence Concept', kind: 'concept', source: 'custom' },
        { id: 'trm_prefixed', label: 'CA Prefix', kind: 'concept', source: 'cognitive_atlas' },
        { id: 'task_nback', label: 'N-Back', kind: 'task' },
      ],
      [
        { source: 'onvoc_memory', target: 'x_custom', type: 'MAPS_TO', confidence: 0.9 },
        { source: 'onvoc_memory', target: 'same_as_neighbor', type: 'SAME_AS', confidence: 0.91 },
        { source: 'onvoc_memory', target: 'trm_12345', type: 'MAPS_TO', confidence: 0.9 },
        { source: 'onvoc_memory', target: 'task_nback', type: 'MAPS_TO', confidence: 0.99 },
        { source: 'onvoc_memory', target: 'trm_prefixed', type: 'RELATED_TO', confidence: 0.99 },
        { source: 'onvoc_memory', target: 'low_conf', type: 'MAPS_TO', confidence: 0.84 },
        { source: 'other_source', target: 'x_custom', type: 'MAPS_TO', confidence: 0.99 },
      ],
    )

    expect(mapped).toEqual([
      { id: 'trm_12345', label: 'CA Concept', source: 'custom' },
      { id: 'same_as_neighbor', label: 'SameAs Concept', source: 'cognitive_atlas' },
    ])
  })

  it('updates mapped concepts when selected concept changes', () => {
    const nodes = [
      { id: 'concept_alpha', label: 'Alpha', kind: 'concept', source: 'onvoc' },
      { id: 'trm_beta', label: 'Beta', kind: 'concept', source: 'custom' },
      { id: 'trm_gamma', label: 'Gamma', kind: 'concept', source: 'custom' },
      { id: 'trm_delta', label: 'Delta', kind: 'concept', source: 'cognitive_atlas' },
    ]
    const edges = [
      { source: 'concept_alpha', target: 'trm_beta', type: 'MAPS_TO', confidence: 0.9 },
      { source: 'concept_alpha', target: 'trm_delta', type: 'SAME_AS', confidence: 0.95 },
      { source: 'trm_beta', target: 'trm_gamma', type: 'MAPS_TO', confidence: 0.9 },
    ]

    expect(computeMappedConceptsFromSubgraph('concept_alpha', nodes, edges)).toEqual([
      { id: 'trm_beta', label: 'Beta', source: 'custom' },
      { id: 'trm_delta', label: 'Delta', source: 'cognitive_atlas' },
    ])

    expect(computeMappedConceptsFromSubgraph('trm_beta', nodes, edges)).toEqual([
      { id: 'trm_gamma', label: 'Gamma', source: 'custom' },
    ])
  })

  it('returns no mapped concepts after clearing selection', () => {
    const mapped = computeMappedConceptsFromSubgraph(
      '',
      [
        { id: 'concept_a', label: 'A', kind: 'concept' },
        { id: 'concept_b', label: 'B', kind: 'concept' },
      ],
      [{ source: 'concept_a', target: 'concept_b', type: 'MAPS_TO', confidence: 0.9 }],
    )

    expect(mapped).toEqual([])
  })

  it('does not show mappings for non-mapping edge types', () => {
    const mapped = computeMappedConceptsFromSubgraph(
      'concept_a',
      [
        { id: 'concept_a', label: 'A', kind: 'concept' },
        { id: 'concept_b', label: 'B', kind: 'concept' },
      ],
      [{ source: 'concept_a', target: 'concept_b', type: 'RELATED_TO', confidence: 0.99 }],
    )

    expect(mapped).toEqual([])
  })
})

import { isOntologyDirectTaskConceptEdge } from '../node-kinds'

describe('node-kinds ontology direct edge guardrail', () => {
  it('marks Task <-> Concept IN_ONVOC edges as ontology-direct', () => {
    expect(
      isOntologyDirectTaskConceptEdge({
        edgeType: 'IN_ONVOC',
        source: { id: 'task:1', labels: ['Task'] },
        target: { id: 'ONVOC_0000153', labels: ['Concept', 'OnvocClass'] },
      }),
    ).toBe(true)

    expect(
      isOntologyDirectTaskConceptEdge({
        edgeType: 'in_onvoc',
        source: { id: 'ONVOC_0000153', labels: ['Concept'] },
        target: { id: 'task:1', labels: ['Task'] },
      }),
    ).toBe(true)
  })

  it('does not mark non Task<->Concept edges as ontology-direct', () => {
    expect(
      isOntologyDirectTaskConceptEdge({
        edgeType: 'IN_ONVOC',
        source: { id: 'task:1', labels: ['Task'] },
        target: { id: 'dataset:1', labels: ['Dataset'] },
      }),
    ).toBe(false)

    expect(
      isOntologyDirectTaskConceptEdge({
        edgeType: 'MAPS_TO',
        source: { id: 'task:1', labels: ['Task'] },
        target: { id: 'ONVOC_0000153', labels: ['Concept'] },
      }),
    ).toBe(false)
  })
})

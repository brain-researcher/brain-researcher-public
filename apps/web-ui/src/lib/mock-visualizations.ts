import { KnowledgeGraph, BrainMapData } from '@/types/visualization'

const MOCK_GRAPH_TIMESTAMP = new Date('2024-01-01T00:00:00Z')

export function generateMockKnowledgeGraph(runId: string): KnowledgeGraph {
  return {
    nodes: [
      {
        id: 'dataset-motor',
        type: 'dataset',
        label: 'Motor Task Dataset',
        description: '20 subjects, fMRI motor task',
        metadata: { subjects: 20, sessions: 1, size: '125MB' },
        position: { x: 100, y: 300 }
      },
      {
        id: 'preprocess',
        type: 'analysis',
        label: 'Preprocessing',
        description: 'Motion correction, smoothing',
        metadata: { tool: 'nilearn', version: '0.10.1' },
        position: { x: 300, y: 200 }
      },
      {
        id: 'glm-analysis',
        type: 'analysis',
        label: 'GLM Analysis',
        description: 'First-level statistical modeling',
        metadata: { tool: 'nilearn', hrf_model: 'spm' },
        position: { x: 500, y: 300 }
      },
      {
        id: 'zmap-result',
        type: 'result',
        label: 'Z-statistic Map',
        description: 'Motor > Rest contrast',
        metadata: { threshold: 0.001, clusters: 15 },
        position: { x: 700, y: 200 }
      },
      {
        id: 'nilearn-tool',
        type: 'tool',
        label: 'Nilearn',
        description: 'Machine learning for neuroimaging',
        metadata: { version: '0.10.1', language: 'Python' },
        position: { x: 400, y: 100 }
      },
      {
        id: 'spm-method',
        type: 'citation',
        label: 'SPM Method',
        description: 'Statistical Parametric Mapping',
        metadata: { doi: '10.1002/hbm.460020402', year: 1994 },
        position: { x: 600, y: 100 }
      },
      {
        id: 'smoothing-param',
        type: 'parameter',
        label: 'FWHM=6mm',
        description: 'Spatial smoothing parameter',
        metadata: { value: 6, unit: 'mm' },
        position: { x: 200, y: 100 }
      }
    ],
    edges: [
      {
        id: 'dataset-preprocess',
        source: 'dataset-motor',
        target: 'preprocess',
        type: 'uses',
        label: 'input'
      },
      {
        id: 'preprocess-glm',
        source: 'preprocess',
        target: 'glm-analysis',
        type: 'generates',
        label: 'preprocessed data'
      },
      {
        id: 'glm-result',
        source: 'glm-analysis',
        target: 'zmap-result',
        type: 'generates',
        label: 'statistical map'
      },
      {
        id: 'tool-preprocess',
        source: 'nilearn-tool',
        target: 'preprocess',
        type: 'uses'
      },
      {
        id: 'tool-glm',
        source: 'nilearn-tool',
        target: 'glm-analysis',
        type: 'uses'
      },
      {
        id: 'method-glm',
        source: 'spm-method',
        target: 'glm-analysis',
        type: 'cites'
      },
      {
        id: 'param-preprocess',
        source: 'smoothing-param',
        target: 'preprocess',
        type: 'configures'
      }
    ],
    metadata: {
      title: 'Motor Task GLM Analysis',
      description: 'Complete workflow from raw data to statistical results',
      timestamp: MOCK_GRAPH_TIMESTAMP
    }
  }
}

export function generateMockBrainMaps(runId: string): BrainMapData[] {
  return [
    {
      id: 'motor-zmap',
      name: 'Motor > Rest Z-map',
      type: 'statistical',
      imageUrl: 'https://images.pexels.com/photos/8386440/pexels-photo-8386440.jpeg?auto=compress&cs=tinysrgb&w=800',
      niftiUrl: '/api/artifacts/motor_zmap.nii.gz',
      threshold: 0.001,
      colormap: 'hot',
      coordinates: { x: -42, y: -24, z: 54 },
      peaks: [
        { x: -42, y: -24, z: 54, value: 8.32, region: 'Left Primary Motor Cortex' },
        { x: 38, y: -28, z: 58, value: 7.89, region: 'Right Primary Motor Cortex' },
        { x: -38, y: -52, z: 48, value: 6.45, region: 'Left Superior Parietal Lobule' },
        { x: 34, y: -48, z: 52, value: 6.12, region: 'Right Superior Parietal Lobule' },
        { x: 0, y: -8, z: 54, value: 5.78, region: 'Supplementary Motor Area' }
      ],
      metadata: {
        analysis: 'GLM',
        contrast: 'Motor > Rest',
        subjects: 20,
        corrected: 'FWE',
        software: 'nilearn'
      }
    },
    {
      id: 'motor-connectivity',
      name: 'Motor Network Connectivity',
      type: 'connectivity',
      imageUrl: 'https://images.pexels.com/photos/8386434/pexels-photo-8386434.jpeg?auto=compress&cs=tinysrgb&w=800',
      threshold: 0.3,
      colormap: 'viridis',
      coordinates: { x: 0, y: -24, z: 54 },
      peaks: [
        { x: -42, y: -24, z: 54, value: 0.85, region: 'Left M1' },
        { x: 38, y: -28, z: 58, value: 0.82, region: 'Right M1' },
        { x: 0, y: -8, z: 54, value: 0.78, region: 'SMA' }
      ],
      metadata: {
        analysis: 'Seed-based connectivity',
        seed: 'Left Primary Motor Cortex',
        subjects: 20,
        software: 'nilearn'
      }
    }
  ]
}

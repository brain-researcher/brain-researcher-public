// Neuroimaging Tools Library
// Defines all available neuroimaging analysis tools with their metadata

export interface Tool {
  id: string
  name: string
  description: string
  category: string
  inputs: string[]
  outputs: string[]
  parameters?: Record<string, any>
  documentation?: string
  version?: string
}

export const toolCategories = {
  'fmri-analysis': {
    name: 'fMRI Analysis',
    description: 'Functional MRI processing and analysis tools',
    icon: 'Brain',
  },
  'connectivity': {
    name: 'Connectivity',
    description: 'Brain connectivity and network analysis',
    icon: 'Activity',
  },
  'preprocessing': {
    name: 'Preprocessing',
    description: 'Image preprocessing and normalization',
    icon: 'Database',
  },
  'meg-eeg': {
    name: 'MEG/EEG',
    description: 'Magnetoencephalography and electroencephalography analysis',
    icon: 'Zap',
  },
  'statistics': {
    name: 'Statistics',
    description: 'Statistical analysis and multiple comparison correction',
    icon: 'BarChart3',
  },
  'deep-learning': {
    name: 'Deep Learning',
    description: 'Machine learning and deep learning models',
    icon: 'Cpu',
  },
  'diffusion': {
    name: 'Diffusion',
    description: 'Diffusion MRI and tractography',
    icon: 'GitBranch',
  },
  'visualization': {
    name: 'Visualization',
    description: 'Brain visualization and reporting',
    icon: 'FileText',
  },
}

export const neuroimagingTools: Tool[] = [
  // fMRI Analysis Tools
  {
    id: 'fmriprep',
    name: 'fMRIPrep',
    description: 'Robust preprocessing pipeline for fMRI data',
    category: 'fmri-analysis',
    inputs: ['raw_data', 'anatomical'],
    outputs: ['preprocessed', 'confounds', 'reports'],
    version: '23.1.0',
  },
  {
    id: 'fsl_feat',
    name: 'FSL FEAT',
    description: 'FMRI Expert Analysis Tool for GLM analysis',
    category: 'fmri-analysis',
    inputs: ['preprocessed'],
    outputs: ['stats', 'contrasts', 'activation_maps'],
    version: '6.0.5',
  },
  {
    id: 'spm_glm',
    name: 'SPM GLM',
    description: 'Statistical Parametric Mapping GLM',
    category: 'fmri-analysis',
    inputs: ['preprocessed'],
    outputs: ['stats', 'spm_maps'],
    version: 'SPM12',
  },
  {
    id: 'nilearn_glm',
    name: 'Nilearn GLM',
    description: 'Python-based GLM analysis',
    category: 'fmri-analysis',
    inputs: ['preprocessed'],
    outputs: ['stats', 'z_maps', 'effect_maps'],
    version: '0.10.1',
  },
  {
    id: 'fitlins',
    name: 'FitLins',
    description: 'Fitting Linear Models to BIDS Datasets',
    category: 'fmri-analysis',
    inputs: ['preprocessed', 'events'],
    outputs: ['stats', 'contrasts'],
    version: '0.11.0',
  },

  // Connectivity Tools
  {
    id: 'conn',
    name: 'CONN Toolbox',
    description: 'Functional connectivity analysis toolbox',
    category: 'connectivity',
    inputs: ['preprocessed'],
    outputs: ['connectivity_matrix', 'roi_timeseries'],
    version: '21a',
  },
  {
    id: 'nilearn_connectivity',
    name: 'Nilearn Connectivity',
    description: 'Connectivity matrix computation',
    category: 'connectivity',
    inputs: ['timeseries', 'atlas'],
    outputs: ['matrix', 'correlation_matrix'],
    version: '0.10.1',
  },
  {
    id: 'graph_theory',
    name: 'Graph Theory Analysis',
    description: 'Network metrics and graph analysis',
    category: 'connectivity',
    inputs: ['matrix'],
    outputs: ['metrics', 'centrality', 'modularity'],
  },
  {
    id: 'dynamic_connectivity',
    name: 'Dynamic Connectivity',
    description: 'Time-varying connectivity analysis',
    category: 'connectivity',
    inputs: ['timeseries'],
    outputs: ['dynamic_matrix', 'states'],
  },
  {
    id: 'gnn_connectivity',
    name: 'GNN Connectivity',
    description: 'Graph Neural Networks for brain networks',
    category: 'connectivity',
    inputs: ['matrix', 'features'],
    outputs: ['predictions', 'embeddings'],
  },

  // Preprocessing Tools
  {
    id: 'fsl_bet',
    name: 'FSL BET',
    description: 'Brain Extraction Tool',
    category: 'preprocessing',
    inputs: ['anatomical'],
    outputs: ['brain_mask', 'skull_stripped'],
    version: '6.0.5',
  },
  {
    id: 'fsl_flirt',
    name: 'FSL FLIRT',
    description: 'Linear image registration',
    category: 'preprocessing',
    inputs: ['image', 'reference'],
    outputs: ['registered', 'transformation_matrix'],
    version: '6.0.5',
  },
  {
    id: 'fsl_fnirt',
    name: 'FSL FNIRT',
    description: 'Non-linear image registration',
    category: 'preprocessing',
    inputs: ['image', 'reference'],
    outputs: ['warped', 'warp_field'],
    version: '6.0.5',
  },
  {
    id: 'ants',
    name: 'ANTs',
    description: 'Advanced Normalization Tools',
    category: 'preprocessing',
    inputs: ['image', 'template'],
    outputs: ['normalized', 'transforms'],
    version: '2.4.0',
  },
  {
    id: 'freesurfer',
    name: 'FreeSurfer',
    description: 'Cortical surface reconstruction',
    category: 'preprocessing',
    inputs: ['anatomical'],
    outputs: ['surfaces', 'parcellation', 'thickness'],
    version: '7.3.2',
  },
  {
    id: 'xcpd',
    name: 'XCP-D',
    description: 'Post-processing and denoising pipeline',
    category: 'preprocessing',
    inputs: ['preprocessed', 'confounds'],
    outputs: ['cleaned', 'qc_reports'],
    version: '0.5.0',
  },

  // MEG/EEG Tools
  {
    id: 'mne_preprocessing',
    name: 'MNE Preprocessing',
    description: 'MEG/EEG preprocessing pipeline',
    category: 'meg-eeg',
    inputs: ['raw_meg'],
    outputs: ['preprocessed_meg', 'bad_channels'],
    version: '1.4.0',
  },
  {
    id: 'mne_ica',
    name: 'MNE ICA',
    description: 'Independent Component Analysis',
    category: 'meg-eeg',
    inputs: ['preprocessed_meg'],
    outputs: ['components', 'cleaned_data'],
    version: '1.4.0',
  },
  {
    id: 'mne_source',
    name: 'MNE Source Localization',
    description: 'Source reconstruction and localization',
    category: 'meg-eeg',
    inputs: ['preprocessed_meg', 'forward_model'],
    outputs: ['source_estimates', 'stc'],
    version: '1.4.0',
  },
  {
    id: 'mne_timefreq',
    name: 'MNE Time-Frequency',
    description: 'Time-frequency analysis',
    category: 'meg-eeg',
    inputs: ['preprocessed_meg'],
    outputs: ['tfr', 'power_spectrum'],
    version: '1.4.0',
  },
  {
    id: 'mne_connectivity',
    name: 'MNE Connectivity',
    description: 'MEG/EEG connectivity analysis',
    category: 'meg-eeg',
    inputs: ['preprocessed_meg'],
    outputs: ['connectivity', 'phase_coupling'],
    version: '0.5.0',
  },
  {
    id: 'fooof',
    name: 'FOOOF',
    description: 'Fitting Oscillations & One Over F',
    category: 'meg-eeg',
    inputs: ['power_spectrum'],
    outputs: ['parameters', 'aperiodic', 'peaks'],
    version: '1.0.0',
  },
  {
    id: 'autoreject',
    name: 'Autoreject',
    description: 'Automated artifact rejection',
    category: 'meg-eeg',
    inputs: ['epochs'],
    outputs: ['clean_epochs', 'reject_log'],
    version: '0.4.0',
  },

  // Statistical Tools
  {
    id: 'fsl_palm',
    name: 'FSL PALM',
    description: 'Permutation Analysis of Linear Models',
    category: 'statistics',
    inputs: ['stats', 'design_matrix'],
    outputs: ['corrected_stats', 'p_values'],
    version: 'alpha116',
  },
  {
    id: 'fsl_fix',
    name: 'FSL FIX',
    description: 'FMRIB ICA-based X-noiseifier',
    category: 'statistics',
    inputs: ['ica_components'],
    outputs: ['cleaned', 'noise_components'],
    version: '1.06.15',
  },
  {
    id: 'multiple_comparison',
    name: 'Multiple Comparison Correction',
    description: 'FDR, FWE, and Bonferroni correction',
    category: 'statistics',
    inputs: ['uncorrected_stats'],
    outputs: ['corrected_stats', 'threshold'],
  },
  {
    id: 'mixed_effects',
    name: 'Mixed Effects Models',
    description: 'Group-level mixed effects analysis',
    category: 'statistics',
    inputs: ['first_level_stats'],
    outputs: ['group_stats', 'random_effects'],
  },
  {
    id: 'bayesian_analysis',
    name: 'Bayesian Analysis',
    description: 'Bayesian statistical inference',
    category: 'statistics',
    inputs: ['data', 'priors'],
    outputs: ['posterior', 'bayes_factors'],
  },
  {
    id: 'permutation_testing',
    name: 'Permutation Testing',
    description: 'Non-parametric permutation tests',
    category: 'statistics',
    inputs: ['data', 'labels'],
    outputs: ['p_values', 'null_distribution'],
  },
  {
    id: 'statsmodels_glm',
    name: 'Statsmodels GLM',
    description: 'Generalized Linear Models',
    category: 'statistics',
    inputs: ['data', 'design'],
    outputs: ['coefficients', 'residuals'],
    version: '0.14.0',
  },

  // Deep Learning Tools
  {
    id: 'dl_pytorch',
    name: 'PyTorch Models',
    description: '3D CNNs, VAEs, RNNs for neuroimaging',
    category: 'deep-learning',
    inputs: ['data', 'labels'],
    outputs: ['predictions', 'model_weights'],
    version: '2.0.0',
  },
  {
    id: 'nilearn_decoding',
    name: 'Nilearn Decoding',
    description: 'Machine learning decoding and classification',
    category: 'deep-learning',
    inputs: ['features', 'labels'],
    outputs: ['predictions', 'scores', 'coefficients'],
    version: '0.10.1',
  },
  {
    id: 'mvpa',
    name: 'MVPA',
    description: 'Multi-Voxel Pattern Analysis',
    category: 'deep-learning',
    inputs: ['data', 'labels'],
    outputs: ['patterns', 'accuracy_maps'],
  },
  {
    id: 'searchlight',
    name: 'Searchlight Analysis',
    description: 'Local pattern information mapping',
    category: 'deep-learning',
    inputs: ['data', 'labels'],
    outputs: ['searchlight_maps', 'accuracy'],
  },
  {
    id: 'encoding_models',
    name: 'Encoding Models',
    description: 'Predictive encoding models',
    category: 'deep-learning',
    inputs: ['stimuli', 'responses'],
    outputs: ['model', 'predictions', 'r2_maps'],
  },
  {
    id: 'rsa_toolbox',
    name: 'RSA Toolbox',
    description: 'Representational Similarity Analysis',
    category: 'deep-learning',
    inputs: ['patterns'],
    outputs: ['rdm', 'similarity_matrix'],
  },
  {
    id: 'temporal_decoding',
    name: 'Temporal Decoding',
    description: 'Time-resolved decoding analysis',
    category: 'deep-learning',
    inputs: ['timeseries', 'labels'],
    outputs: ['temporal_accuracy', 'confusion_matrix'],
  },
  {
    id: 'feature_selection',
    name: 'Feature Selection',
    description: 'Feature selection and dimensionality reduction',
    category: 'deep-learning',
    inputs: ['features'],
    outputs: ['selected_features', 'importance_scores'],
  },

  // Diffusion Tools
  {
    id: 'qsiprep',
    name: 'QSIPrep',
    description: 'Preprocessing and reconstruction of diffusion MRI',
    category: 'diffusion',
    inputs: ['dwi', 'bvecs', 'bvals'],
    outputs: ['preprocessed_dwi', 'qc_report'],
    version: '0.18.0',
  },
  {
    id: 'fsl_bedpostx',
    name: 'FSL BEDPOSTX',
    description: 'Bayesian Estimation of Diffusion Parameters',
    category: 'diffusion',
    inputs: ['dwi'],
    outputs: ['fiber_orientations', 'uncertainty_maps'],
    version: '6.0.5',
  },
  {
    id: 'mrtrix',
    name: 'MRtrix3',
    description: 'Advanced diffusion MRI processing',
    category: 'diffusion',
    inputs: ['dwi'],
    outputs: ['tracks', 'fod', 'connectome'],
    version: '3.0.4',
  },
  {
    id: 'dipy',
    name: 'DIPY',
    description: 'Diffusion Imaging in Python',
    category: 'diffusion',
    inputs: ['dwi'],
    outputs: ['tensors', 'fa_maps', 'streamlines'],
    version: '1.7.0',
  },

  // Visualization Tools
  {
    id: 'nilearn_plotting',
    name: 'Nilearn Plotting',
    description: 'Statistical maps and brain visualization',
    category: 'visualization',
    inputs: ['stats', 'atlas'],
    outputs: ['figures', 'html_reports'],
    version: '0.10.1',
  },
  {
    id: 'surface_plotting',
    name: 'Surface Plotting',
    description: 'Cortical surface visualization',
    category: 'visualization',
    inputs: ['surface_data', 'mesh'],
    outputs: ['surface_figures', 'interactive_plots'],
  },
  {
    id: 'glass_brain',
    name: 'Glass Brain',
    description: '3D glass brain visualization',
    category: 'visualization',
    inputs: ['coordinates', 'activation_maps'],
    outputs: ['glass_brain_figure'],
  },
  {
    id: 'report_generator',
    name: 'Report Generator',
    description: 'Automated analysis reports',
    category: 'visualization',
    inputs: ['results', 'qc_metrics'],
    outputs: ['html_report', 'pdf_report'],
  },

  // Additional Analysis Tools
  {
    id: 'fsl_melodic',
    name: 'FSL MELODIC',
    description: 'Model-free fMRI analysis using ICA',
    category: 'fmri-analysis',
    inputs: ['preprocessed'],
    outputs: ['ica_components', 'time_courses', 'spatial_maps'],
    version: '6.0.5',
  },
  {
    id: 'spm_dcm',
    name: 'SPM DCM',
    description: 'Dynamic Causal Modeling',
    category: 'connectivity',
    inputs: ['timeseries', 'model_specification'],
    outputs: ['dcm_results', 'effective_connectivity'],
    version: 'SPM12',
  },
  {
    id: 'nipype',
    name: 'Nipype',
    description: 'Neuroimaging pipeline framework',
    category: 'preprocessing',
    inputs: ['workflow_spec'],
    outputs: ['pipeline_results'],
    version: '1.8.6',
  },
  {
    id: 'realtime_fmri',
    name: 'Real-time fMRI',
    description: 'Real-time neurofeedback analysis',
    category: 'fmri-analysis',
    inputs: ['streaming_data'],
    outputs: ['feedback_signal', 'online_stats'],
  },
  {
    id: 'multimodal_integration',
    name: 'Multimodal Integration',
    description: 'Integration of multiple imaging modalities',
    category: 'deep-learning',
    inputs: ['fmri', 'meg', 'structural'],
    outputs: ['integrated_features', 'fusion_maps'],
  },
  {
    id: 'statistical_inference',
    name: 'Statistical Inference',
    description: 'Advanced statistical inference methods',
    category: 'statistics',
    inputs: ['data', 'hypothesis'],
    outputs: ['test_statistics', 'confidence_intervals'],
  },
]

// Helper function to get tools by category
export function getToolsByCategory(category: string): Tool[] {
  return neuroimagingTools.filter(tool => tool.category === category)
}

// Helper function to search tools
export function searchTools(query: string): Tool[] {
  const lowerQuery = query.toLowerCase()
  return neuroimagingTools.filter(tool =>
    tool.name.toLowerCase().includes(lowerQuery) ||
    tool.description.toLowerCase().includes(lowerQuery) ||
    tool.id.toLowerCase().includes(lowerQuery)
  )
}

// Helper function to get tool by ID
export function getToolById(id: string): Tool | undefined {
  return neuroimagingTools.find(tool => tool.id === id)
}

// Helper function to validate tool connections
export function canConnect(sourceTool: Tool, targetTool: Tool): boolean {
  // Check if any output of source matches any input of target
  return sourceTool.outputs.some(output =>
    targetTool.inputs.some(input => {
      // Simple matching logic - can be made more sophisticated
      return output === input || 
             (output.includes('preprocessed') && input.includes('preprocessed')) ||
             (output.includes('stats') && input.includes('stats')) ||
             (output.includes('matrix') && input.includes('matrix'))
    })
  )
}

// Export tool count for display
export const TOTAL_TOOLS_COUNT = neuroimagingTools.length
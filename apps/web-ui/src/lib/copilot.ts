import { ParameterSuggestion, MethodRecommendation, CopilotContext } from '@/types/copilot'
import { Dataset } from '@/types/dataset'

export class CopilotEngine {
  generateParameterSuggestions(dataset?: Dataset, analysisType?: string): ParameterSuggestion[] {
    const suggestions: ParameterSuggestion[] = []

    if (dataset) {
      // TR-based suggestions
      if (dataset.tr) {
        if (dataset.tr <= 1.0) {
          suggestions.push({
            id: 'tr_fast',
            name: 'High-pass filter',
            value: '0.01',
            description: 'High-pass filter cutoff (Hz)',
            category: 'preprocessing',
            reasoning: `Fast TR (${dataset.tr}s) allows higher cutoff to remove low-frequency noise`,
            confidence: 0.9,
            source: 'best_practice',
            citation: 'Lindquist et al., 2019'
          })
        } else {
          suggestions.push({
            id: 'tr_slow',
            name: 'High-pass filter',
            value: '0.008',
            description: 'High-pass filter cutoff (Hz)',
            category: 'preprocessing',
            reasoning: `Standard TR (${dataset.tr}s) suggests conservative high-pass filtering`,
            confidence: 0.8,
            source: 'best_practice'
          })
        }
      }

      // Field strength based suggestions
      if (dataset.fieldStrength === '3T') {
        suggestions.push({
          id: 'smoothing_3t',
          name: 'Smoothing FWHM',
          value: '6mm',
          description: 'Spatial smoothing kernel size',
          category: 'preprocessing',
          reasoning: '3T data typically benefits from 6mm smoothing for group analysis',
          confidence: 0.85,
          source: 'literature',
          citation: 'Mikl et al., 2008'
        })
      }

      // Subject count based suggestions
      if (dataset.nSubjects < 30) {
        suggestions.push({
          id: 'small_sample_threshold',
          name: 'Statistical threshold',
          value: '0.001',
          description: 'Uncorrected p-value threshold',
          category: 'statistics',
          reasoning: `Small sample size (n=${dataset.nSubjects}) may require more liberal threshold`,
          confidence: 0.7,
          source: 'best_practice'
        })
      } else if (dataset.nSubjects > 100) {
        suggestions.push({
          id: 'large_sample_threshold',
          name: 'Statistical threshold',
          value: '0.05',
          description: 'FWE-corrected p-value',
          category: 'statistics',
          reasoning: `Large sample size (n=${dataset.nSubjects}) enables strict correction`,
          confidence: 0.9,
          source: 'best_practice'
        })
      }

      // Task-specific suggestions
      if (dataset.tasks?.includes('motor')) {
        suggestions.push({
          id: 'motor_contrast',
          name: 'Contrast',
          value: 'motor > rest',
          description: 'Motor activation vs rest',
          category: 'analysis',
          reasoning: 'Standard contrast for motor task analysis',
          confidence: 0.95,
          source: 'best_practice'
        })
      }

      if (dataset.tasks?.includes('rest')) {
        suggestions.push({
          id: 'bandpass_filter',
          name: 'Bandpass filter',
          value: '0.01-0.1 Hz',
          description: 'Frequency band for resting-state analysis',
          category: 'preprocessing',
          reasoning: 'Standard frequency band for resting-state connectivity',
          confidence: 0.9,
          source: 'literature',
          citation: 'Biswal et al., 1995'
        })
      }
    }

    // General best practice suggestions
    suggestions.push(
      {
        id: 'slice_timing',
        name: 'Slice timing correction',
        value: 'true',
        description: 'Correct for slice acquisition timing',
        category: 'preprocessing',
        reasoning: 'Standard preprocessing step for accurate timing',
        confidence: 0.8,
        source: 'best_practice'
      },
      {
        id: 'motion_correction',
        name: 'Motion correction',
        value: 'true',
        description: 'Correct for head motion',
        category: 'preprocessing',
        reasoning: 'Essential for reducing motion artifacts',
        confidence: 0.95,
        source: 'best_practice'
      },
      {
        id: 'template',
        name: 'Template',
        value: 'MNI152',
        description: 'Normalization template',
        category: 'preprocessing',
        reasoning: 'Standard template for group analysis',
        confidence: 0.9,
        source: 'best_practice'
      }
    )

    return suggestions
  }

  generateMethodRecommendations(dataset?: Dataset, analysisType?: string): MethodRecommendation[] {
    const recommendations: MethodRecommendation[] = []

    if (dataset?.tasks?.includes('motor')) {
      recommendations.push({
        id: 'glm_motor',
        name: 'General Linear Model',
        description: 'First-level GLM analysis for task-based activation',
        category: 'first_level',
        suitability: 0.95,
        reasoning: 'GLM is the gold standard for task-based fMRI analysis',
        parameters: [
          {
            id: 'hrf_model',
            name: 'HRF model',
            value: 'spm',
            description: 'Hemodynamic response function model',
            category: 'analysis',
            reasoning: 'SPM canonical HRF works well for motor tasks',
            confidence: 0.9,
            source: 'best_practice'
          }
        ],
      })
    }

    if (dataset?.tasks?.includes('rest')) {
      recommendations.push({
        id: 'seed_connectivity',
        name: 'Seed-based Connectivity',
        description: 'Analyze connectivity from predefined seed regions',
        category: 'connectivity',
        suitability: 0.85,
        reasoning: 'Good starting point for resting-state connectivity analysis',
        parameters: [
          {
            id: 'seed_region',
            name: 'Seed region',
            value: 'PCC',
            description: 'Seed region for connectivity analysis',
            category: 'analysis',
            reasoning: 'PCC is a key node in the default mode network',
            confidence: 0.8,
            source: 'literature'
          }
        ],
      })
    }

    if (dataset && dataset.nSubjects > 50) {
      recommendations.push({
        id: 'group_ica',
        name: 'Independent Component Analysis',
        description: 'Data-driven decomposition into independent networks',
        category: 'connectivity',
        suitability: 0.8,
        reasoning: 'Large sample size enables reliable ICA decomposition',
        parameters: [
          {
            id: 'n_components',
            name: 'Number of components',
            value: '20',
            description: 'Number of independent components to extract',
            category: 'analysis',
            reasoning: '20 components captures major brain networks',
            confidence: 0.7,
            source: 'literature'
          }
        ],
      })
    }

    // General preprocessing recommendation
    recommendations.push({
      id: 'preprocessing_pipeline',
      name: 'Standard Preprocessing',
      description: 'Complete preprocessing pipeline with motion correction, normalization, and smoothing',
      category: 'preprocessing',
      suitability: 0.9,
      reasoning: 'Essential first step for most fMRI analyses',
      parameters: [
        {
          id: 'pipeline',
          name: 'Pipeline',
          value: 'fMRIPrep',
          description: 'Preprocessing pipeline',
          category: 'preprocessing',
          reasoning: 'fMRIPrep provides robust, standardized preprocessing',
          confidence: 0.95,
          source: 'best_practice'
        }
      ],
    })

    return recommendations.sort((a, b) => b.suitability - a.suitability)
  }

  async generateCopilotResponse(userMessage: string, context: CopilotContext): Promise<string> {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 1000))

    const lowerMessage = userMessage.toLowerCase()

    if (lowerMessage.includes('parameter') || lowerMessage.includes('suggest')) {
      return "I've analyzed your dataset and current analysis context. Here are my parameter suggestions based on your data characteristics and neuroimaging best practices. Each suggestion includes the reasoning behind the recommendation."
    }

    if (lowerMessage.includes('threshold') || lowerMessage.includes('p-value')) {
      return "For statistical thresholding, I recommend considering your sample size and analysis goals. With larger samples (n>100), you can use stricter FWE correction (p<0.05). For smaller samples or exploratory analyses, uncorrected p<0.001 with cluster extent thresholding is common."
    }

    if (lowerMessage.includes('smoothing') || lowerMessage.includes('fwhm')) {
      return "Spatial smoothing depends on your analysis goals. For group analysis, 6-8mm FWHM is typical. For within-subject or high-resolution analysis, use less smoothing (2-4mm). Consider your voxel size - smoothing kernel should be 2-3x voxel size."
    }

    if (lowerMessage.includes('glm') || lowerMessage.includes('model')) {
      return "For GLM analysis, I recommend starting with the SPM canonical HRF for most tasks. Consider adding temporal and dispersion derivatives for better model fit. Make sure to include motion parameters and other confounds in your design matrix."
    }

    if (lowerMessage.includes('connectivity') || lowerMessage.includes('network')) {
      return "For connectivity analysis, seed-based approaches are interpretable and hypothesis-driven. ICA is great for exploratory network discovery. Remember to bandpass filter (0.01-0.1 Hz) and regress out global signal for resting-state data."
    }

    // Default helpful response
    return "I'm here to help with your neuroimaging analysis! I can suggest parameters based on your dataset, recommend analysis methods, and provide guidance on best practices. What specific aspect of your analysis would you like help with?"
  }
}

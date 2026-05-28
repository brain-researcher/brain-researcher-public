/**
 * Survey Templates for Neuroimaging Research
 * Pre-built survey templates and question libraries for common neuroimaging studies
 */

import { 
  SurveyTemplate, 
  TemplateQuestion, 
  QuestionType,
  SurveySettings,
  BrainRegion,
  CognitiveDomain,
  ScannerParameters 
} from '@/types/survey';

// Brain Region Definitions
export const BRAIN_REGIONS: BrainRegion[] = [
  {
    name: 'Prefrontal Cortex',
    atlas: 'AAL',
    coordinates: { x: 32, y: 22, z: 42 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Primary Motor Cortex',
    atlas: 'AAL',
    coordinates: { x: 37, y: -26, z: 58 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Visual Cortex',
    atlas: 'AAL',
    coordinates: { x: 18, y: -94, z: -12 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Auditory Cortex',
    atlas: 'AAL',
    coordinates: { x: 57, y: -32, z: 8 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Hippocampus',
    atlas: 'AAL',
    coordinates: { x: 28, y: -21, z: -18 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Amygdala',
    atlas: 'AAL',
    coordinates: { x: 22, y: -1, z: -18 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Thalamus',
    atlas: 'AAL',
    coordinates: { x: 10, y: -16, z: 8 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Cerebellum',
    atlas: 'AAL',
    coordinates: { x: 0, y: -63, z: -32 },
    hemisphere: 'bilateral'
  },
  {
    name: 'Brainstem',
    atlas: 'AAL',
    coordinates: { x: 0, y: -12, z: -16 },
    hemisphere: 'bilateral'
  }
];

// Cognitive Domain Definitions
export const COGNITIVE_DOMAINS: CognitiveDomain[] = [
  {
    name: 'Executive Function',
    subcategories: ['Working Memory', 'Cognitive Flexibility', 'Inhibitory Control'],
    assessments: ['Stroop Task', 'Wisconsin Card Sort', 'N-Back Task', 'Go/No-Go Task']
  },
  {
    name: 'Attention',
    subcategories: ['Sustained Attention', 'Selective Attention', 'Divided Attention'],
    assessments: ['Attention Network Test', 'Continuous Performance Task', 'Trail Making Test']
  },
  {
    name: 'Memory',
    subcategories: ['Working Memory', 'Episodic Memory', 'Semantic Memory'],
    assessments: ['Digit Span', 'Rey Auditory Verbal Learning', 'Spatial Memory Task']
  },
  {
    name: 'Language',
    subcategories: ['Comprehension', 'Production', 'Reading'],
    assessments: ['Verbal Fluency', 'Boston Naming Test', 'Token Test']
  },
  {
    name: 'Visuospatial',
    subcategories: ['Spatial Processing', 'Visual Perception', 'Mental Rotation'],
    assessments: ['Block Design', 'Mental Rotation Task', 'Line Orientation']
  }
];

// Scanner Parameter Templates
export const SCANNER_PARAMETERS: ScannerParameters[] = [
  {
    field_strength: '3T',
    manufacturer: 'Siemens',
    pulse_sequence: 'T1-MPRAGE',
    voxel_size: [1, 1, 1],
    repetition_time: 2300,
    echo_time: 2.32,
    flip_angle: 9
  },
  {
    field_strength: '3T',
    manufacturer: 'GE',
    pulse_sequence: 'EPI',
    voxel_size: [3, 3, 3],
    repetition_time: 2000,
    echo_time: 30,
    flip_angle: 90
  },
  {
    field_strength: '7T',
    manufacturer: 'Siemens',
    pulse_sequence: 'T1-MPRAGE',
    voxel_size: [0.7, 0.7, 0.7],
    repetition_time: 3000,
    echo_time: 3.5,
    flip_angle: 7
  }
];

// Question Templates
export const NEUROIMAGING_QUESTION_TEMPLATES: Record<string, TemplateQuestion> = {
  scanner_parameters: {
    question_text: 'Please specify the MRI scanner parameters used in this study',
    question_type: 'scanner_parameters' as QuestionType,
    options: {
      scanner_parameters: SCANNER_PARAMETERS as any,
      custom_allowed: true
    },
    validation_rules: {
      required: true,
      neuroimaging_validation: {
        required_parameters: ['field_strength', 'pulse_sequence'],
        valid_modalities: ['fMRI', 'sMRI', 'DTI']
      }
    },
    neuroimaging_context: {
      category: 'acquisition_parameters',
      required_for: ['fMRI', 'structural_MRI'],
      statistical_covariates: true
    },
    required: true,
    description: 'Essential for data quality assessment and cross-study comparisons'
  },

  brain_regions: {
    question_text: 'Which brain regions were analyzed in this study?',
    question_type: 'brain_region' as QuestionType,
    options: {
      brain_regions: BRAIN_REGIONS,
      choices: BRAIN_REGIONS.map(region => ({
        id: region.name.toLowerCase().replace(/\s+/g, '_'),
        text: region.name,
        value: region.name,
        description: `Atlas: ${region.atlas}, Coordinates: (${region.coordinates.x}, ${region.coordinates.y}, ${region.coordinates.z})`
      })),
      other_option: true
    },
    validation_rules: {
      required: true,
      neuroimaging_validation: {
        atlas_validation: 'AAL',
        coordinate_validation: true
      }
    },
    neuroimaging_context: {
      category: 'analysis_regions',
      atlas_support: true,
      statistical_covariates: false
    },
    required: true,
    description: 'Select all brain regions that were part of your analysis'
  },

  cognitive_assessment: {
    question_text: 'Which cognitive assessments were administered during the study?',
    question_type: 'cognitive_battery' as QuestionType,
    options: {
      cognitive_assessments: COGNITIVE_DOMAINS,
      choices: COGNITIVE_DOMAINS.flatMap(domain => 
        domain.assessments?.map(assessment => ({
          id: assessment.toLowerCase().replace(/[^a-z0-9]/g, '_'),
          text: assessment,
          value: assessment,
          description: `Domain: ${domain.name}`,
          neuroimaging_metadata: { domain: domain.name }
        })) || []
      ),
      other_option: true
    },
    validation_rules: {
      required: false,
      neuroimaging_validation: {
        valid_modalities: ['fMRI', 'EEG', 'MEG']
      }
    },
    neuroimaging_context: {
      category: 'behavioral_measures',
      synchronized_with_imaging: true,
      statistical_covariates: true
    },
    required: false,
    description: 'Select all cognitive tasks administered during or outside of scanning'
  },

  medication_history: {
    question_text: 'Please provide medication history relevant to neuroimaging analysis',
    question_type: 'medication_history' as QuestionType,
    options: {
      medication_categories: [
        'Antidepressants (SSRIs, SNRIs)',
        'Antipsychotics',
        'Stimulants (ADHD medications)',
        'Anti-anxiety medications',
        'Mood stabilizers',
        'Neurological medications',
        'None',
        'Prefer not to answer'
      ],
      choices: [
        {
          id: 'antidepressants',
          text: 'Antidepressants (SSRIs, SNRIs)',
          value: 'antidepressants',
          description: 'May affect neurotransmitter systems and brain activity'
        },
        {
          id: 'antipsychotics',
          text: 'Antipsychotics',
          value: 'antipsychotics',
          description: 'Can significantly affect dopaminergic systems'
        },
        {
          id: 'stimulants',
          text: 'Stimulants (ADHD medications)',
          value: 'stimulants',
          description: 'Affect attention networks and dopamine signaling'
        },
        {
          id: 'none',
          text: 'None',
          value: 'none'
        }
      ]
    },
    validation_rules: {
      required: true,
      neuroimaging_validation: {
        required_parameters: ['medication_category', 'dosage_info']
      }
    },
    neuroimaging_context: {
      category: 'participant_characteristics',
      statistical_covariates: true
    },
    required: true,
    description: 'Medication information is crucial for interpreting neuroimaging results'
  },

  demographics: {
    question_text: 'Participant Demographics',
    question_type: 'matrix' as QuestionType,
    options: {
      rows: ['Age', 'Gender', 'Education Years', 'Handedness'],
      columns: ['Response'],
      choices: [
        {
          id: 'age',
          text: 'Age (years)',
          value: 'age'
        },
        {
          id: 'gender',
          text: 'Gender',
          value: 'gender'
        },
        {
          id: 'education',
          text: 'Years of Education',
          value: 'education'
        },
        {
          id: 'handedness',
          text: 'Handedness',
          value: 'handedness'
        }
      ]
    },
    validation_rules: {
      required: true
    },
    neuroimaging_context: {
      category: 'participant_characteristics',
      statistical_covariates: true
    },
    required: true,
    description: 'Basic demographic information for statistical analysis'
  },

  data_quality: {
    question_text: 'Please rate the quality of the uploaded neuroimaging data',
    question_type: 'scale' as QuestionType,
    options: {
      scale_type: 'likert',
      scale_min: 1,
      scale_max: 5,
      scale_labels: ['Poor', 'Fair', 'Good', 'Very Good', 'Excellent'],
      choices: [
        { id: '1', text: 'Poor', value: 1 },
        { id: '2', text: 'Fair', value: 2 },
        { id: '3', text: 'Good', value: 3 },
        { id: '4', text: 'Very Good', value: 4 },
        { id: '5', text: 'Excellent', value: 5 }
      ]
    },
    validation_rules: {
      required: true,
      min_value: 1,
      max_value: 5
    },
    neuroimaging_context: {
      category: 'quality_assessment'
    },
    required: true,
    description: 'Rate overall data quality including motion artifacts, signal-to-noise ratio, and coverage'
  },

  analysis_feedback: {
    question_text: 'Please provide feedback on the neuroimaging analysis results',
    question_type: 'textarea' as QuestionType,
    options: {
      max_length: 1000,
      min_length: 10
    },
    validation_rules: {
      required: false,
      min_value: 10,
      max_value: 1000
    },
    neuroimaging_context: {
      category: 'analysis_feedback'
    },
    required: false,
    description: 'Your feedback helps improve analysis pipelines and result interpretation'
  }
};

// Complete Survey Templates
export const SURVEY_TEMPLATES: SurveyTemplate[] = [
  {
    id: 'fmri_task_study',
    name: 'fMRI Task-Based Study Survey',
    description: 'Comprehensive survey for task-based fMRI studies including scanner parameters, cognitive assessments, and participant demographics',
    category: 'neuroimaging_protocol',
    neuroimaging_focus: ['fMRI'],
    study_types: ['task-based'],
    cognitive_domains: ['executive_function', 'attention', 'memory'],
    template_questions: [
      NEUROIMAGING_QUESTION_TEMPLATES.scanner_parameters,
      NEUROIMAGING_QUESTION_TEMPLATES.brain_regions,
      NEUROIMAGING_QUESTION_TEMPLATES.cognitive_assessment,
      NEUROIMAGING_QUESTION_TEMPLATES.demographics,
      NEUROIMAGING_QUESTION_TEMPLATES.medication_history
    ],
    default_settings: {
      theme: {
        primary_color: '#2563eb',
        secondary_color: '#64748b',
        font_family: 'Inter'
      },
      logic: {
        conditional_questions: [],
        randomization: {
          randomize_questions: false,
          randomize_options: false
        }
      },
      validation: {
        require_all_questions: true,
        email_validation: false,
        phone_validation: false
      }
    },
    usage_count: 0,
    created_at: new Date().toISOString(),
    created_by: 'system',
    tags: ['fMRI', 'task-based', 'cognitive', 'neuroimaging'],
    is_public: true
  },

  {
    id: 'resting_state_study',
    name: 'Resting-State fMRI Study Survey',
    description: 'Survey template for resting-state connectivity studies focusing on scanner parameters and participant characteristics',
    category: 'neuroimaging_protocol',
    neuroimaging_focus: ['fMRI'],
    study_types: ['resting-state'],
    cognitive_domains: [],
    template_questions: [
      NEUROIMAGING_QUESTION_TEMPLATES.scanner_parameters,
      NEUROIMAGING_QUESTION_TEMPLATES.brain_regions,
      NEUROIMAGING_QUESTION_TEMPLATES.demographics,
      NEUROIMAGING_QUESTION_TEMPLATES.medication_history,
      {
        question_text: 'How long was the resting-state scan?',
        question_type: 'single_choice' as QuestionType,
        options: {
          choices: [
            { id: '5min', text: '5 minutes', value: '5' },
            { id: '10min', text: '10 minutes', value: '10' },
            { id: '15min', text: '15 minutes', value: '15' },
            { id: 'other', text: 'Other', value: 'other' }
          ]
        },
        validation_rules: { required: true },
        neuroimaging_context: {
          category: 'acquisition_parameters'
        },
        required: true,
        description: 'Scan duration affects connectivity analysis reliability'
      }
    ],
    default_settings: {
      theme: {
        primary_color: '#059669',
        secondary_color: '#64748b',
        font_family: 'Inter'
      },
      validation: {
        require_all_questions: true,
        email_validation: false,
        phone_validation: false
      }
    },
    usage_count: 0,
    created_at: new Date().toISOString(),
    created_by: 'system',
    tags: ['fMRI', 'resting-state', 'connectivity', 'networks'],
    is_public: true
  },

  {
    id: 'clinical_neuroimaging',
    name: 'Clinical Neuroimaging Study Survey',
    description: 'Comprehensive survey for clinical neuroimaging research including detailed medical history and clinical assessments',
    category: 'clinical_research',
    neuroimaging_focus: ['fMRI', 'sMRI', 'DTI'],
    study_types: ['clinical', 'patient-control'],
    cognitive_domains: ['executive_function', 'memory', 'attention'],
    template_questions: [
      NEUROIMAGING_QUESTION_TEMPLATES.scanner_parameters,
      NEUROIMAGING_QUESTION_TEMPLATES.brain_regions,
      NEUROIMAGING_QUESTION_TEMPLATES.cognitive_assessment,
      NEUROIMAGING_QUESTION_TEMPLATES.demographics,
      NEUROIMAGING_QUESTION_TEMPLATES.medication_history,
      {
        question_text: 'What is the primary clinical diagnosis?',
        question_type: 'single_choice' as QuestionType,
        options: {
          choices: [
            { id: 'depression', text: 'Major Depressive Disorder', value: 'depression' },
            { id: 'anxiety', text: 'Anxiety Disorder', value: 'anxiety' },
            { id: 'schizophrenia', text: 'Schizophrenia', value: 'schizophrenia' },
            { id: 'bipolar', text: 'Bipolar Disorder', value: 'bipolar' },
            { id: 'adhd', text: 'ADHD', value: 'adhd' },
            { id: 'control', text: 'Healthy Control', value: 'control' },
            { id: 'other', text: 'Other', value: 'other' }
          ]
        },
        validation_rules: { required: true },
        neuroimaging_context: {
          category: 'clinical_characteristics',
          statistical_covariates: true
        },
        required: true
      }
    ],
    default_settings: {
      theme: {
        primary_color: '#dc2626',
        secondary_color: '#64748b',
        font_family: 'Inter'
      },
      privacy: {
        anonymous_responses: true,
        collect_ip: false,
        gdpr_compliant: true,
        data_retention_days: 1825 // 5 years
      },
      validation: {
        require_all_questions: true,
        email_validation: false,
        phone_validation: false
      }
    },
    usage_count: 0,
    created_at: new Date().toISOString(),
    created_by: 'system',
    tags: ['clinical', 'patient', 'medical', 'diagnosis'],
    is_public: true
  },

  {
    id: 'data_quality_assessment',
    name: 'Data Quality Assessment Survey',
    description: 'Post-upload survey for assessing neuroimaging data quality and providing feedback',
    category: 'quality_assessment',
    neuroimaging_focus: ['fMRI', 'sMRI', 'DTI', 'EEG', 'MEG'],
    study_types: ['quality-control'],
    cognitive_domains: [],
    template_questions: [
      NEUROIMAGING_QUESTION_TEMPLATES.data_quality,
      {
        question_text: 'Were there any issues with data acquisition?',
        question_type: 'multiple_choice' as QuestionType,
        options: {
          choices: [
            { id: 'motion', text: 'Excessive head motion', value: 'motion' },
            { id: 'artifacts', text: 'Image artifacts', value: 'artifacts' },
            { id: 'coverage', text: 'Incomplete brain coverage', value: 'coverage' },
            { id: 'signal', text: 'Poor signal quality', value: 'signal' },
            { id: 'none', text: 'No issues', value: 'none' }
          ],
          other_option: true
        },
        validation_rules: { required: true },
        neuroimaging_context: {
          category: 'quality_assessment'
        },
        required: true
      },
      NEUROIMAGING_QUESTION_TEMPLATES.analysis_feedback
    ],
    default_settings: {
      theme: {
        primary_color: '#7c3aed',
        secondary_color: '#64748b',
        font_family: 'Inter'
      },
      reminders: {
        enabled: true,
        frequency: 'weekly',
        max_reminders: 3
      }
    },
    usage_count: 0,
    created_at: new Date().toISOString(),
    created_by: 'system',
    tags: ['quality', 'assessment', 'feedback', 'qc'],
    is_public: true
  },

  {
    id: 'user_experience_feedback',
    name: 'Neuroimaging Platform User Experience',
    description: 'Collect feedback on the usability and effectiveness of neuroimaging analysis platforms',
    category: 'user_feedback',
    neuroimaging_focus: ['platform'],
    study_types: ['usability'],
    cognitive_domains: [],
    template_questions: [
      {
        question_text: 'How would you rate the overall usability of the platform?',
        question_type: 'scale' as QuestionType,
        options: {
          scale_type: 'likert',
          scale_min: 1,
          scale_max: 5,
          scale_labels: ['Very Difficult', 'Difficult', 'Neutral', 'Easy', 'Very Easy']
        },
        validation_rules: { required: true },
        neuroimaging_context: {
          category: 'usability_feedback'
        },
        required: true
      },
      {
        question_text: 'Which analysis features do you use most frequently?',
        question_type: 'multiple_choice' as QuestionType,
        options: {
          choices: [
            { id: 'preprocessing', text: 'Preprocessing pipelines', value: 'preprocessing' },
            { id: 'statistics', text: 'Statistical analysis', value: 'statistics' },
            { id: 'visualization', text: 'Brain visualization', value: 'visualization' },
            { id: 'connectivity', text: 'Connectivity analysis', value: 'connectivity' },
            { id: 'machine_learning', text: 'Machine learning', value: 'machine_learning' }
          ]
        },
        validation_rules: { required: true },
        neuroimaging_context: {
          category: 'feature_usage'
        },
        required: true
      },
      {
        question_text: 'What improvements would you like to see?',
        question_type: 'textarea' as QuestionType,
        options: {
          max_length: 500,
          min_length: 10
        },
        validation_rules: { required: false },
        neuroimaging_context: {
          category: 'feature_requests'
        },
        required: false
      }
    ],
    default_settings: {
      theme: {
        primary_color: '#0891b2',
        secondary_color: '#64748b',
        font_family: 'Inter'
      },
      privacy: {
        anonymous_responses: true,
        collect_ip: false,
        gdpr_compliant: true
      }
    },
    usage_count: 0,
    created_at: new Date().toISOString(),
    created_by: 'system',
    tags: ['usability', 'platform', 'feedback', 'ux'],
    is_public: true
  }
];

// Utility Functions
export function getTemplatesByCategory(category: string): SurveyTemplate[] {
  return SURVEY_TEMPLATES.filter(template => template.category === category);
}

export function getTemplatesByModality(modality: string): SurveyTemplate[] {
  return SURVEY_TEMPLATES.filter(template => 
    template.neuroimaging_focus.includes(modality)
  );
}

export function getQuestionTemplate(templateKey: string): TemplateQuestion | null {
  return NEUROIMAGING_QUESTION_TEMPLATES[templateKey] || null;
}

export function createCustomTemplate(
  name: string,
  description: string,
  questionKeys: string[],
  customSettings?: Partial<SurveySettings>
): Partial<SurveyTemplate> {
  const questions = questionKeys
    .map(key => getQuestionTemplate(key))
    .filter(Boolean) as TemplateQuestion[];

  return {
    name,
    description,
    category: 'custom',
    neuroimaging_focus: ['custom'],
    study_types: ['custom'],
    cognitive_domains: [],
    template_questions: questions,
    default_settings: {
      theme: {
        primary_color: '#6366f1',
        secondary_color: '#64748b',
        font_family: 'Inter'
      },
      validation: {
        require_all_questions: true,
        email_validation: false,
        phone_validation: false
      },
      ...customSettings
    },
    tags: ['custom'],
    is_public: false
  };
}

export default SURVEY_TEMPLATES;

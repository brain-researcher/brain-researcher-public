/**
 * Unit Tests for Question Editor Component
 * 
 * Comprehensive tests for the question editing interface including
 * all question types, neuroimaging-specific options, validation,
 * conditional logic, and accessibility features.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

// Mock the question editor component (would be implemented)
import { QuestionEditor } from '@/components/surveys/QuestionEditor';
import { SurveyQuestion, QuestionType, TemplateQuestion, QuestionEditorProps } from '@/types/survey';

// Mock dependencies
jest.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: jest.fn(),
  }),
}));

jest.mock('@/lib/brain-researcher-api', () => ({
  validateQuestion: jest.fn(),
  getBrainRegions: jest.fn(),
  getCognitiveBatteries: jest.fn(),
}));

// Sample question data for testing
const mockMultipleChoiceQuestion: Partial<SurveyQuestion> = {
  id: 'question-1',
  survey_id: 'survey-123',
  question_text: 'What is your experience with fMRI analysis?',
  question_type: 'multiple_choice',
  description: 'Select your level of experience',
  options: {
    choices: [
      { id: '1', text: 'Beginner', value: 'beginner' },
      { id: '2', text: 'Intermediate', value: 'intermediate' },
      { id: '3', text: 'Advanced', value: 'advanced' }
    ],
    other_option: true
  },
  validation_rules: { required: true },
  order_index: 0,
  required: true,
  randomize_options: false
};

const mockBrainRegionQuestion: Partial<SurveyQuestion> = {
  id: 'question-2',
  survey_id: 'survey-123',
  question_text: 'Which brain regions did you analyze?',
  question_type: 'brain_region',
  description: 'Select all applicable regions',
  options: {
    brain_regions: [
      { 
        name: 'Prefrontal Cortex', 
        atlas: 'AAL',
        coordinates: { x: -45, y: 23, z: 15 },
        hemisphere: 'bilateral'
      },
      { 
        name: 'Motor Cortex', 
        atlas: 'AAL',
        hemisphere: 'bilateral'
      }
    ],
    custom_allowed: true
  },
  validation_rules: { required: false },
  neuroimaging_context: {
    category: 'analysis_regions',
    atlas_support: true,
    required_for: ['fMRI']
  },
  order_index: 1,
  required: false
};

const mockScaleQuestion: Partial<SurveyQuestion> = {
  id: 'question-3',
  survey_id: 'survey-123',
  question_text: 'Rate your satisfaction with the analysis tools',
  question_type: 'scale',
  description: 'Use a scale from 1-10',
  options: {
    scale_type: 'numeric',
    scale_min: 1,
    scale_max: 10,
    scale_labels: ['Very Dissatisfied', 'Very Satisfied']
  },
  validation_rules: { 
    required: true,
    min_value: 1,
    max_value: 10
  },
  order_index: 2,
  required: true
};

const mockScannerParametersQuestion: Partial<SurveyQuestion> = {
  id: 'question-4',
  survey_id: 'survey-123',
  question_text: 'Specify your scanner parameters',
  question_type: 'scanner_parameters',
  description: 'Provide technical details',
  options: {
    scanner_parameters: {
      field_strength: ['1.5T', '3T', '7T'],
      manufacturer: ['Siemens', 'GE', 'Philips'],
      pulse_sequence: ['T1-MPRAGE', 'T2-FLAIR', 'EPI', 'DTI']
    }
  },
  validation_rules: { required: true },
  neuroimaging_context: {
    category: 'acquisition_parameters',
    required_for: ['fMRI', 'structural_MRI']
  },
  order_index: 3,
  required: true
};

const mockNeuroimagingTemplates: TemplateQuestion[] = [
  {
    question_text: 'Standard fMRI protocol assessment',
    question_type: 'neuroimaging_protocol',
    options: {
      protocols: ['task-based', 'resting-state', 'connectivity']
    },
    validation_rules: { required: true },
    neuroimaging_context: {
      category: 'protocol_assessment'
    },
    required: true
  }
];

// Default props
const defaultProps: QuestionEditorProps = {
  question: mockMultipleChoiceQuestion,
  onChange: jest.fn(),
  onSave: jest.fn(),
  onCancel: jest.fn(),
  neuroimagingTemplates: mockNeuroimagingTemplates
};

describe('QuestionEditor Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Component Rendering', () => {
    it('renders question editor with basic elements', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByText('Edit Question')).toBeInTheDocument();
      expect(screen.getByLabelText(/question text/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/question type/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
      expect(screen.getByText(/save/i)).toBeInTheDocument();
      expect(screen.getByText(/cancel/i)).toBeInTheDocument();
    });

    it('loads existing question data correctly', () => {
      render(<QuestionEditor {...defaultProps} />);

      const questionTextInput = screen.getByLabelText(/question text/i) as HTMLInputElement;
      const descriptionInput = screen.getByLabelText(/description/i) as HTMLTextAreaElement;

      expect(questionTextInput.value).toBe(mockMultipleChoiceQuestion.question_text);
      expect(descriptionInput.value).toBe(mockMultipleChoiceQuestion.description);
    });

    it('displays correct question type', () => {
      render(<QuestionEditor {...defaultProps} />);

      const typeSelect = screen.getByLabelText(/question type/i) as HTMLSelectElement;
      expect(typeSelect.value).toBe('multiple_choice');
    });

    it('shows required field indicator', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByText(/required/i)).toBeInTheDocument();
      const requiredCheckbox = screen.getByLabelText(/make this question required/i) as HTMLInputElement;
      expect(requiredCheckbox.checked).toBe(true);
    });
  });

  describe('Question Text and Description Editing', () => {
    it('allows editing question text', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const questionTextInput = screen.getByLabelText(/question text/i);
      await user.clear(questionTextInput);
      await user.type(questionTextInput, 'Updated question text');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          question_text: 'Updated question text'
        })
      );
    });

    it('allows editing description', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const descriptionInput = screen.getByLabelText(/description/i);
      await user.clear(descriptionInput);
      await user.type(descriptionInput, 'Updated description');

      expect(mockOnChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          description: 'Updated description'
        })
      );
    });

    it('validates question text is required', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const questionTextInput = screen.getByLabelText(/question text/i);
      await user.clear(questionTextInput);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/question text is required/i)).toBeInTheDocument();
      });
    });

    it('shows character count for text inputs', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByText(/\d+ characters/i)).toBeInTheDocument();
    });
  });

  describe('Question Type Selection', () => {
    it('allows changing question type', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const typeSelect = screen.getByLabelText(/question type/i);
      await user.selectOptions(typeSelect, 'scale');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          question_type: 'scale'
        })
      );
    });

    it('shows appropriate options for each question type', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      // Multiple choice should show choice options
      expect(screen.getByText(/answer choices/i)).toBeInTheDocument();
      expect(screen.getByText(/add choice/i)).toBeInTheDocument();

      // Change to scale type
      const typeSelect = screen.getByLabelText(/question type/i);
      await user.selectOptions(typeSelect, 'scale');

      await waitFor(() => {
        expect(screen.getByLabelText(/minimum value/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/maximum value/i)).toBeInTheDocument();
      });
    });

    it('groups neuroimaging question types separately', () => {
      render(<QuestionEditor {...defaultProps} />);

      const typeSelect = screen.getByLabelText(/question type/i);
      const optGroups = within(typeSelect).getAllByRole('group');

      expect(optGroups).toHaveLength(2); // Standard and Neuroimaging groups
      expect(screen.getByText(/standard questions/i)).toBeInTheDocument();
      expect(screen.getByText(/neuroimaging questions/i)).toBeInTheDocument();
    });
  });

  describe('Multiple Choice Question Options', () => {
    it('displays existing choices', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByDisplayValue('Beginner')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Intermediate')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Advanced')).toBeInTheDocument();
    });

    it('allows adding new choices', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const addChoiceButton = screen.getByText(/add choice/i);
      await user.click(addChoiceButton);

      const newChoiceInput = screen.getAllByLabelText(/choice text/i).pop();
      await user.type(newChoiceInput!, 'Expert');

      expect(mockOnChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            choices: expect.arrayContaining([
              expect.objectContaining({ text: 'Expert' })
            ])
          })
        })
      );
    });

    it('allows removing choices', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const removeButtons = screen.getAllByLabelText(/remove choice/i);
      await user.click(removeButtons[0]);

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            choices: expect.not.arrayContaining([
              expect.objectContaining({ text: 'Beginner' })
            ])
          })
        })
      );
    });

    it('allows reordering choices with drag and drop', async () => {
      const mockOnChange = jest.fn();
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const choices = screen.getAllByRole('listitem');
      const firstChoice = choices[0];
      const secondChoice = choices[1];

      // Simulate drag and drop
      fireEvent.dragStart(firstChoice);
      fireEvent.dragEnter(secondChoice);
      fireEvent.drop(secondChoice);

      expect(mockOnChange).toHaveBeenCalled();
    });

    it('toggles "Allow Other" option', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const allowOtherCheckbox = screen.getByLabelText(/allow other/i);
      expect(allowOtherCheckbox).toBeChecked();

      await user.click(allowOtherCheckbox);

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            other_option: false
          })
        })
      );
    });

    it('validates minimum number of choices', async () => {
      const questionWithFewChoices = {
        ...mockMultipleChoiceQuestion,
        options: {
          choices: [{ id: '1', text: 'Only one', value: 'one' }]
        }
      };

      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={questionWithFewChoices} />);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/multiple choice questions need at least 2 choices/i)).toBeInTheDocument();
      });
    });
  });

  describe('Scale Question Options', () => {
    it('renders scale question options', () => {
      render(<QuestionEditor {...defaultProps} question={mockScaleQuestion} />);

      expect(screen.getByLabelText(/minimum value/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/maximum value/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/scale type/i)).toBeInTheDocument();
    });

    it('allows editing scale range', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={mockScaleQuestion} onChange={mockOnChange} />);

      const minInput = screen.getByLabelText(/minimum value/i);
      await user.clear(minInput);
      await user.type(minInput, '0');

      const maxInput = screen.getByLabelText(/maximum value/i);
      await user.clear(maxInput);
      await user.type(maxInput, '5');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            scale_min: 0,
            scale_max: 5
          })
        })
      );
    });

    it('allows editing scale labels', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={mockScaleQuestion} onChange={mockOnChange} />);

      const lowLabelInput = screen.getByLabelText(/low end label/i);
      await user.clear(lowLabelInput);
      await user.type(lowLabelInput, 'Poor');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            scale_labels: expect.arrayContaining(['Poor'])
          })
        })
      );
    });

    it('validates scale range', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={mockScaleQuestion} />);

      const minInput = screen.getByLabelText(/minimum value/i);
      const maxInput = screen.getByLabelText(/maximum value/i);

      await user.clear(minInput);
      await user.type(minInput, '10');
      await user.clear(maxInput);
      await user.type(maxInput, '5');

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/maximum value must be greater than minimum/i)).toBeInTheDocument();
      });
    });
  });

  describe('Brain Region Question Options', () => {
    it('renders brain region question options', () => {
      render(<QuestionEditor {...defaultProps} question={mockBrainRegionQuestion} />);

      expect(screen.getByText(/brain regions/i)).toBeInTheDocument();
      expect(screen.getByText(/brain atlas/i)).toBeInTheDocument();
      expect(screen.getByText(/hemisphere/i)).toBeInTheDocument();
    });

    it('displays existing brain regions', () => {
      render(<QuestionEditor {...defaultProps} question={mockBrainRegionQuestion} />);

      expect(screen.getByText('Prefrontal Cortex')).toBeInTheDocument();
      expect(screen.getByText('Motor Cortex')).toBeInTheDocument();
    });

    it('allows adding custom brain regions', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={mockBrainRegionQuestion} onChange={mockOnChange} />);

      const addRegionButton = screen.getByText(/add brain region/i);
      await user.click(addRegionButton);

      const regionNameInput = screen.getByLabelText(/region name/i);
      await user.type(regionNameInput, 'Visual Cortex');

      const atlasSelect = screen.getByLabelText(/atlas/i);
      await user.selectOptions(atlasSelect, 'AAL');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            brain_regions: expect.arrayContaining([
              expect.objectContaining({ name: 'Visual Cortex', atlas: 'AAL' })
            ])
          })
        })
      );
    });

    it('allows setting coordinates for brain regions', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={mockBrainRegionQuestion} onChange={mockOnChange} />);

      const coordinatesButton = screen.getByText(/set coordinates/i);
      await user.click(coordinatesButton);

      const xInput = screen.getByLabelText(/x coordinate/i);
      await user.type(xInput, '-20');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            brain_regions: expect.arrayContaining([
              expect.objectContaining({
                coordinates: expect.objectContaining({ x: -20 })
              })
            ])
          })
        })
      );
    });

    it('validates brain region data', async () => {
      const invalidBrainRegionQuestion = {
        ...mockBrainRegionQuestion,
        options: {
          brain_regions: []
        }
      };

      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={invalidBrainRegionQuestion} />);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/brain region questions must have at least one region/i)).toBeInTheDocument();
      });
    });
  });

  describe('Scanner Parameters Question Options', () => {
    it('renders scanner parameters options', () => {
      render(<QuestionEditor {...defaultProps} question={mockScannerParametersQuestion} />);

      expect(screen.getByText(/field strength/i)).toBeInTheDocument();
      expect(screen.getByText(/manufacturer/i)).toBeInTheDocument();
      expect(screen.getByText(/pulse sequence/i)).toBeInTheDocument();
    });

    it('displays available scanner options', () => {
      render(<QuestionEditor {...defaultProps} question={mockScannerParametersQuestion} />);

      expect(screen.getByText('1.5T')).toBeInTheDocument();
      expect(screen.getByText('3T')).toBeInTheDocument();
      expect(screen.getByText('7T')).toBeInTheDocument();
      expect(screen.getByText('Siemens')).toBeInTheDocument();
    });

    it('allows customizing scanner parameter options', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={mockScannerParametersQuestion} onChange={mockOnChange} />);

      const addParameterButton = screen.getByText(/add parameter option/i);
      await user.click(addParameterButton);

      const parameterTypeSelect = screen.getByLabelText(/parameter type/i);
      await user.selectOptions(parameterTypeSelect, 'coil_type');

      const parameterValueInput = screen.getByLabelText(/parameter value/i);
      await user.type(parameterValueInput, '32-channel');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          options: expect.objectContaining({
            scanner_parameters: expect.objectContaining({
              coil_type: expect.arrayContaining(['32-channel'])
            })
          })
        })
      );
    });
  });

  describe('Conditional Logic', () => {
    it('shows conditional logic section', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const advancedButton = screen.getByText(/advanced options/i);
      await user.click(advancedButton);

      await waitFor(() => {
        expect(screen.getByText(/conditional logic/i)).toBeInTheDocument();
      });
    });

    it('allows adding show/hide conditions', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const advancedButton = screen.getByText(/advanced options/i);
      await user.click(advancedButton);

      await waitFor(() => {
        const addConditionButton = screen.getByText(/add condition/i);
        user.click(addConditionButton);
      });

      await waitFor(() => {
        const targetQuestionSelect = screen.getByLabelText(/target question/i);
        const operatorSelect = screen.getByLabelText(/condition operator/i);
        const valueInput = screen.getByLabelText(/condition value/i);

        expect(targetQuestionSelect).toBeInTheDocument();
        expect(operatorSelect).toBeInTheDocument();
        expect(valueInput).toBeInTheDocument();
      });
    });

    it('validates conditional logic setup', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const advancedButton = screen.getByText(/advanced options/i);
      await user.click(advancedButton);

      await waitFor(() => {
        const addConditionButton = screen.getByText(/add condition/i);
        user.click(addConditionButton);
      });

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/conditional logic requires target question/i)).toBeInTheDocument();
      });
    });
  });

  describe('Validation Rules', () => {
    it('shows validation options', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByLabelText(/make this question required/i)).toBeInTheDocument();
    });

    it('allows setting custom validation messages', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const customMessageInput = screen.getByLabelText(/custom validation message/i);
      await user.type(customMessageInput, 'Please select your experience level');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          validation_rules: expect.objectContaining({
            custom_message: 'Please select your experience level'
          })
        })
      );
    });

    it('shows validation rules for different question types', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={mockScaleQuestion} />);

      expect(screen.getByLabelText(/minimum value/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/maximum value/i)).toBeInTheDocument();
    });
  });

  describe('Neuroimaging Context', () => {
    it('shows neuroimaging context for relevant question types', () => {
      render(<QuestionEditor {...defaultProps} question={mockBrainRegionQuestion} />);

      expect(screen.getByText(/neuroimaging context/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/category/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/required for/i)).toBeInTheDocument();
    });

    it('allows editing neuroimaging context', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={mockBrainRegionQuestion} onChange={mockOnChange} />);

      const categorySelect = screen.getByLabelText(/context category/i);
      await user.selectOptions(categorySelect, 'statistical_analysis');

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          neuroimaging_context: expect.objectContaining({
            category: 'statistical_analysis'
          })
        })
      );
    });

    it('validates neuroimaging context completeness', async () => {
      const incompleteNeuroimagingQuestion = {
        ...mockBrainRegionQuestion,
        neuroimaging_context: {}
      };

      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={incompleteNeuroimagingQuestion} />);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/neuroimaging questions require context category/i)).toBeInTheDocument();
      });
    });
  });

  describe('Templates Integration', () => {
    it('shows template selector for neuroimaging questions', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={{}} />);

      const typeSelect = screen.getByLabelText(/question type/i);
      await user.selectOptions(typeSelect, 'neuroimaging_protocol');

      await waitFor(() => {
        expect(screen.getByText(/use template/i)).toBeInTheDocument();
      });
    });

    it('applies template when selected', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} question={{}} onChange={mockOnChange} />);

      const typeSelect = screen.getByLabelText(/question type/i);
      await user.selectOptions(typeSelect, 'neuroimaging_protocol');

      await waitFor(() => {
        const useTemplateButton = screen.getByText(/use template/i);
        user.click(useTemplateButton);
      });

      await waitFor(() => {
        const templateOption = screen.getByText(/standard fMRI protocol assessment/i);
        user.click(templateOption);
      });

      expect(mockOnChange).toHaveBeenCalledWith(
        expect.objectContaining({
          question_text: 'Standard fMRI protocol assessment',
          question_type: 'neuroimaging_protocol'
        })
      );
    });
  });

  describe('Preview Functionality', () => {
    it('shows question preview', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const previewButton = screen.getByText(/preview/i);
      await user.click(previewButton);

      await waitFor(() => {
        expect(screen.getByText(/question preview/i)).toBeInTheDocument();
        
        // Should show question as participant would see it
        const radioButtons = screen.getAllByRole('radio');
        expect(radioButtons.length).toBe(3); // Three choices plus potentially "Other"
      });
    });

    it('updates preview when question changes', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const previewButton = screen.getByText(/preview/i);
      await user.click(previewButton);

      // Change question text
      const questionTextInput = screen.getByLabelText(/question text/i);
      await user.clear(questionTextInput);
      await user.type(questionTextInput, 'Updated preview question');

      await waitFor(() => {
        expect(screen.getByText('Updated preview question')).toBeInTheDocument();
      });
    });
  });

  describe('Save and Cancel Operations', () => {
    it('calls onSave with question data when save is clicked', async () => {
      const mockOnSave = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onSave={mockOnSave} />);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      expect(mockOnSave).toHaveBeenCalledWith(
        expect.objectContaining({
          question_text: mockMultipleChoiceQuestion.question_text,
          question_type: mockMultipleChoiceQuestion.question_type
        })
      );
    });

    it('calls onCancel when cancel is clicked', async () => {
      const mockOnCancel = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onCancel={mockOnCancel} />);

      const cancelButton = screen.getByText(/cancel/i);
      await user.click(cancelButton);

      expect(mockOnCancel).toHaveBeenCalled();
    });

    it('shows unsaved changes warning', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      // Make changes
      const questionTextInput = screen.getByLabelText(/question text/i);
      await user.type(questionTextInput, ' Modified');

      // Try to cancel
      const cancelButton = screen.getByText(/cancel/i);
      await user.click(cancelButton);

      await waitFor(() => {
        expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
      });
    });

    it('validates question before saving', async () => {
      const invalidQuestion = {
        ...mockMultipleChoiceQuestion,
        question_text: '',
        options: { choices: [] }
      };

      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} question={invalidQuestion} />);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/validation errors found/i)).toBeInTheDocument();
      });
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByLabelText(/question text/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/question type/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
    });

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const questionTextInput = screen.getByLabelText(/question text/i);
      questionTextInput.focus();

      // Tab through elements
      await user.tab();
      expect(screen.getByLabelText(/question type/i)).toHaveFocus();

      await user.tab();
      expect(screen.getByLabelText(/description/i)).toHaveFocus();
    });

    it('announces validation errors to screen readers', async () => {
      const user = userEvent.setup();
      render(<QuestionEditor {...defaultProps} />);

      const questionTextInput = screen.getByLabelText(/question text/i);
      await user.clear(questionTextInput);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        const errorMessage = screen.getByRole('alert');
        expect(errorMessage).toHaveTextContent(/question text is required/i);
      });
    });

    it('provides field descriptions', () => {
      render(<QuestionEditor {...defaultProps} />);

      expect(screen.getByText(/the main text of your question/i)).toBeInTheDocument();
      expect(screen.getByText(/optional additional context/i)).toBeInTheDocument();
    });
  });

  describe('Performance and Edge Cases', () => {
    it('handles empty question gracefully', () => {
      render(<QuestionEditor {...defaultProps} question={{}} />);

      const questionTextInput = screen.getByLabelText(/question text/i) as HTMLInputElement;
      expect(questionTextInput.value).toBe('');
    });

    it('handles malformed question data', () => {
      const malformedQuestion = {
        question_text: null,
        options: null,
        validation_rules: undefined
      } as any;

      expect(() => {
        render(<QuestionEditor {...defaultProps} question={malformedQuestion} />);
      }).not.toThrow();
    });

    it('debounces onChange calls', async () => {
      const mockOnChange = jest.fn();
      const user = userEvent.setup();
      
      render(<QuestionEditor {...defaultProps} onChange={mockOnChange} />);

      const questionTextInput = screen.getByLabelText(/question text/i);
      
      // Type quickly
      await user.type(questionTextInput, 'Fast typing');

      // Should debounce and only call onChange once at the end
      await waitFor(() => {
        expect(mockOnChange).toHaveBeenCalledTimes(1);
      }, { timeout: 1000 });
    });

    it('handles large numbers of choices efficiently', () => {
      const questionWithManyChoices = {
        ...mockMultipleChoiceQuestion,
        options: {
          choices: Array.from({ length: 100 }, (_, i) => ({
            id: `choice-${i}`,
            text: `Choice ${i}`,
            value: `choice_${i}`
          }))
        }
      };

      const { container } = render(
        <QuestionEditor {...defaultProps} question={questionWithManyChoices} />
      );

      expect(container).toBeInTheDocument();
      expect(screen.getAllByLabelText(/choice text/i)).toHaveLength(100);
    });
  });
});
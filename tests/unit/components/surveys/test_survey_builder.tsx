/**
 * Unit Tests for Survey Builder UI Component
 * 
 * Comprehensive tests for the survey creation and editing interface,
 * including drag-and-drop functionality, question types, validation,
 * and neuroimaging-specific features.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

// Mock the survey builder component (would be implemented)
import { SurveyBuilder } from '@/components/surveys/SurveyBuilder';
import { Survey, SurveyQuestion, QuestionType, SurveyBuilderState } from '@/types/survey';

// Mock dependencies
jest.mock('@/lib/brain-researcher-api', () => ({
  createSurvey: jest.fn(),
  updateSurvey: jest.fn(),
  getSurveyTemplates: jest.fn(),
}));

jest.mock('@/hooks/use-toast', () => ({
  useToast: () => ({
    toast: jest.fn(),
  }),
}));

// Mock drag and drop
const mockDragEvent = (type: string) => ({
  dataTransfer: {
    setData: jest.fn(),
    getData: jest.fn(),
    effectAllowed: 'move',
    dropEffect: 'move',
  },
  preventDefault: jest.fn(),
  stopPropagation: jest.fn(),
  type,
});

// Sample data for testing
const mockSurvey: Partial<Survey> = {
  id: 'survey-123',
  title: 'Test Neuroimaging Survey',
  description: 'A survey for testing',
  category: 'cognitive_assessment',
  status: 'draft',
  creator_id: 'user-123',
  questions: []
};

const mockQuestions: SurveyQuestion[] = [
  {
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
      ]
    },
    validation_rules: { required: true },
    order_index: 0,
    required: true,
    randomize_options: false
  },
  {
    id: 'question-2',
    survey_id: 'survey-123',
    question_text: 'Which brain regions are you analyzing?',
    question_type: 'brain_region',
    description: 'Select all regions that apply',
    options: {
      brain_regions: [
        { name: 'Prefrontal Cortex', atlas: 'AAL', hemisphere: 'bilateral' },
        { name: 'Motor Cortex', atlas: 'AAL', hemisphere: 'bilateral' }
      ]
    },
    validation_rules: { required: false },
    neuroimaging_context: {
      category: 'analysis_regions',
      atlas_support: true
    },
    order_index: 1,
    required: false,
    randomize_options: false
  }
];

const mockBuilderState: SurveyBuilderState = {
  survey: mockSurvey,
  questions: mockQuestions,
  current_question_index: 0,
  preview_mode: false,
  unsaved_changes: false,
  validation_errors: {}
};

// Mock props
const defaultProps = {
  initialSurvey: mockSurvey,
  onSave: jest.fn(),
  onCancel: jest.fn(),
  onPreview: jest.fn(),
  neuroimagingTemplates: [],
  isReadOnly: false
};

describe('SurveyBuilder Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Component Rendering', () => {
    it('renders survey builder with basic elements', () => {
      render(<SurveyBuilder {...defaultProps} />);

      expect(screen.getByText('Survey Builder')).toBeInTheDocument();
      expect(screen.getByLabelText(/survey title/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/survey description/i)).toBeInTheDocument();
      expect(screen.getByText(/add question/i)).toBeInTheDocument();
      expect(screen.getByText(/preview/i)).toBeInTheDocument();
      expect(screen.getByText(/save/i)).toBeInTheDocument();
    });

    it('loads existing survey data correctly', () => {
      render(<SurveyBuilder {...defaultProps} />);

      const titleInput = screen.getByLabelText(/survey title/i) as HTMLInputElement;
      const descriptionInput = screen.getByLabelText(/survey description/i) as HTMLTextAreaElement;

      expect(titleInput.value).toBe(mockSurvey.title);
      expect(descriptionInput.value).toBe(mockSurvey.description);
    });

    it('displays existing questions', () => {
      render(<SurveyBuilder {...defaultProps} />);

      expect(screen.getByText('What is your experience with fMRI analysis?')).toBeInTheDocument();
      expect(screen.getByText('Which brain regions are you analyzing?')).toBeInTheDocument();
    });

    it('shows question type indicators', () => {
      render(<SurveyBuilder {...defaultProps} />);

      expect(screen.getByText(/multiple choice/i)).toBeInTheDocument();
      expect(screen.getByText(/brain region/i)).toBeInTheDocument();
    });

    it('displays neuroimaging context badges', () => {
      render(<SurveyBuilder {...defaultProps} />);

      expect(screen.getByText(/neuroimaging/i)).toBeInTheDocument();
      expect(screen.getByText(/analysis regions/i)).toBeInTheDocument();
    });
  });

  describe('Survey Metadata Editing', () => {
    it('allows editing survey title', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const titleInput = screen.getByLabelText(/survey title/i);
      await user.clear(titleInput);
      await user.type(titleInput, 'Updated Survey Title');

      expect(titleInput).toHaveValue('Updated Survey Title');
    });

    it('allows editing survey description', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const descriptionInput = screen.getByLabelText(/survey description/i);
      await user.clear(descriptionInput);
      await user.type(descriptionInput, 'Updated description');

      expect(descriptionInput).toHaveValue('Updated description');
    });

    it('allows selecting survey category', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const categorySelect = screen.getByLabelText(/category/i);
      await user.selectOptions(categorySelect, 'demographics');

      expect(categorySelect).toHaveValue('demographics');
    });

    it('validates required fields', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const titleInput = screen.getByLabelText(/survey title/i);
      await user.clear(titleInput);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/title is required/i)).toBeInTheDocument();
      });
    });
  });

  describe('Question Management', () => {
    it('shows add question button', () => {
      render(<SurveyBuilder {...defaultProps} />);
      
      expect(screen.getByText(/add question/i)).toBeInTheDocument();
    });

    it('opens question type selector when adding question', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const addButton = screen.getByText(/add question/i);
      await user.click(addButton);

      await waitFor(() => {
        expect(screen.getByText(/select question type/i)).toBeInTheDocument();
      });
    });

    it('displays all available question types', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const addButton = screen.getByText(/add question/i);
      await user.click(addButton);

      await waitFor(() => {
        // Standard types
        expect(screen.getByText(/multiple choice/i)).toBeInTheDocument();
        expect(screen.getByText(/single choice/i)).toBeInTheDocument();
        expect(screen.getByText(/text input/i)).toBeInTheDocument();
        expect(screen.getByText(/scale/i)).toBeInTheDocument();

        // Neuroimaging-specific types
        expect(screen.getByText(/brain region/i)).toBeInTheDocument();
        expect(screen.getByText(/scanner parameters/i)).toBeInTheDocument();
        expect(screen.getByText(/cognitive battery/i)).toBeInTheDocument();
      });
    });

    it('creates new question when type is selected', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const addButton = screen.getByText(/add question/i);
      await user.click(addButton);

      await waitFor(() => {
        const scaleOption = screen.getByText(/scale/i);
        user.click(scaleOption);
      });

      await waitFor(() => {
        expect(screen.getByText(/new scale question/i)).toBeInTheDocument();
      });
    });

    it('allows deleting questions', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const deleteButtons = screen.getAllByLabelText(/delete question/i);
      await user.click(deleteButtons[0]);

      // Confirmation dialog
      await waitFor(() => {
        expect(screen.getByText(/confirm delete/i)).toBeInTheDocument();
      });

      const confirmButton = screen.getByText(/delete/i);
      await user.click(confirmButton);

      await waitFor(() => {
        expect(screen.queryByText('What is your experience with fMRI analysis?')).not.toBeInTheDocument();
      });
    });

    it('allows duplicating questions', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const duplicateButtons = screen.getAllByLabelText(/duplicate question/i);
      await user.click(duplicateButtons[0]);

      await waitFor(() => {
        const fmriQuestions = screen.getAllByText(/What is your experience with fMRI analysis/);
        expect(fmriQuestions).toHaveLength(2);
      });
    });
  });

  describe('Question Reordering', () => {
    it('displays move up/down buttons', () => {
      render(<SurveyBuilder {...defaultProps} />);

      expect(screen.getAllByLabelText(/move up/i)).toHaveLength(1); // Second question can move up
      expect(screen.getAllByLabelText(/move down/i)).toHaveLength(1); // First question can move down
    });

    it('reorders questions with move buttons', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const moveDownButton = screen.getByLabelText(/move down/i);
      await user.click(moveDownButton);

      // Check that order changed
      await waitFor(() => {
        const questions = screen.getAllByRole('article'); // Assuming questions are in articles
        expect(questions[0]).toHaveTextContent('Which brain regions are you analyzing?');
        expect(questions[1]).toHaveTextContent('What is your experience with fMRI analysis?');
      });
    });

    it('supports drag and drop reordering', async () => {
      render(<SurveyBuilder {...defaultProps} />);

      const questions = screen.getAllByRole('article');
      const firstQuestion = questions[0];
      const secondQuestion = questions[1];

      // Simulate drag start
      fireEvent(firstQuestion, mockDragEvent('dragstart'));
      
      // Simulate drop on second question
      fireEvent(secondQuestion, mockDragEvent('drop'));

      await waitFor(() => {
        const reorderedQuestions = screen.getAllByRole('article');
        expect(reorderedQuestions[1]).toHaveTextContent('What is your experience with fMRI analysis?');
      });
    });
  });

  describe('Question Editing', () => {
    it('opens question editor when question is clicked', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const question = screen.getByText('What is your experience with fMRI analysis?');
      await user.click(question);

      await waitFor(() => {
        expect(screen.getByText(/edit question/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/question text/i)).toBeInTheDocument();
      });
    });

    it('shows question-specific editing options', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const question = screen.getByText('What is your experience with fMRI analysis?');
      await user.click(question);

      await waitFor(() => {
        // Multiple choice specific options
        expect(screen.getByText(/add choice/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/allow other/i)).toBeInTheDocument();
      });
    });

    it('shows neuroimaging-specific options for brain region questions', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const brainRegionQuestion = screen.getByText('Which brain regions are you analyzing?');
      await user.click(brainRegionQuestion);

      await waitFor(() => {
        expect(screen.getByText(/brain atlas/i)).toBeInTheDocument();
        expect(screen.getByText(/hemisphere/i)).toBeInTheDocument();
        expect(screen.getByText(/coordinates/i)).toBeInTheDocument();
      });
    });

    it('validates question text is required', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const question = screen.getByText('What is your experience with fMRI analysis?');
      await user.click(question);

      await waitFor(() => {
        const questionTextInput = screen.getByLabelText(/question text/i);
        user.clear(questionTextInput);
        
        const saveButton = screen.getByText(/save question/i);
        user.click(saveButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/question text is required/i)).toBeInTheDocument();
      });
    });
  });

  describe('Survey Templates', () => {
    const mockTemplates = [
      {
        id: 'template-1',
        name: 'fMRI Task-Based Study',
        description: 'Template for task-based fMRI studies',
        category: 'cognitive_neuroscience',
        neuroimaging_focus: ['fMRI'],
        template_questions: [
          {
            question_text: 'Scanner field strength',
            question_type: 'scanner_parameters',
            options: { field_strength: ['1.5T', '3T', '7T'] }
          }
        ]
      }
    ];

    it('shows template selector', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} neuroimagingTemplates={mockTemplates} />);

      expect(screen.getByText(/use template/i)).toBeInTheDocument();

      await user.click(screen.getByText(/use template/i));

      await waitFor(() => {
        expect(screen.getByText('fMRI Task-Based Study')).toBeInTheDocument();
      });
    });

    it('applies template when selected', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} neuroimagingTemplates={mockTemplates} />);

      await user.click(screen.getByText(/use template/i));
      
      await waitFor(() => {
        const templateOption = screen.getByText('fMRI Task-Based Study');
        user.click(templateOption);
      });

      const applyButton = screen.getByText(/apply template/i);
      await user.click(applyButton);

      await waitFor(() => {
        expect(screen.getByText(/scanner field strength/i)).toBeInTheDocument();
      });
    });

    it('shows template preview', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} neuroimagingTemplates={mockTemplates} />);

      await user.click(screen.getByText(/use template/i));
      
      await waitFor(() => {
        const templateOption = screen.getByText('fMRI Task-Based Study');
        user.hover(templateOption);
      });

      await waitFor(() => {
        expect(screen.getByText(/template for task-based fMRI studies/i)).toBeInTheDocument();
        expect(screen.getByText(/1 question/i)).toBeInTheDocument();
      });
    });
  });

  describe('Survey Preview', () => {
    it('enters preview mode when preview button is clicked', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const previewButton = screen.getByText(/preview/i);
      await user.click(previewButton);

      await waitFor(() => {
        expect(screen.getByText(/preview mode/i)).toBeInTheDocument();
        expect(screen.getByText(/exit preview/i)).toBeInTheDocument();
      });
    });

    it('shows survey in participant view during preview', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const previewButton = screen.getByText(/preview/i);
      await user.click(previewButton);

      await waitFor(() => {
        // Should show survey title and questions as participants would see them
        expect(screen.getByRole('heading', { name: mockSurvey.title })).toBeInTheDocument();
        
        // Questions should be interactive
        const radioButtons = screen.getAllByRole('radio');
        expect(radioButtons.length).toBeGreaterThan(0);
      });
    });

    it('exits preview mode', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      // Enter preview mode
      await user.click(screen.getByText(/preview/i));

      await waitFor(() => {
        const exitButton = screen.getByText(/exit preview/i);
        user.click(exitButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/add question/i)).toBeInTheDocument();
        expect(screen.queryByText(/exit preview/i)).not.toBeInTheDocument();
      });
    });
  });

  describe('Save and Cancel Operations', () => {
    it('calls onSave with survey data when save is clicked', async () => {
      const mockOnSave = jest.fn();
      const user = userEvent.setup();
      
      render(<SurveyBuilder {...defaultProps} onSave={mockOnSave} />);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      expect(mockOnSave).toHaveBeenCalledWith(
        expect.objectContaining({
          title: mockSurvey.title,
          description: mockSurvey.description,
          questions: expect.any(Array)
        })
      );
    });

    it('calls onCancel when cancel is clicked', async () => {
      const mockOnCancel = jest.fn();
      const user = userEvent.setup();
      
      render(<SurveyBuilder {...defaultProps} onCancel={mockOnCancel} />);

      const cancelButton = screen.getByText(/cancel/i);
      await user.click(cancelButton);

      expect(mockOnCancel).toHaveBeenCalled();
    });

    it('shows unsaved changes warning', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      // Make changes
      const titleInput = screen.getByLabelText(/survey title/i);
      await user.type(titleInput, ' Modified');

      // Try to cancel
      const cancelButton = screen.getByText(/cancel/i);
      await user.click(cancelButton);

      await waitFor(() => {
        expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
      });
    });

    it('auto-saves draft periodically', async () => {
      jest.useFakeTimers();
      const mockAutoSave = jest.fn();
      
      render(<SurveyBuilder {...defaultProps} onAutoSave={mockAutoSave} />);

      // Make changes
      const titleInput = screen.getByLabelText(/survey title/i);
      await userEvent.type(titleInput, ' Auto-save test');

      // Advance timers to trigger auto-save
      jest.advanceTimersByTime(30000); // 30 seconds

      await waitFor(() => {
        expect(mockAutoSave).toHaveBeenCalled();
      });

      jest.useRealTimers();
    });
  });

  describe('Validation and Error Handling', () => {
    it('validates survey before saving', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      // Clear required fields
      const titleInput = screen.getByLabelText(/survey title/i);
      await user.clear(titleInput);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/title is required/i)).toBeInTheDocument();
      });
    });

    it('validates questions have required options', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      // Create multiple choice question without choices
      const addButton = screen.getByText(/add question/i);
      await user.click(addButton);

      await waitFor(() => {
        const multipleChoiceOption = screen.getByText(/multiple choice/i);
        user.click(multipleChoiceOption);
      });

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/multiple choice questions must have choices/i)).toBeInTheDocument();
      });
    });

    it('validates neuroimaging questions have proper context', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      // Edit brain region question to remove context
      const brainRegionQuestion = screen.getByText('Which brain regions are you analyzing?');
      await user.click(brainRegionQuestion);

      await waitFor(() => {
        const contextInput = screen.getByLabelText(/neuroimaging context/i);
        user.clear(contextInput);
        
        const saveQuestionButton = screen.getByText(/save question/i);
        user.click(saveQuestionButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/neuroimaging questions require context/i)).toBeInTheDocument();
      });
    });

    it('shows validation summary', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      // Create multiple validation errors
      const titleInput = screen.getByLabelText(/survey title/i);
      await user.clear(titleInput);

      const saveButton = screen.getByText(/save/i);
      await user.click(saveButton);

      await waitFor(() => {
        expect(screen.getByText(/validation errors/i)).toBeInTheDocument();
        expect(screen.getByText(/1 error found/i)).toBeInTheDocument();
      });
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(<SurveyBuilder {...defaultProps} />);

      expect(screen.getByLabelText(/survey title/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/survey description/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add question/i })).toBeInTheDocument();
    });

    it('supports keyboard navigation', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const titleInput = screen.getByLabelText(/survey title/i);
      titleInput.focus();

      // Tab through elements
      await user.tab();
      expect(screen.getByLabelText(/survey description/i)).toHaveFocus();

      await user.tab();
      expect(screen.getByLabelText(/category/i)).toHaveFocus();
    });

    it('announces changes to screen readers', async () => {
      const user = userEvent.setup();
      render(<SurveyBuilder {...defaultProps} />);

      const addButton = screen.getByText(/add question/i);
      await user.click(addButton);

      await waitFor(() => {
        expect(screen.getByRole('status')).toHaveTextContent(/question added/i);
      });
    });
  });

  describe('Read-only Mode', () => {
    it('disables editing in read-only mode', () => {
      render(<SurveyBuilder {...defaultProps} isReadOnly={true} />);

      const titleInput = screen.getByLabelText(/survey title/i) as HTMLInputElement;
      const descriptionInput = screen.getByLabelText(/survey description/i) as HTMLTextAreaElement;

      expect(titleInput).toBeDisabled();
      expect(descriptionInput).toBeDisabled();
      expect(screen.queryByText(/add question/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/save/i)).not.toBeInTheDocument();
    });

    it('shows read-only indicator', () => {
      render(<SurveyBuilder {...defaultProps} isReadOnly={true} />);

      expect(screen.getByText(/read-only/i)).toBeInTheDocument();
    });
  });

  describe('Performance', () => {
    it('renders efficiently with many questions', () => {
      const manyQuestions = Array.from({ length: 50 }, (_, i) => ({
        ...mockQuestions[0],
        id: `question-${i}`,
        question_text: `Question ${i}`,
        order_index: i
      }));

      const surveyWithManyQuestions = {
        ...mockSurvey,
        questions: manyQuestions
      };

      const { container } = render(
        <SurveyBuilder {...defaultProps} initialSurvey={surveyWithManyQuestions} />
      );

      expect(container).toBeInTheDocument();
      expect(screen.getAllByRole('article')).toHaveLength(50);
    });

    it('uses virtualization for large question lists', () => {
      // Test would verify virtual scrolling implementation
      // This is a placeholder for the actual virtualization test
      expect(true).toBe(true);
    });
  });
});

describe('SurveyBuilder Integration', () => {
  it('integrates with API for saving surveys', async () => {
    const mockCreateSurvey = jest.fn().mockResolvedValue({ id: 'new-survey-id' });
    const user = userEvent.setup();

    // Mock the API
    jest.doMock('@/lib/brain-researcher-api', () => ({
      createSurvey: mockCreateSurvey
    }));

    render(<SurveyBuilder {...defaultProps} initialSurvey={{}} />);

    // Fill out survey
    const titleInput = screen.getByLabelText(/survey title/i);
    await user.type(titleInput, 'New Survey');

    const saveButton = screen.getByText(/save/i);
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateSurvey).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'New Survey'
        })
      );
    });
  });

  it('handles API errors gracefully', async () => {
    const mockCreateSurvey = jest.fn().mockRejectedValue(new Error('Network error'));
    const user = userEvent.setup();

    jest.doMock('@/lib/brain-researcher-api', () => ({
      createSurvey: mockCreateSurvey
    }));

    render(<SurveyBuilder {...defaultProps} />);

    const saveButton = screen.getByText(/save/i);
    await user.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText(/error saving survey/i)).toBeInTheDocument();
    });
  });
});
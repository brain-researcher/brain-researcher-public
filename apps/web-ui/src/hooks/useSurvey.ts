/**
 * Custom React hooks for survey management and state handling
 * Comprehensive hooks for survey creation, editing, responses, and analytics
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from '@/hooks/use-toast';
import {
  Survey,
  SurveyQuestion,
  SurveyResponse,
  SurveyTemplate,
  SurveyAnalytics,
  SurveyInsight,
  CreateSurveyRequest,
  UpdateSurveyRequest,
  SubmitResponseRequest,
  SurveyBuilderState,
  SurveyOperationResult,
  PaginatedResponse,
  SurveyStatus
} from '@/types/survey';
import { api } from '@/lib/api';

// Survey List Management Hook
export function useSurveyList(initialFilters: {
  category?: string;
  status?: SurveyStatus;
  limit?: number;
} = {}) {
  const [surveys, setSurveys] = useState<Survey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState(initialFilters);
  const [pagination, setPagination] = useState({
    page: 1,
    limit: initialFilters.limit || 50,
    total: 0
  });

  const fetchSurveys = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const queryParams = new URLSearchParams({
        limit: pagination.limit.toString(),
        offset: ((pagination.page - 1) * pagination.limit).toString(),
        ...(filters.category && { category: filters.category }),
        ...(filters.status && { status: filters.status })
      });

      const response = await api.get(`/api/v1/surveys?${queryParams}`);
      
      if (response.ok) {
        const data = await response.json();
        setSurveys(data);
      } else {
        throw new Error('Failed to fetch surveys');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [filters, pagination.page, pagination.limit]);

  useEffect(() => {
    fetchSurveys();
  }, [fetchSurveys]);

  const updateFilters = useCallback((newFilters: Partial<typeof filters>) => {
    setFilters(prev => ({ ...prev, ...newFilters }));
    setPagination(prev => ({ ...prev, page: 1 })); // Reset to first page
  }, []);

  const changePage = useCallback((page: number) => {
    setPagination(prev => ({ ...prev, page }));
  }, []);

  return {
    surveys,
    loading,
    error,
    filters,
    pagination,
    updateFilters,
    changePage,
    refetch: fetchSurveys
  };
}

// Individual Survey Management Hook
export function useSurvey(surveyId: string | null) {
  const [survey, setSurvey] = useState<Survey | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const fetchSurvey = useCallback(async () => {
    if (!surveyId) return;

    setLoading(true);
    setError(null);

    try {
      const response = await api.get(`/api/v1/surveys/${surveyId}?include_questions=true&include_analytics=true`);
      
      if (response.ok) {
        const data = await response.json();
        setSurvey(data);
      } else {
        throw new Error('Failed to fetch survey');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [surveyId]);

  useEffect(() => {
    if (surveyId) {
      fetchSurvey();
    }
  }, [fetchSurvey, surveyId]);

  const updateSurvey = useCallback(async (updates: UpdateSurveyRequest): Promise<SurveyOperationResult> => {
    if (!surveyId) {
      return { success: false, error: { code: 'NO_SURVEY_ID', message: 'No survey ID provided' } };
    }

    try {
      const response = await api.put(`/api/v1/surveys/${surveyId}`, updates);
      
      if (response.ok) {
        await fetchSurvey(); // Refresh survey data
        toast({
          title: 'Survey Updated',
          description: 'Your survey has been updated successfully.'
        });
        return { success: true };
      } else {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Failed to update survey');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      toast({
        title: 'Update Failed',
        description: errorMessage,
        variant: 'destructive'
      });
      return { success: false, error: { code: 'UPDATE_FAILED', message: errorMessage } };
    }
  }, [surveyId, fetchSurvey]);

  const publishSurvey = useCallback(async (): Promise<SurveyOperationResult> => {
    if (!surveyId) {
      return { success: false, error: { code: 'NO_SURVEY_ID', message: 'No survey ID provided' } };
    }

    try {
      const response = await api.post(`/api/v1/surveys/${surveyId}/publish`);
      
      if (response.ok) {
        await fetchSurvey();
        toast({
          title: 'Survey Published',
          description: 'Your survey is now active and ready for responses.'
        });
        return { success: true };
      } else {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Failed to publish survey');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      toast({
        title: 'Publish Failed',
        description: errorMessage,
        variant: 'destructive'
      });
      return { success: false, error: { code: 'PUBLISH_FAILED', message: errorMessage } };
    }
  }, [surveyId, fetchSurvey]);

  const deleteSurvey = useCallback(async (): Promise<SurveyOperationResult> => {
    if (!surveyId) {
      return { success: false, error: { code: 'NO_SURVEY_ID', message: 'No survey ID provided' } };
    }

    try {
      const response = await api.delete(`/api/v1/surveys/${surveyId}`);
      
      if (response.ok) {
        toast({
          title: 'Survey Deleted',
          description: 'The survey has been deleted successfully.'
        });
        router.push('/surveys');
        return { success: true };
      } else {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Failed to delete survey');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      toast({
        title: 'Delete Failed',
        description: errorMessage,
        variant: 'destructive'
      });
      return { success: false, error: { code: 'DELETE_FAILED', message: errorMessage } };
    }
  }, [surveyId, router]);

  return {
    survey,
    loading,
    error,
    updateSurvey,
    publishSurvey,
    deleteSurvey,
    refetch: fetchSurvey
  };
}

// Survey Builder Hook
export function useSurveyBuilder(initialSurvey?: Partial<Survey>) {
  const [state, setState] = useState<SurveyBuilderState>({
    survey: initialSurvey || {
      title: '',
      description: '',
      category: 'demographic_survey',
      settings: {
        theme: {
          primary_color: '#2563eb',
          secondary_color: '#64748b',
          font_family: 'Inter'
        },
        validation: {
          require_all_questions: true,
          email_validation: false,
          phone_validation: false
        }
      }
    },
    questions: initialSurvey?.questions || [],
    current_question_index: 0,
    preview_mode: false,
    unsaved_changes: false,
    validation_errors: {}
  });

  const router = useRouter();

  const updateSurvey = useCallback((updates: Partial<Survey>) => {
    setState(prev => ({
      ...prev,
      survey: { ...prev.survey, ...updates },
      unsaved_changes: true
    }));
  }, []);

  const addQuestion = useCallback((question: Partial<SurveyQuestion>) => {
    const newQuestion: SurveyQuestion = {
      id: `temp_${Date.now()}`,
      survey_id: state.survey.id || '',
      question_text: question.question_text || '',
      question_type: question.question_type || 'text',
      description: question.description,
      options: question.options || {},
      validation_rules: question.validation_rules || {},
      conditional_logic: question.conditional_logic,
      neuroimaging_context: question.neuroimaging_context,
      cognitive_domain: question.cognitive_domain,
      order_index: state.questions.length,
      required: question.required || false,
      randomize_options: question.randomize_options || false
    };

    setState(prev => ({
      ...prev,
      questions: [...prev.questions, newQuestion],
      current_question_index: prev.questions.length,
      unsaved_changes: true
    }));
  }, [state.survey.id, state.questions.length]);

  const updateQuestion = useCallback((index: number, updates: Partial<SurveyQuestion>) => {
    setState(prev => ({
      ...prev,
      questions: prev.questions.map((q, i) => 
        i === index ? { ...q, ...updates } : q
      ),
      unsaved_changes: true
    }));
  }, []);

  const removeQuestion = useCallback((index: number) => {
    setState(prev => ({
      ...prev,
      questions: prev.questions.filter((_, i) => i !== index),
      current_question_index: Math.max(0, prev.current_question_index - (index <= prev.current_question_index ? 1 : 0)),
      unsaved_changes: true
    }));
  }, []);

  const reorderQuestions = useCallback((fromIndex: number, toIndex: number) => {
    setState(prev => {
      const questions = [...prev.questions];
      const [removed] = questions.splice(fromIndex, 1);
      questions.splice(toIndex, 0, removed);
      
      // Update order_index for all questions
      questions.forEach((question, index) => {
        question.order_index = index;
      });

      return {
        ...prev,
        questions,
        unsaved_changes: true
      };
    });
  }, []);

  const setCurrentQuestion = useCallback((index: number) => {
    setState(prev => ({
      ...prev,
      current_question_index: Math.max(0, Math.min(index, prev.questions.length - 1))
    }));
  }, []);

  const togglePreview = useCallback(() => {
    setState(prev => ({ ...prev, preview_mode: !prev.preview_mode }));
  }, []);

  const validateSurvey = useCallback((): boolean => {
    const errors: Record<string, string> = {};

    if (!state.survey.title?.trim()) {
      errors.title = 'Survey title is required';
    }

    if (!state.survey.category) {
      errors.category = 'Survey category is required';
    }

    if (state.questions.length === 0) {
      errors.questions = 'At least one question is required';
    }

    // Validate individual questions
    state.questions.forEach((question, index) => {
      if (!question.question_text?.trim()) {
        errors[`question_${index}_text`] = `Question ${index + 1} text is required`;
      }
    });

    setState(prev => ({ ...prev, validation_errors: errors }));
    return Object.keys(errors).length === 0;
  }, [state.survey, state.questions]);

  const saveSurvey = useCallback(async (): Promise<SurveyOperationResult> => {
    if (!validateSurvey()) {
      return { success: false, error: { code: 'VALIDATION_FAILED', message: 'Please fix validation errors' } };
    }

    try {
      const surveyData: CreateSurveyRequest = {
        title: state.survey.title!,
        description: state.survey.description,
        category: state.survey.category!,
        questions: state.questions.map(q => ({
          question_text: q.question_text,
          question_type: q.question_type,
          description: q.description,
          options: q.options,
          validation_rules: q.validation_rules,
          conditional_logic: q.conditional_logic,
          neuroimaging_context: q.neuroimaging_context,
          cognitive_domain: q.cognitive_domain,
          required: q.required,
          randomize_options: q.randomize_options
        })),
        settings: state.survey.settings,
        target_audience: state.survey.target_audience
      };

      const response = state.survey.id 
        ? await api.put(`/api/v1/surveys/${state.survey.id}`, surveyData)
        : await api.post('/api/v1/surveys', surveyData);

      if (response.ok) {
        const result = await response.json();
        setState(prev => ({ ...prev, unsaved_changes: false }));
        
        toast({
          title: 'Survey Saved',
          description: 'Your survey has been saved successfully.'
        });

        if (!state.survey.id) {
          router.push(`/surveys/${result.survey_id}/edit`);
        }

        return { success: true, data: result };
      } else {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Failed to save survey');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      toast({
        title: 'Save Failed',
        description: errorMessage,
        variant: 'destructive'
      });
      return { success: false, error: { code: 'SAVE_FAILED', message: errorMessage } };
    }
  }, [state, validateSurvey, router]);

  const loadFromTemplate = useCallback((template: SurveyTemplate) => {
    setState(prev => ({
      ...prev,
      survey: {
        ...prev.survey,
        title: template.name,
        description: template.description,
        category: template.category,
        settings: template.default_settings
      },
      questions: template.template_questions.map((tq, index) => ({
        id: `template_${index}`,
        survey_id: prev.survey.id || '',
        question_text: tq.question_text,
        question_type: tq.question_type,
        description: tq.description,
        options: tq.options,
        validation_rules: tq.validation_rules,
        neuroimaging_context: tq.neuroimaging_context,
        order_index: index,
        required: tq.required,
        randomize_options: false,
        conditional_logic: undefined,
        cognitive_domain: undefined
      })),
      unsaved_changes: true
    }));
  }, []);

  return {
    state,
    updateSurvey,
    addQuestion,
    updateQuestion,
    removeQuestion,
    reorderQuestions,
    setCurrentQuestion,
    togglePreview,
    validateSurvey,
    saveSurvey,
    loadFromTemplate
  };
}

// Survey Response Hook
export function useSurveyResponse(survey: Survey) {
  const [responses, setResponses] = useState<Record<string, any>>({});
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  
  const questions = useMemo(() => survey.questions || [], [survey.questions]);
  const currentQuestion = questions[currentQuestionIndex];
  const isLastQuestion = currentQuestionIndex === questions.length - 1;
  const canProceed = useMemo(() => {
    if (!currentQuestion) return true;
    
    const hasResponse = responses[currentQuestion.id] !== undefined && responses[currentQuestion.id] !== '';
    const isRequired = currentQuestion.required;
    
    return !isRequired || hasResponse;
  }, [currentQuestion, responses]);

  const updateResponse = useCallback((questionId: string, value: any) => {
    setResponses(prev => ({ ...prev, [questionId]: value }));
    setErrors(prev => ({ ...prev, [questionId]: '' })); // Clear error when user responds
  }, []);

  const validateCurrentQuestion = useCallback((): boolean => {
    if (!currentQuestion) return true;

    const value = responses[currentQuestion.id];
    const rules = currentQuestion.validation_rules;
    let error = '';

    // Required validation
    if (currentQuestion.required && (value === undefined || value === '' || (Array.isArray(value) && value.length === 0))) {
      error = 'This question is required';
    }

    // Type-specific validation
    if (value !== undefined && value !== '') {
      // Number validation
      if (currentQuestion.question_type === 'scale' && typeof value === 'string') {
        const numValue = parseFloat(value);
        if (isNaN(numValue)) {
          error = 'Please enter a valid number';
        } else {
          if (rules.min_value !== undefined && numValue < rules.min_value) {
            error = `Value must be at least ${rules.min_value}`;
          }
          if (rules.max_value !== undefined && numValue > rules.max_value) {
            error = `Value must be at most ${rules.max_value}`;
          }
        }
      }

      // Text length validation
      if (currentQuestion.question_type === 'text' || currentQuestion.question_type === 'textarea') {
        const textValue = String(value);
        const minLength = currentQuestion.options.min_length;
        const maxLength = currentQuestion.options.max_length;

        if (minLength && textValue.length < minLength) {
          error = `Response must be at least ${minLength} characters`;
        }
        if (maxLength && textValue.length > maxLength) {
          error = `Response must be at most ${maxLength} characters`;
        }
      }

      // Regex validation
      if (rules.regex_pattern && typeof value === 'string') {
        const regex = new RegExp(rules.regex_pattern);
        if (!regex.test(value)) {
          error = rules.custom_message || 'Invalid format';
        }
      }
    }

    if (error) {
      setErrors(prev => ({ ...prev, [currentQuestion.id]: error }));
      return false;
    }

    return true;
  }, [currentQuestion, responses]);

  const goToNextQuestion = useCallback(() => {
    if (validateCurrentQuestion() && currentQuestionIndex < questions.length - 1) {
      setCurrentQuestionIndex(prev => prev + 1);
    }
  }, [currentQuestionIndex, questions.length, validateCurrentQuestion]);

  const goToPreviousQuestion = useCallback(() => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(prev => prev - 1);
    }
  }, [currentQuestionIndex]);

  const goToQuestion = useCallback((index: number) => {
    if (index >= 0 && index < questions.length) {
      setCurrentQuestionIndex(index);
    }
  }, [questions.length]);

  const submitResponse = useCallback(async (): Promise<SurveyOperationResult> => {
    // Validate all required questions are answered
    const missingRequired = questions
      .filter(q => q.required)
      .filter(q => responses[q.id] === undefined || responses[q.id] === '');

    if (missingRequired.length > 0) {
      toast({
        title: 'Incomplete Survey',
        description: `Please answer all required questions (${missingRequired.length} remaining)`,
        variant: 'destructive'
      });
      return { success: false, error: { code: 'INCOMPLETE', message: 'Required questions not answered' } };
    }

    setSubmitting(true);

    try {
      const responseData: SubmitResponseRequest = {
        survey_id: survey.id,
        responses,
        metadata: {
          completion_time_seconds: Math.floor(Date.now() / 1000), // Simple completion tracking
          device_type: /Mobile|Android|iPhone|iPad/.test(navigator.userAgent) ? 'mobile' : 'desktop',
          browser: navigator.userAgent
        },
        session_data: {
          session_id: `session_${Date.now()}`,
          user_agent: navigator.userAgent,
          referrer: document.referrer
        }
      };

      const response = await api.post('/api/v1/surveys/responses', responseData);

      if (response.ok) {
        const result = await response.json();
        toast({
          title: 'Survey Submitted',
          description: 'Thank you for your response!'
        });
        return { success: true, data: result };
      } else {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Failed to submit response');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      toast({
        title: 'Submission Failed',
        description: errorMessage,
        variant: 'destructive'
      });
      return { success: false, error: { code: 'SUBMIT_FAILED', message: errorMessage } };
    } finally {
      setSubmitting(false);
    }
  }, [survey.id, questions, responses]);

  const progressPercentage = useMemo(() => {
    if (questions.length === 0) return 0;
    return Math.round(((currentQuestionIndex + 1) / questions.length) * 100);
  }, [currentQuestionIndex, questions.length]);

  const answeredCount = useMemo(() => {
    return questions.filter(q => responses[q.id] !== undefined && responses[q.id] !== '').length;
  }, [questions, responses]);

  return {
    responses,
    currentQuestionIndex,
    currentQuestion,
    isLastQuestion,
    canProceed,
    submitting,
    errors,
    progressPercentage,
    answeredCount,
    totalQuestions: questions.length,
    updateResponse,
    goToNextQuestion,
    goToPreviousQuestion,
    goToQuestion,
    validateCurrentQuestion,
    submitResponse
  };
}

// Survey Analytics Hook
export function useSurveyAnalytics(surveyIds: string[], dateRange?: { start: string; end: string }) {
  const [analytics, setAnalytics] = useState<Record<string, any>>({});
  const [insights, setInsights] = useState<SurveyInsight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAnalytics = useCallback(async () => {
    if (surveyIds.length === 0) return;

    setLoading(true);
    setError(null);

    try {
      const requestData = {
        survey_ids: surveyIds,
        date_range: dateRange,
        metrics: ['response_rate', 'completion_rate', 'insights', 'demographics']
      };

      const response = await api.post('/api/v1/surveys/analytics', requestData);

      if (response.ok) {
        const data = await response.json();
        setAnalytics(data.analytics);
      } else {
        throw new Error('Failed to fetch analytics');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [surveyIds, dateRange]);

  const fetchInsights = useCallback(async (surveyId: string, insightType?: string) => {
    try {
      const params = insightType ? `?insight_type=${insightType}` : '';
      const response = await api.get(`/api/v1/surveys/${surveyId}/insights${params}`);

      if (response.ok) {
        const data = await response.json();
        setInsights(data.insights);
      }
    } catch (err) {
      console.error('Failed to fetch insights:', err);
    }
  }, []);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  return {
    analytics,
    insights,
    loading,
    error,
    fetchInsights,
    refetch: fetchAnalytics
  };
}

// Survey Templates Hook
export function useSurveyTemplates() {
  const [templates, setTemplates] = useState<SurveyTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTemplates = useCallback(async (category?: string, neuroimagingFocus?: string) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (category) params.append('category', category);
      if (neuroimagingFocus) params.append('neuroimaging_focus', neuroimagingFocus);

      const response = await api.get(`/api/v1/surveys/templates?${params}`);

      if (response.ok) {
        const data = await response.json();
        setTemplates(data);
      } else {
        throw new Error('Failed to fetch templates');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  return {
    templates,
    loading,
    error,
    fetchTemplates
  };
}

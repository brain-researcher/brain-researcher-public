/**
 * Survey Renderer Component
 * Core component for displaying surveys to respondents with neuroimaging-specific features
 */

'use client';

import React, { useState, useEffect } from 'react';
import { Brain, AlertCircle, CheckCircle, Info, Clock } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';

import { Survey, SurveyQuestion } from '@/types/survey';
import { QuestionRenderer } from './QuestionRenderer';
import { ProgressIndicator } from './ProgressIndicator';

interface SurveyRendererProps {
  survey: Survey;
  currentQuestionIndex?: number;
  responses: Record<string, any>;
  onResponseChange: (questionId: string, value: any) => void;
  mode?: 'survey' | 'preview' | 'review';
  readonly?: boolean;
  showProgress?: boolean;
  theme?: {
    primaryColor?: string;
    secondaryColor?: string;
    fontFamily?: string;
  };
}

export function SurveyRenderer({ 
  survey, 
  currentQuestionIndex = 0,
  responses, 
  onResponseChange,
  mode = 'survey',
  readonly = false,
  showProgress = true,
  theme
}: SurveyRendererProps) {
  const [startTime, setStartTime] = useState<Date | null>(null);
  const [questionStartTime, setQuestionStartTime] = useState<Date | null>(null);

  const questions = survey.questions || [];
  const currentQuestion = questions[currentQuestionIndex];
  const totalQuestions = questions.length;

  // Track timing
  useEffect(() => {
    if (!startTime) {
      setStartTime(new Date());
    }
    setQuestionStartTime(new Date());
  }, [currentQuestionIndex]);

  // Apply theme
  const themeStyles = {
    '--primary-color': theme?.primaryColor || survey.settings?.theme?.primary_color || '#2563eb',
    '--secondary-color': theme?.secondaryColor || survey.settings?.theme?.secondary_color || '#64748b',
    '--font-family': theme?.fontFamily || survey.settings?.theme?.font_family || 'Inter'
  } as React.CSSProperties;

  const handleResponseChange = (questionId: string, value: any, metadata?: Record<string, any>) => {
    const responseTime = questionStartTime ? new Date().getTime() - questionStartTime.getTime() : 0;
    
    // Add timing metadata
    const enrichedMetadata = {
      ...metadata,
      response_time_ms: responseTime,
      timestamp: new Date().toISOString(),
      question_index: currentQuestionIndex
    };

    onResponseChange(questionId, value);

    // Store metadata separately if needed
    if (mode === 'survey') {
      // Could emit analytics event here
      console.log('Response metadata:', enrichedMetadata);
    }
  };

  const getCompletionPercentage = () => {
    if (totalQuestions === 0) return 0;
    return Math.round(((currentQuestionIndex + 1) / totalQuestions) * 100);
  };

  const getAnsweredCount = () => {
    return questions.filter(q => responses[q.id] !== undefined && responses[q.id] !== '').length;
  };

  const renderSurveyHeader = () => {
    if (mode === 'preview') return null;

    return (
      <div className="mb-8">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-bold text-gray-900 mb-3" style={{ fontFamily: themeStyles['--font-family'] }}>
            {survey.title}
          </h1>
          {survey.description && (
            <p className="text-gray-600 max-w-3xl mx-auto text-lg">
              {survey.description}
            </p>
          )}
        </div>

        {/* Survey metadata */}
        <div className="flex justify-center flex-wrap gap-3 mb-6">
          <Badge variant="outline" className="text-sm">
            <Clock className="h-4 w-4 mr-2" />
            ~{Math.ceil(totalQuestions * 1.5)} minutes
          </Badge>
          <Badge variant="outline" className="text-sm">
            {totalQuestions} questions
          </Badge>
          {survey.neuroimaging_context?.imaging_modalities && (
            <Badge variant="outline" className="text-sm">
              <Brain className="h-4 w-4 mr-2" />
              {survey.neuroimaging_context.imaging_modalities.join(', ')}
            </Badge>
          )}
          {survey.settings?.privacy?.anonymous_responses && (
            <Badge variant="outline" className="text-sm text-green-600">
              <CheckCircle className="h-4 w-4 mr-2" />
              Anonymous
            </Badge>
          )}
        </div>

        {/* Privacy notice */}
        {survey.settings?.privacy?.gdpr_compliant && mode === 'survey' && (
          <Alert className="mb-6">
            <Info className="h-4 w-4" />
            <AlertDescription>
              Your responses are collected in accordance with privacy regulations. 
              {survey.settings.privacy.anonymous_responses && ' No personal identifying information is collected.'}
              {survey.settings.privacy.data_retention_days && 
                ` Data will be retained for ${survey.settings.privacy.data_retention_days} days.`
              }
            </AlertDescription>
          </Alert>
        )}
      </div>
    );
  };

  const renderProgress = () => {
    if (!showProgress || mode === 'review') return null;

    return (
      <div className="mb-8">
        <ProgressIndicator
          currentQuestion={currentQuestionIndex + 1}
          totalQuestions={totalQuestions}
          answeredCount={getAnsweredCount()}
          showPercentage={true}
        />
      </div>
    );
  };

  const renderNeuroimagingContext = () => {
    if (!currentQuestion?.neuroimaging_context || mode === 'preview') return null;

    const context = currentQuestion.neuroimaging_context;
    
    return (
      <Alert className="mb-6 border-blue-200 bg-blue-50">
        <Brain className="h-4 w-4 text-blue-600" />
        <AlertDescription>
          <div className="font-medium text-blue-900 mb-2">Neuroimaging Context</div>
          <div className="text-sm text-blue-800 space-y-1">
            <div>Category: {context.category?.replace('_', ' ')}</div>
            {context.required_for && (
              <div>Required for: {context.required_for.join(', ')}</div>
            )}
            {context.statistical_covariates && (
              <div>This information will be used in statistical analysis</div>
            )}
            {context.synchronized_with_imaging && (
              <div>This data should be collected during or immediately after scanning</div>
            )}
          </div>
        </AlertDescription>
      </Alert>
    );
  };

  const renderCurrentQuestion = () => {
    if (!currentQuestion) {
      return (
        <Card>
          <CardContent className="pt-6 text-center">
            <AlertCircle className="h-12 w-12 mx-auto mb-4 text-gray-400" />
            <h3 className="text-lg font-semibold mb-2">No questions available</h3>
            <p className="text-gray-600">This survey appears to be empty.</p>
          </CardContent>
        </Card>
      );
    }

    return (
      <div className="space-y-6">
        {/* Neuroimaging Context */}
        {renderNeuroimagingContext()}

        {/* Question Card */}
        <Card className="shadow-lg border-0" style={{ borderTop: `4px solid ${themeStyles['--primary-color']}` }}>
          <CardHeader className="pb-4">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-3">
                  <Badge variant="outline" className="text-sm">
                    Question {currentQuestionIndex + 1} of {totalQuestions}
                  </Badge>
                  {currentQuestion.required && (
                    <Badge variant="destructive" className="text-sm">
                      Required
                    </Badge>
                  )}
                  {currentQuestion.neuroimaging_context && (
                    <Badge variant="outline" className="text-sm">
                      <Brain className="h-3 w-3 mr-1" />
                      Neuroimaging
                    </Badge>
                  )}
                </div>
                <CardTitle className="text-xl leading-relaxed" style={{ fontFamily: themeStyles['--font-family'] }}>
                  {currentQuestion.question_text}
                  {currentQuestion.required && <span className="text-red-500 ml-1">*</span>}
                </CardTitle>
                {currentQuestion.description && (
                  <p className="text-gray-600 mt-3 leading-relaxed">
                    {currentQuestion.description}
                  </p>
                )}
              </div>
            </div>
          </CardHeader>

          <CardContent>
            <QuestionRenderer
              question={currentQuestion}
              value={responses[currentQuestion.id]}
              onChange={(value, metadata) => handleResponseChange(currentQuestion.id, value, metadata)}
              readonly={readonly}
              theme={theme}
            />

            {/* Validation feedback */}
            {currentQuestion.required && 
             responses[currentQuestion.id] === undefined && 
             mode === 'survey' && (
              <Alert variant="destructive" className="mt-4">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  This question is required. Please provide an answer to continue.
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        {/* Question-specific help */}
        {currentQuestion.neuroimaging_context?.category === 'acquisition_parameters' && (
          <Alert>
            <Info className="h-4 w-4" />
            <AlertDescription>
              <div className="font-medium mb-2">Acquisition Parameter Guidelines</div>
              <ul className="text-sm space-y-1">
                <li>• Provide exact parameter values when possible</li>
                <li>• Check your scanning protocol or ask your MR technician if unsure</li>
                <li>• These parameters are crucial for data quality assessment</li>
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {currentQuestion.neuroimaging_context?.category === 'quality_assessment' && (
          <Alert>
            <Info className="h-4 w-4" />
            <AlertDescription>
              <div className="font-medium mb-2">Quality Assessment Tips</div>
              <ul className="text-sm space-y-1">
                <li>• Consider motion artifacts, signal dropout, and coverage</li>
                <li>• Rate based on suitability for your analysis goals</li>
                <li>• When in doubt, err on the side of caution</li>
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </div>
    );
  };

  const renderReviewMode = () => {
    if (mode !== 'review') return null;

    return (
      <div className="space-y-6">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-bold mb-2">Review Your Responses</h2>
          <p className="text-gray-600">Please review your answers before submitting</p>
        </div>

        {questions.map((question, index) => (
          <Card key={question.id} className="shadow-sm">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="outline">Q{index + 1}</Badge>
                    {question.required && (
                      <Badge variant="destructive" className="text-xs">Required</Badge>
                    )}
                    {question.neuroimaging_context && (
                      <Badge variant="outline" className="text-xs">
                        <Brain className="h-3 w-3 mr-1" />
                        Neuroimaging
                      </Badge>
                    )}
                  </div>
                  <CardTitle className="text-base">{question.question_text}</CardTitle>
                </div>
                <div className="text-right text-sm">
                  {responses[question.id] !== undefined ? (
                    <CheckCircle className="h-5 w-5 text-green-600" />
                  ) : (
                    <AlertCircle className="h-5 w-5 text-red-500" />
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <QuestionRenderer
                question={question}
                value={responses[question.id]}
                onChange={() => {}} // No changes in review mode
                readonly={true}
                theme={theme}
              />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  };

  if (totalQuestions === 0) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="h-16 w-16 mx-auto mb-4 text-gray-400" />
        <h3 className="text-xl font-semibold mb-2">Survey Not Available</h3>
        <p className="text-gray-600">This survey appears to be empty or not properly configured.</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto" style={themeStyles}>
      {renderSurveyHeader()}
      {renderProgress()}
      {mode === 'review' ? renderReviewMode() : renderCurrentQuestion()}
    </div>
  );
}
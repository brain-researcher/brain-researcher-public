/**
 * Survey Preview Component
 * Preview mode for surveys showing how they will appear to respondents
 */

'use client';

import React, { useState } from 'react';
import { 
  Eye, 
  Smartphone, 
  Monitor, 
  Tablet,
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  AlertCircle
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { Survey, SurveyQuestion } from '@/types/survey';
import { SurveyRenderer } from './display/SurveyRenderer';

interface SurveyPreviewProps {
  survey: Partial<Survey>;
  mode?: 'builder' | 'standalone';
}

type DeviceType = 'mobile' | 'tablet' | 'desktop';

export function SurveyPreview({ survey, mode = 'builder' }: SurveyPreviewProps) {
  const [deviceType, setDeviceType] = useState<DeviceType>('desktop');
  const [currentStep, setCurrentStep] = useState(0);
  const [responses, setResponses] = useState<Record<string, any>>({});

  const questions = survey.questions || [];
  const currentQuestion = questions[currentStep];
  const isLastQuestion = currentStep === questions.length - 1;
  const progressPercentage = questions.length > 0 ? ((currentStep + 1) / questions.length) * 100 : 0;

  const getDeviceClass = () => {
    switch (deviceType) {
      case 'mobile':
        return 'max-w-sm mx-auto';
      case 'tablet':
        return 'max-w-2xl mx-auto';
      case 'desktop':
      default:
        return 'max-w-4xl mx-auto';
    }
  };

  const getDeviceIcon = (type: DeviceType) => {
    const iconProps = { className: `h-4 w-4 ${deviceType === type ? 'text-blue-600' : 'text-gray-400'}` };
    switch (type) {
      case 'mobile':
        return <Smartphone {...iconProps} />;
      case 'tablet':
        return <Tablet {...iconProps} />;
      case 'desktop':
        return <Monitor {...iconProps} />;
    }
  };

  const handleResponseChange = (questionId: string, value: any) => {
    setResponses(prev => ({ ...prev, [questionId]: value }));
  };

  const validateCurrentQuestion = (): boolean => {
    if (!currentQuestion) return true;
    
    const hasResponse = responses[currentQuestion.id] !== undefined && responses[currentQuestion.id] !== '';
    return !currentQuestion.required || hasResponse;
  };

  const goToNext = () => {
    if (validateCurrentQuestion() && currentStep < questions.length - 1) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const goToPrevious = () => {
    if (currentStep > 0) {
      setCurrentStep(prev => prev - 1);
    }
  };

  const renderSurveyHeader = () => (
    <div className="text-center mb-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">
        {survey.title || 'Untitled Survey'}
      </h1>
      {survey.description && (
        <p className="text-gray-600 max-w-2xl mx-auto">
          {survey.description}
        </p>
      )}
      
      {/* Survey metadata */}
      <div className="flex justify-center gap-3 mt-4">
        <Badge variant="outline">
          {survey.category?.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
        </Badge>
        {survey.neuroimaging_context?.imaging_modalities && (
          <Badge variant="outline">
            {survey.neuroimaging_context.imaging_modalities.join(', ')}
          </Badge>
        )}
        <Badge variant="outline">
          {questions.length} Questions
        </Badge>
        <Badge variant="outline">
          ~{Math.ceil(questions.length * 1.5)} min
        </Badge>
      </div>
    </div>
  );

  const renderProgressBar = () => (
    <div className="mb-6">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm text-gray-600">
          Question {currentStep + 1} of {questions.length}
        </span>
        <span className="text-sm text-gray-600">
          {Math.round(progressPercentage)}% Complete
        </span>
      </div>
      <Progress value={progressPercentage} className="h-2" />
    </div>
  );

  const renderNavigationButtons = () => (
    <div className="flex justify-between items-center mt-8">
      <Button
        variant="outline"
        onClick={goToPrevious}
        disabled={currentStep === 0}
      >
        <ArrowLeft className="h-4 w-4 mr-2" />
        Previous
      </Button>

      <div className="text-sm text-gray-500">
        {questions.filter(q => responses[q.id] !== undefined).length} of {questions.length} answered
      </div>

      {isLastQuestion ? (
        <Button className="bg-green-600 hover:bg-green-700">
          <CheckCircle className="h-4 w-4 mr-2" />
          Submit Survey
        </Button>
      ) : (
        <Button
          onClick={goToNext}
          disabled={!validateCurrentQuestion()}
        >
          Next
          <ArrowRight className="h-4 w-4 ml-2" />
        </Button>
      )}
    </div>
  );

  const renderValidationErrors = () => {
    const errors = [];
    
    if (questions.length === 0) {
      errors.push('Survey has no questions');
    }
    
    if (!survey.title) {
      errors.push('Survey title is missing');
    }

    const requiredQuestionsWithoutText = questions.filter(q => 
      q.required && !q.question_text?.trim()
    );
    if (requiredQuestionsWithoutText.length > 0) {
      errors.push(`${requiredQuestionsWithoutText.length} required questions have no text`);
    }

    if (errors.length === 0) return null;

    return (
      <Alert variant="destructive" className="mb-6">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          <div className="font-semibold">Preview Issues:</div>
          <ul className="list-disc list-inside text-sm mt-2">
            {errors.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </AlertDescription>
      </Alert>
    );
  };

  const renderDeviceSelector = () => (
    <div className="flex items-center justify-center gap-2 mb-6">
      <span className="text-sm text-gray-600 mr-2">Preview on:</span>
      {(['desktop', 'tablet', 'mobile'] as DeviceType[]).map(device => (
        <Button
          key={device}
          variant={deviceType === device ? 'default' : 'outline'}
          size="sm"
          onClick={() => setDeviceType(device)}
        >
          {getDeviceIcon(device)}
          <span className="ml-2 capitalize">{device}</span>
        </Button>
      ))}
    </div>
  );

  if (questions.length === 0) {
    return (
      <div className="text-center py-12">
        <Eye className="h-16 w-16 mx-auto mb-4 text-gray-400" />
        <h3 className="text-xl font-semibold mb-2">No questions to preview</h3>
        <p className="text-gray-600 mb-6">Add some questions to see how your survey will look</p>
        {mode === 'builder' && (
          <Button variant="outline">
            Go back to add questions
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <Eye className="h-6 w-6" />
            Survey Preview
          </h2>
          <p className="text-gray-600">See how your survey will appear to respondents</p>
        </div>
      </div>

      {/* Device Selector */}
      {renderDeviceSelector()}

      {/* Validation Errors */}
      {renderValidationErrors()}

      {/* Preview Container */}
      <div className={`${getDeviceClass()} transition-all duration-300`}>
        {deviceType === 'mobile' && (
          <div className="bg-gray-900 rounded-t-3xl p-4">
            <div className="bg-white rounded-2xl overflow-hidden shadow-2xl">
              <div className="px-6 py-8">
                {renderSurveyHeader()}
                {renderProgressBar()}
                
                {currentQuestion && (
                  <SurveyRenderer
                    survey={survey as Survey}
                    currentQuestionIndex={currentStep}
                    responses={responses}
                    onResponseChange={handleResponseChange}
                    mode="preview"
                  />
                )}
                
                {renderNavigationButtons()}
              </div>
            </div>
          </div>
        )}

        {deviceType === 'tablet' && (
          <div className="bg-gray-800 rounded-3xl p-6">
            <div className="bg-white rounded-2xl overflow-hidden shadow-2xl">
              <div className="px-8 py-10">
                {renderSurveyHeader()}
                {renderProgressBar()}
                
                {currentQuestion && (
                  <SurveyRenderer
                    survey={survey as Survey}
                    currentQuestionIndex={currentStep}
                    responses={responses}
                    onResponseChange={handleResponseChange}
                    mode="preview"
                  />
                )}
                
                {renderNavigationButtons()}
              </div>
            </div>
          </div>
        )}

        {deviceType === 'desktop' && (
          <Card className="shadow-lg">
            <CardHeader className="text-center">
              {renderSurveyHeader()}
            </CardHeader>
            <CardContent>
              {renderProgressBar()}
              
              {currentQuestion && (
                <SurveyRenderer
                  survey={survey as Survey}
                  currentQuestionIndex={currentStep}
                  responses={responses}
                  onResponseChange={handleResponseChange}
                  mode="preview"
                />
              )}
              
              {renderNavigationButtons()}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Preview Statistics */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Preview Summary</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-600">{questions.length}</div>
            <div className="text-sm text-gray-600">Total Questions</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">
              {questions.filter(q => q.required).length}
            </div>
            <div className="text-sm text-gray-600">Required</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-purple-600">
              {questions.filter(q => q.neuroimaging_context).length}
            </div>
            <div className="text-sm text-gray-600">Neuroimaging</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-orange-600">
              ~{Math.ceil(questions.length * 1.5)}
            </div>
            <div className="text-sm text-gray-600">Est. Minutes</div>
          </div>
        </CardContent>
      </Card>

      {/* Question List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Question Flow</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {questions.map((question, index) => (
              <div
                key={question.id}
                className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                  index === currentStep 
                    ? 'bg-blue-50 border border-blue-200' 
                    : 'bg-gray-50 hover:bg-gray-100'
                }`}
                onClick={() => setCurrentStep(index)}
              >
                <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                  index === currentStep
                    ? 'bg-blue-600 text-white'
                    : responses[question.id] !== undefined
                      ? 'bg-green-600 text-white'
                      : 'bg-gray-300 text-gray-600'
                }`}>
                  {index + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm">
                      {question.question_text || 'Untitled Question'}
                    </span>
                    {question.required && (
                      <Badge variant="destructive" className="text-xs">Required</Badge>
                    )}
                    {question.neuroimaging_context && (
                      <Badge variant="outline" className="text-xs">Neuroimaging</Badge>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">
                    {question.question_type.replace('_', ' ')} question
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
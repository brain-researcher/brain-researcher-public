/**
 * Progress Indicator Component
 * Visual progress indicator for survey completion
 */

'use client';

import React from 'react';
import { CheckCircle, Circle, Clock } from 'lucide-react';

import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';

interface ProgressIndicatorProps {
  currentQuestion: number;
  totalQuestions: number;
  answeredCount: number;
  showPercentage?: boolean;
  showQuestionNumbers?: boolean;
  showTimeEstimate?: boolean;
  estimatedMinutesPerQuestion?: number;
  className?: string;
}

export function ProgressIndicator({
  currentQuestion,
  totalQuestions,
  answeredCount,
  showPercentage = true,
  showQuestionNumbers = true,
  showTimeEstimate = false,
  estimatedMinutesPerQuestion = 1.5,
  className = ''
}: ProgressIndicatorProps) {
  const progressPercentage = totalQuestions > 0 ? (currentQuestion / totalQuestions) * 100 : 0;
  const completionPercentage = totalQuestions > 0 ? (answeredCount / totalQuestions) * 100 : 0;
  const remainingQuestions = totalQuestions - currentQuestion;
  const estimatedTimeRemaining = Math.ceil(remainingQuestions * estimatedMinutesPerQuestion);

  const getProgressColor = () => {
    if (completionPercentage >= 80) return 'text-green-600';
    if (completionPercentage >= 50) return 'text-blue-600';
    if (completionPercentage >= 25) return 'text-yellow-600';
    return 'text-gray-600';
  };

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Main Progress Bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          {showQuestionNumbers && (
            <div className="text-sm font-medium text-gray-700">
              Question {currentQuestion} of {totalQuestions}
            </div>
          )}
          
          {showPercentage && (
            <div className={`text-sm font-medium ${getProgressColor()}`}>
              {Math.round(progressPercentage)}% Complete
            </div>
          )}
        </div>
        
        <Progress 
          value={progressPercentage} 
          className="h-3"
        />
      </div>

      {/* Additional Info */}
      <div className="flex items-center justify-between text-sm">
        {/* Answered Count */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-green-600" />
            <span className="text-gray-600">
              {answeredCount} answered
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <Circle className="h-4 w-4 text-gray-400" />
            <span className="text-gray-600">
              {totalQuestions - answeredCount} remaining
            </span>
          </div>
        </div>

        {/* Time Estimate */}
        {showTimeEstimate && estimatedTimeRemaining > 0 && (
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-gray-400" />
            <span className="text-gray-600">
              ~{estimatedTimeRemaining} min remaining
            </span>
          </div>
        )}
      </div>

      {/* Completion Status Badges */}
      <div className="flex items-center gap-2">
        {completionPercentage >= 25 && (
          <Badge 
            variant={completionPercentage >= 100 ? 'default' : 'secondary'} 
            className="text-xs"
          >
            {completionPercentage >= 100 ? 'Complete' : '25%+'}
          </Badge>
        )}
        
        {completionPercentage >= 50 && completionPercentage < 100 && (
          <Badge variant="secondary" className="text-xs">
            Halfway
          </Badge>
        )}
        
        {completionPercentage >= 75 && completionPercentage < 100 && (
          <Badge variant="secondary" className="text-xs">
            Almost Done
          </Badge>
        )}
      </div>
    </div>
  );
}
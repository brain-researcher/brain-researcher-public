/**
 * Logic Builder Component
 * Visual builder for survey logic, conditional questions, and branching
 */

'use client';

import React, { useState } from 'react';
import { 
  Plus, 
  Trash2, 
  ArrowRight, 
  GitBranch, 
  Shuffle, 
  Eye, 
  EyeOff,
  Settings,
  AlertTriangle
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { 
  SurveyQuestion, 
  SurveyLogic, 
  ConditionalLogic, 
  SkipLogic, 
  BranchingRule,
  RandomizationSettings
} from '@/types/survey';

interface LogicBuilderProps {
  questions: SurveyQuestion[];
  logic?: SurveyLogic;
  onChange: (logic: SurveyLogic) => void;
}

export function LogicBuilder({ questions, logic, onChange }: LogicBuilderProps) {
  const [activeSection, setActiveSection] = useState<'conditional' | 'skip' | 'branching' | 'randomization'>('conditional');
  const [showPreview, setShowPreview] = useState(false);

  const updateLogic = (updates: Partial<SurveyLogic>) => {
    onChange({ ...logic, ...updates });
  };

  const addConditionalLogic = () => {
    const newRule: ConditionalLogic = {
      condition_id: `condition_${Date.now()}`,
      target_question_id: '',
      operator: 'equals',
      value: '',
      action: 'show'
    };

    updateLogic({
      conditional_questions: [...(logic?.conditional_questions || []), newRule]
    });
  };

  const updateConditionalLogic = (index: number, updates: Partial<ConditionalLogic>) => {
    const conditionalQuestions = [...(logic?.conditional_questions || [])];
    conditionalQuestions[index] = { ...conditionalQuestions[index], ...updates };
    updateLogic({ conditional_questions: conditionalQuestions });
  };

  const removeConditionalLogic = (index: number) => {
    const conditionalQuestions = logic?.conditional_questions?.filter((_, i) => i !== index) || [];
    updateLogic({ conditional_questions: conditionalQuestions });
  };

  const addSkipLogic = () => {
    const newSkip: SkipLogic = {
      question_id: '',
      conditions: [],
      skip_to_question: ''
    };

    updateLogic({
      skip_logic: [...(logic?.skip_logic || []), newSkip]
    });
  };

  const addBranchingRule = () => {
    const newBranch: BranchingRule = {
      rule_id: `branch_${Date.now()}`,
      condition: {
        condition_id: `branch_condition_${Date.now()}`,
        target_question_id: '',
        operator: 'equals',
        value: '',
        action: 'show'
      },
      branch_to: '',
      description: ''
    };

    updateLogic({
      branching: [...(logic?.branching || []), newBranch]
    });
  };

  const getQuestionOptions = () => {
    return questions.map(q => ({
      value: q.id,
      label: `Q${q.order_index + 1}: ${q.question_text.substring(0, 50)}${q.question_text.length > 50 ? '...' : ''}`
    }));
  };

  const getChoiceQuestions = () => {
    return questions.filter(q => 
      ['single_choice', 'multiple_choice', 'scale'].includes(q.question_type)
    );
  };

  const renderConditionalLogic = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Conditional Logic</h3>
          <p className="text-sm text-gray-600">Show or hide questions based on previous answers</p>
        </div>
        <Button onClick={addConditionalLogic} size="sm">
          <Plus className="h-4 w-4 mr-2" />
          Add Rule
        </Button>
      </div>

      {(logic?.conditional_questions || []).length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-center">
            <GitBranch className="h-12 w-12 mx-auto mb-4 text-gray-400" />
            <h3 className="text-lg font-semibold mb-2">No conditional logic yet</h3>
            <p className="text-gray-600 mb-4">Add rules to show/hide questions based on responses</p>
            <Button onClick={addConditionalLogic} variant="outline">
              Add First Rule
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {logic.conditional_questions.map((rule, index) => (
            <Card key={rule.condition_id}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Conditional Rule {index + 1}</CardTitle>
                  <Button
                    onClick={() => removeConditionalLogic(index)}
                    variant="outline"
                    size="sm"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Source Question */}
                <div>
                  <Label>When this question is answered:</Label>
                  <Select
                    value={rule.target_question_id}
                    onValueChange={(value) => updateConditionalLogic(index, { target_question_id: value })}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select question" />
                    </SelectTrigger>
                    <SelectContent>
                      {getChoiceQuestions().map(q => (
                        <SelectItem key={q.id} value={q.id}>
                          Q{q.order_index + 1}: {q.question_text.substring(0, 40)}...
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  {/* Operator */}
                  <div>
                    <Label>Condition</Label>
                    <Select
                      value={rule.operator}
                      onValueChange={(value: any) => updateConditionalLogic(index, { operator: value })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="equals">Equals</SelectItem>
                        <SelectItem value="not_equals">Not Equals</SelectItem>
                        <SelectItem value="contains">Contains</SelectItem>
                        <SelectItem value="greater_than">Greater Than</SelectItem>
                        <SelectItem value="less_than">Less Than</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Value */}
                  <div>
                    <Label>Value</Label>
                    <Select
                      value={rule.value?.toString() || ''}
                      onValueChange={(value) => updateConditionalLogic(index, { value })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select value" />
                      </SelectTrigger>
                      <SelectContent>
                        {rule.target_question_id && (() => {
                          const question = questions.find(q => q.id === rule.target_question_id);
                          if (question?.options?.choices) {
                            return question.options.choices.map(choice => (
                              <SelectItem key={choice.id} value={choice.value?.toString() || choice.text}>
                                {choice.text}
                              </SelectItem>
                            ));
                          }
                          return null;
                        })()}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Action */}
                  <div>
                    <Label>Then</Label>
                    <Select
                      value={rule.action}
                      onValueChange={(value: any) => updateConditionalLogic(index, { action: value })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="show">Show questions</SelectItem>
                        <SelectItem value="hide">Hide questions</SelectItem>
                        <SelectItem value="require">Make required</SelectItem>
                        <SelectItem value="skip">Skip to section</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {/* Preview */}
                <div className="bg-gray-50 p-3 rounded-lg text-sm">
                  <strong>Rule Preview:</strong> When question "{
                    questions.find(q => q.id === rule.target_question_id)?.question_text?.substring(0, 30) || 'selected question'
                  }" {rule.operator} "{rule.value}", then {rule.action} subsequent questions.
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );

  const renderSkipLogic = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Skip Logic</h3>
          <p className="text-sm text-gray-600">Skip sections based on responses</p>
        </div>
        <Button onClick={addSkipLogic} size="sm">
          <Plus className="h-4 w-4 mr-2" />
          Add Skip Rule
        </Button>
      </div>

      {(logic?.skip_logic || []).length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-center">
            <ArrowRight className="h-12 w-12 mx-auto mb-4 text-gray-400" />
            <h3 className="text-lg font-semibold mb-2">No skip logic configured</h3>
            <p className="text-gray-600 mb-4">Add rules to skip sections based on responses</p>
            <Button onClick={addSkipLogic} variant="outline">
              Add Skip Rule
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              Skip logic is coming soon! For now, use conditional logic to show/hide questions.
            </AlertDescription>
          </Alert>
        </div>
      )}
    </div>
  );

  const renderBranchingLogic = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Branching Logic</h3>
          <p className="text-sm text-gray-600">Create different survey paths</p>
        </div>
        <Button onClick={addBranchingRule} size="sm">
          <Plus className="h-4 w-4 mr-2" />
          Add Branch
        </Button>
      </div>

      {(logic?.branching || []).length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-center">
            <GitBranch className="h-12 w-12 mx-auto mb-4 text-gray-400" />
            <h3 className="text-lg font-semibold mb-2">No branching logic yet</h3>
            <p className="text-gray-600 mb-4">Create different survey paths for different respondents</p>
            <Button onClick={addBranchingRule} variant="outline">
              Add First Branch
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              Advanced branching logic is coming soon! Use conditional logic for basic branching.
            </AlertDescription>
          </Alert>
        </div>
      )}
    </div>
  );

  const renderRandomizationSettings = () => (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Randomization Settings</h3>
        <p className="text-sm text-gray-600">Randomize question and answer order</p>
      </div>

      <Card>
        <CardContent className="pt-6 space-y-6">
          {/* Question Randomization */}
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-base">Randomize Question Order</Label>
              <p className="text-sm text-gray-600">Randomize the order of all questions</p>
            </div>
            <Switch
              checked={logic?.randomization?.randomize_questions || false}
              onCheckedChange={(checked) => updateLogic({
                randomization: {
                  ...logic?.randomization,
                  randomize_questions: checked
                }
              })}
            />
          </div>

          <Separator />

          {/* Answer Option Randomization */}
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-base">Randomize Answer Options</Label>
              <p className="text-sm text-gray-600">Randomize choice options within questions</p>
            </div>
            <Switch
              checked={logic?.randomization?.randomize_options || false}
              onCheckedChange={(checked) => updateLogic({
                randomization: {
                  ...logic?.randomization,
                  randomize_options: checked
                }
              })}
            />
          </div>

          {/* Randomization Groups */}
          {logic?.randomization?.randomize_questions && (
            <>
              <Separator />
              <div>
                <Label className="text-base">Randomization Groups</Label>
                <p className="text-sm text-gray-600 mb-4">
                  Group questions to randomize together (advanced feature)
                </p>
                
                <Alert>
                  <Settings className="h-4 w-4" />
                  <AlertDescription>
                    Advanced randomization groups are coming soon. Currently, all questions are randomized together.
                  </AlertDescription>
                </Alert>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Neuroimaging-Specific Randomization */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Neuroimaging Considerations</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              <strong>Note:</strong> When randomizing questions, ensure that demographic and scanner parameter 
              questions appear before neuroimaging-specific questions for optimal data collection flow.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    </div>
  );

  const renderLogicPreview = () => {
    if (!showPreview) return null;

    const hasLogic = 
      (logic?.conditional_questions?.length || 0) > 0 ||
      (logic?.skip_logic?.length || 0) > 0 ||
      (logic?.branching?.length || 0) > 0 ||
      logic?.randomization?.randomize_questions ||
      logic?.randomization?.randomize_options;

    return (
      <Card>
        <CardHeader>
          <CardTitle>Logic Summary</CardTitle>
        </CardHeader>
        <CardContent>
          {!hasLogic ? (
            <p className="text-gray-600">No logic rules configured</p>
          ) : (
            <div className="space-y-4">
              {(logic?.conditional_questions?.length || 0) > 0 && (
                <div>
                  <h4 className="font-medium">Conditional Logic Rules:</h4>
                  <ul className="list-disc list-inside text-sm text-gray-600 mt-1">
                    {logic?.conditional_questions?.map((rule, index) => (
                      <li key={rule.condition_id}>
                        Rule {index + 1}: {rule.action} when {rule.operator} {rule.value}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {logic?.randomization && (
                <div>
                  <h4 className="font-medium">Randomization:</h4>
                  <ul className="list-disc list-inside text-sm text-gray-600 mt-1">
                    {logic.randomization.randomize_questions && <li>Questions randomized</li>}
                    {logic.randomization.randomize_options && <li>Answer options randomized</li>}
                  </ul>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Survey Logic</h2>
          <p className="text-gray-600">Configure conditional logic, branching, and randomization</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowPreview(!showPreview)}
        >
          {showPreview ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          {showPreview ? 'Hide' : 'Show'} Summary
        </Button>
      </div>

      {/* Preview */}
      {renderLogicPreview()}

      {/* Navigation */}
      <div className="flex space-x-1 border-b">
        {[
          { key: 'conditional', label: 'Conditional', icon: GitBranch },
          { key: 'skip', label: 'Skip Logic', icon: ArrowRight },
          { key: 'branching', label: 'Branching', icon: GitBranch },
          { key: 'randomization', label: 'Randomization', icon: Shuffle }
        ].map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveSection(key as any)}
            className={`flex items-center gap-2 px-4 py-2 border-b-2 transition-colors ${
              activeSection === key
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="min-h-96">
        {activeSection === 'conditional' && renderConditionalLogic()}
        {activeSection === 'skip' && renderSkipLogic()}
        {activeSection === 'branching' && renderBranchingLogic()}
        {activeSection === 'randomization' && renderRandomizationSettings()}
      </div>

      {/* Help Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Logic Best Practices</CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-2">
          <ul className="list-disc list-inside space-y-1 text-gray-600">
            <li>Keep logic rules simple and easy to understand</li>
            <li>Test your logic thoroughly before publishing</li>
            <li>For neuroimaging surveys, place demographic questions first</li>
            <li>Use conditional logic to reduce survey fatigue</li>
            <li>Consider the survey flow from the respondent's perspective</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
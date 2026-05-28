import type { Meta, StoryObj } from '@storybook/react';
import { fn } from '@storybook/test';
import React, { useState } from 'react';
import { Send, Paperclip, Mic, MicOff, Image, FileText } from 'lucide-react';

// Mock chat components for demonstration
const MockChatWorkspace = ({ 
  messages = [], 
  onSendMessage, 
  onFileUpload,
  onVoiceToggle,
  isListening = false,
  className = ''
}: {
  messages?: Array<{ id: string; content: string; sender: 'user' | 'assistant'; timestamp: Date; attachments?: any[] }>;
  onSendMessage?: (message: string) => void;
  onFileUpload?: (files: File[]) => void;
  onVoiceToggle?: () => void;
  isListening?: boolean;
  className?: string;
}) => {
  const [inputValue, setInputValue] = useState('');
  
  const handleSend = () => {
    if (inputValue.trim()) {
      onSendMessage?.(inputValue);
      setInputValue('');
    }
  };
  
  return (
    <div className={`flex flex-col h-96 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg ${className}`}>
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 dark:text-gray-400 mt-8">
            <div className="text-4xl mb-2">🧠</div>
            <h3 className="text-lg font-semibold mb-2">Start a Research Conversation</h3>
            <p>Ask questions about neuroimaging data, analysis methods, or upload datasets for analysis.</p>
          </div>
        ) : (
          messages.map((message) => (
            <div 
              key={message.id}
              className={`flex ${message.sender === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div className={`max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                message.sender === 'user' 
                  ? 'bg-blue-500 text-white' 
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white'
              }`}>
                <p className="text-sm">{message.content}</p>
                {message.attachments && message.attachments.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {message.attachments.map((attachment, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs opacity-80">
                        <FileText className="h-3 w-3" />
                        <span>{attachment.name}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="text-xs mt-1 opacity-70">
                  {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      
      {/* Input Area */}
      <div className="border-t border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <div className="relative">
              <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="Ask about fMRI analysis, upload data, or describe your research question..."
                className="w-full px-3 py-2 pr-12 border border-gray-300 dark:border-gray-600 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:text-white"
                rows={1}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
              />
              <div className="absolute right-2 top-2 flex items-center gap-1">
                <button
                  onClick={onVoiceToggle}
                  className={`p-1.5 rounded ${isListening ? 'text-red-500' : 'text-gray-400 hover:text-gray-600'}`}
                  title={isListening ? 'Stop listening' : 'Start voice input'}
                >
                  {isListening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                </button>
                <input
                  type="file"
                  multiple
                  accept=".nii,.nii.gz,.json,.csv,.txt"
                  className="hidden"
                  id="file-upload"
                  onChange={(e) => onFileUpload?.(Array.from(e.target.files || []))}
                />
                <label
                  htmlFor="file-upload"
                  className="p-1.5 text-gray-400 hover:text-gray-600 cursor-pointer"
                  title="Upload files"
                >
                  <Paperclip className="h-4 w-4" />
                </label>
              </div>
            </div>
          </div>
          
          <button
            onClick={handleSend}
            disabled={!inputValue.trim()}
            className="p-2.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        
        <div className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          Press Enter to send, Shift+Enter for new line
        </div>
      </div>
    </div>
  );
};

const mockMessages = [
  {
    id: '1',
    content: "Hi! I have an fMRI dataset from a visual attention experiment. Can you help me analyze it?",
    sender: 'user' as const,
    timestamp: new Date(Date.now() - 300000),
  },
  {
    id: '2',
    content: "Absolutely! I'd be happy to help with your visual attention fMRI analysis. Can you tell me more about your experimental design? For example:\n\n• How many participants?\n• What were the task conditions?\n• Do you have the data in BIDS format?\n• Any specific contrasts you're interested in?",
    sender: 'assistant' as const,
    timestamp: new Date(Date.now() - 280000),
  },
  {
    id: '3',
    content: "We have 24 participants, comparing focused attention vs. distributed attention conditions. The data is in BIDS format. I'm particularly interested in frontoparietal network activation.",
    sender: 'user' as const,
    timestamp: new Date(Date.now() - 260000),
  },
  {
    id: '4',
    content: "Perfect! That's a classic attention network study. I can help you set up a GLM analysis to contrast focused vs. distributed attention. This should reveal activation in:\n\n🧠 **Frontoparietal Control Network:**\n• Dorsolateral prefrontal cortex\n• Posterior parietal cortex\n• Frontal eye fields\n\n📊 **Analysis Steps:**\n1. First-level GLM for each participant\n2. Focused > Distributed contrast\n3. Group-level analysis\n4. ROI analysis in attention networks\n\nShall we start by uploading your BIDS dataset?",
    sender: 'assistant' as const,
    timestamp: new Date(Date.now() - 240000),
    attachments: [{ name: 'attention_analysis_plan.json', size: 2048 }]
  },
];

const meta = {
  title: 'Components/Chat Interface',
  component: MockChatWorkspace,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'An intelligent chat interface for research conversations. Supports text input, voice commands, file uploads, and contextual assistance for neuroimaging analysis workflows.',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: {
    messages: {
      description: 'Array of chat messages to display',
    },
    onSendMessage: {
      action: 'sendMessage',
      description: 'Callback when user sends a message',
    },
    onFileUpload: {
      action: 'fileUpload',
      description: 'Callback when files are uploaded',
    },
    onVoiceToggle: {
      action: 'voiceToggle',
      description: 'Callback when voice input is toggled',
    },
    isListening: {
      control: { type: 'boolean' },
      description: 'Whether voice input is active',
    },
  },
  args: {
    onSendMessage: fn(),
    onFileUpload: fn(),
    onVoiceToggle: fn(),
  },
} satisfies Meta<typeof MockChatWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

// Empty state
export const EmptyState: Story = {
  args: {
    messages: [],
  },
  parameters: {
    docs: {
      description: {
        story: 'Initial empty state encouraging users to start a research conversation.',
      },
    },
  },
};

// Active conversation
export const ActiveConversation: Story = {
  args: {
    messages: mockMessages,
  },
  parameters: {
    docs: {
      description: {
        story: 'Active research conversation about fMRI analysis with assistant responses.',
      },
    },
  },
};

// Voice input active
export const VoiceInputActive: Story = {
  args: {
    messages: mockMessages.slice(0, 2),
    isListening: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Chat interface with voice input activated for hands-free interaction.',
      },
    },
  },
};

// File upload scenario
export const FileUploadScenario: Story = {
  render: () => {
    const [messages, setMessages] = useState([
      {
        id: '1',
        content: "I'd like to upload my fMRI dataset for analysis.",
        sender: 'user' as const,
        timestamp: new Date(Date.now() - 60000),
      },
      {
        id: '2',
        content: "Great! Please upload your BIDS-formatted dataset. I can accept .nii/.nii.gz files, JSON sidecars, and TSV files. What type of analysis are you planning?",
        sender: 'assistant' as const,
        timestamp: new Date(Date.now() - 45000),
      },
    ]);
    
    return (
      <MockChatWorkspace 
        messages={messages}
        onSendMessage={(msg) => setMessages(prev => [...prev, {
          id: Date.now().toString(),
          content: msg,
          sender: 'user',
          timestamp: new Date()
        }])}
        onFileUpload={(files) => {
          const fileNames = files.map(f => f.name).join(', ');
          setMessages(prev => [...prev, 
            {
              id: Date.now().toString(),
              content: `Uploading files: ${fileNames}`,
              sender: 'user',
              timestamp: new Date(),
              attachments: files.map(f => ({ name: f.name, size: f.size }))
            }
          ]);
        }}
      />
    );
  },
  parameters: {
    docs: {
      description: {
        story: 'Interactive demo showing file upload workflow in chat interface.',
      },
    },
  },
};

// Scientific discussion
export const ScientificDiscussion: Story = {
  args: {
    messages: [
      {
        id: '1',
        content: "What's the difference between FWE and FDR correction for multiple comparisons?",
        sender: 'user' as const,
        timestamp: new Date(Date.now() - 120000),
      },
      {
        id: '2',
        content: "Great question! Both control for multiple comparisons but differently:\n\n**FWE (Family-Wise Error):**\n• Controls probability of ANY false positive\n• More conservative (fewer false positives)\n• Better for confirmatory analyses\n• Methods: Bonferroni, Random Field Theory\n\n**FDR (False Discovery Rate):**\n• Controls proportion of false positives\n• Less conservative (more discoveries)\n• Better for exploratory analyses\n• Allows some false positives if overall rate is controlled\n\n**When to use:**\n• FWE: Hypothesis testing, small number of tests\n• FDR: Exploratory analysis, many voxels/regions\n\nWhich type of analysis are you planning?",
        sender: 'assistant' as const,
        timestamp: new Date(Date.now() - 100000),
      },
      {
        id: '3',
        content: "I'm doing an exploratory whole-brain analysis to identify regions involved in working memory. Sounds like FDR would be appropriate?",
        sender: 'user' as const,
        timestamp: new Date(Date.now() - 80000),
      },
      {
        id: '4',
        content: "Exactly right! For exploratory whole-brain working memory analysis, FDR is ideal because:\n\n✅ **Advantages for your study:**\n• Maximizes discovery of working memory regions\n• Balances sensitivity vs. specificity\n• Standard for exploratory neuroimaging\n\n📊 **Typical thresholds:**\n• q < 0.05 (FDR-corrected)\n• Minimum cluster size: 10+ voxels\n• Consider q < 0.01 for more conservative results\n\n🧠 **Expected working memory regions:**\n• Dorsolateral prefrontal cortex\n• Posterior parietal cortex\n• Anterior cingulate\n• Premotor areas\n\nWould you like me to help set up the analysis parameters?",
        sender: 'assistant' as const,
        timestamp: new Date(Date.now() - 60000),
      },
    ],
  },
  parameters: {
    docs: {
      description: {
        story: 'In-depth scientific discussion about statistical methods in neuroimaging.',
      },
    },
  },
};

// Mobile responsive
export const MobileView: Story = {
  args: {
    messages: mockMessages.slice(0, 3),
    className: 'h-screen max-w-sm mx-auto',
  },
  parameters: {
    viewport: {
      defaultViewport: 'mobile',
    },
    docs: {
      description: {
        story: 'Chat interface optimized for mobile devices with touch interactions.',
      },
    },
  },
};

// Dark theme
export const DarkTheme: Story = {
  args: {
    messages: mockMessages,
  },
  parameters: {
    backgrounds: { default: 'dark' },
    docs: {
      description: {
        story: 'Chat interface in dark theme showing proper contrast and readability.',
      },
    },
  },
  decorators: [
    (Story) => (
      <div className="dark">
        <div className="bg-gray-900 p-4 min-h-screen">
          <Story />
        </div>
      </div>
    ),
  ],
};

// Accessibility features
export const AccessibilityFeatures: Story = {
  render: () => (
    <div className="space-y-4">
      <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
        <h3 className="font-semibold text-blue-900 dark:text-blue-100 mb-2">
          Accessibility Features
        </h3>
        <ul className="text-sm text-blue-700 dark:text-blue-300 space-y-1">
          <li>• Keyboard navigation (Tab, Enter, Shift+Enter)</li>
          <li>• Screen reader announcements for new messages</li>
          <li>• Voice input with visual feedback</li>
          <li>• High contrast focus indicators</li>
          <li>• Semantic HTML structure</li>
        </ul>
      </div>
      
      <MockChatWorkspace 
        messages={[
          {
            id: '1',
            content: "Testing accessibility features...",
            sender: 'user',
            timestamp: new Date(),
          }
        ]}
      />
      
      <div className="text-sm text-gray-600 dark:text-gray-400">
        <strong>Keyboard shortcuts:</strong>
        <br />• Enter: Send message
        <br />• Shift+Enter: New line
        <br />• Ctrl+U: Upload file
        <br />• Ctrl+M: Toggle voice input
      </div>
    </div>
  ),
  parameters: {
    docs: {
      description: {
        story: 'Demonstration of accessibility features including keyboard navigation and screen reader support.',
      },
    },
  },
};
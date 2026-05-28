/**
 * PWA Install Prompt Component for Brain Researcher
 * Provides intelligent install prompts based on user behavior and device capabilities
 */

'use client';

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CloudArrowDownIcon,
  XMarkIcon,
  DevicePhoneMobileIcon,
  ComputerDesktopIcon,
  SparklesIcon,
  BoltIcon,
  SignalIcon,
  ShieldCheckIcon
} from '@heroicons/react/24/outline';
import { cn } from '@/lib/utils';
import { usePWA } from '@/hooks/use-pwa';
import { PushNotificationUtils } from '@/lib/push-notifications';
import { serviceEndpoints } from '@/lib/service-endpoints';

interface InstallPromptProps {
  className?: string;
  variant?: 'banner' | 'modal' | 'inline';
  autoShow?: boolean;
  showDelay?: number;
}

interface InstallBenefit {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
}

const installBenefits: InstallBenefit[] = [
  {
    icon: BoltIcon,
    title: 'Faster Performance',
    description: 'Lightning-fast access to brain analysis tools'
  },
  {
    icon: SignalIcon,
    title: 'Offline Access',
    description: 'Work with brain data even without internet'
  },
  {
    icon: ShieldCheckIcon,
    title: 'Secure & Private',
    description: 'Your research data stays on your device'
  },
  {
    icon: SparklesIcon,
    title: 'Native Experience',
    description: 'App-like interface optimized for your device'
  }
];

export function InstallPrompt({ 
  className, 
  variant = 'banner',
  autoShow = true,
  showDelay = 3000 
}: InstallPromptProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [isAnimating, setIsAnimating] = useState(false);
  const [hasUserDismissed, setHasUserDismissed] = useState(false);
  const [installStep, setInstallStep] = useState<'prompt' | 'installing' | 'success' | 'error'>('prompt');
  
  const {
    installPrompt,
    isInstalled,
    canInstall,
    install
  } = usePWA();

  const isMobile = PushNotificationUtils.isMobileDevice();

  // Auto-show logic
  useEffect(() => {
    if (!autoShow || hasUserDismissed || isInstalled || !canInstall) return;

    // Check if user has dismissed before
    const dismissed = localStorage.getItem('br-install-prompt-dismissed');
    if (dismissed) {
      const dismissedTime = parseInt(dismissed);
      const daysSinceDismissed = (Date.now() - dismissedTime) / (1000 * 60 * 60 * 24);
      
      // Don't show again for 7 days
      if (daysSinceDismissed < 7) {
        setHasUserDismissed(true);
        return;
      }
    }

    // Show after delay
    const timer = setTimeout(() => {
      setIsVisible(true);
    }, showDelay);

    return () => clearTimeout(timer);
  }, [autoShow, showDelay, hasUserDismissed, isInstalled, canInstall]);

  // Handle install process
  const handleInstall = async () => {
    if (!installPrompt || !canInstall) return;

    setIsAnimating(true);
    setInstallStep('installing');

    try {
      const result = await install();
      
      if (result.outcome === 'accepted') {
        setInstallStep('success');
        
        // Track successful install
        trackInstallEvent('install_accepted', {
          variant,
          isMobile,
          userAgent: navigator.userAgent
        });

        // Auto-close after success animation
        setTimeout(() => {
          setIsVisible(false);
        }, 2000);
      } else {
        setInstallStep('error');
        trackInstallEvent('install_dismissed', { variant });
        
        setTimeout(() => {
          setIsVisible(false);
          setInstallStep('prompt');
        }, 2000);
      }
    } catch (error) {
      console.error('Installation failed:', error);
      setInstallStep('error');
      
      trackInstallEvent('install_error', {
        error: error.message,
        variant
      });

      setTimeout(() => {
        setIsVisible(false);
        setInstallStep('prompt');
      }, 2000);
    } finally {
      setIsAnimating(false);
    }
  };

  const handleDismiss = () => {
    setIsVisible(false);
    setHasUserDismissed(true);
    
    // Remember dismissal
    localStorage.setItem('br-install-prompt-dismissed', Date.now().toString());
    
    trackInstallEvent('install_prompt_dismissed', {
      variant,
      step: installStep
    });
  };

  const handleLater = () => {
    setIsVisible(false);
    
    // Remember "later" choice for shorter period
    localStorage.setItem('br-install-prompt-later', Date.now().toString());
    
    trackInstallEvent('install_later', { variant });
  };

  const trackInstallEvent = (event: string, data: Record<string, any>) => {
    // Analytics tracking
    if (typeof window !== 'undefined' && (window as any).gtag) {
      (window as any).gtag('event', event, {
        event_category: 'pwa_install',
        ...data
      });
    }

    // Internal telemetry
    const endpoint = serviceEndpoints.orchestrator('/api/telemetry/event');
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'pwa_install_event',
        event,
        data,
        timestamp: new Date().toISOString()
      })
    }).catch(() => {
      // Ignore telemetry errors
    });
  };

  // Don't render if already installed or can't install
  if (isInstalled || !canInstall) {
    return null;
  }

  // Don't render if dismissed and not forced
  if (hasUserDismissed && !isVisible) {
    return null;
  }

  const getDeviceIcon = () => {
    return isMobile ? DevicePhoneMobileIcon : ComputerDesktopIcon;
  };

  const getInstallInstructions = () => {
    const userAgent = navigator.userAgent.toLowerCase();
    
    if (isMobile) {
      if (userAgent.includes('android')) {
        return 'Tap "Add to Home Screen" to install';
      } else if (userAgent.includes('ios') || userAgent.includes('safari')) {
        return 'Tap the share button and "Add to Home Screen"';
      }
    }
    
    return 'Click install to add to your applications';
  };

  if (variant === 'banner') {
    return (
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ y: -100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -100, opacity: 0 }}
            className={cn(
              "fixed top-16 left-4 right-4 z-50 bg-gradient-to-r from-blue-600 to-purple-600",
              "rounded-lg shadow-lg text-white p-4 md:max-w-md md:left-auto md:right-4",
              className
            )}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <CloudArrowDownIcon className="w-6 h-6 flex-shrink-0" />
                <div className="min-w-0">
                  <div className="text-sm font-medium">Install Brain Researcher</div>
                  <div className="text-xs opacity-90 truncate">
                    Get faster offline access
                  </div>
                </div>
              </div>
              
              <div className="flex items-center space-x-2 ml-4">
                <button
                  onClick={handleInstall}
                  disabled={isAnimating}
                  className="px-3 py-1 bg-white bg-opacity-20 rounded text-sm font-medium hover:bg-opacity-30 transition-all disabled:opacity-50"
                >
                  {installStep === 'installing' ? 'Installing...' : 'Install'}
                </button>
                <button
                  onClick={handleDismiss}
                  className="p-1 hover:bg-white hover:bg-opacity-20 rounded transition-all"
                >
                  <XMarkIcon className="w-4 h-4" />
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    );
  }

  if (variant === 'modal') {
    return (
      <AnimatePresence>
        {isVisible && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-50 bg-black bg-opacity-50"
              onClick={handleDismiss}
            />

            {/* Modal */}
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              className={cn(
                "fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-50",
                "bg-white rounded-2xl shadow-2xl max-w-md w-full mx-4 overflow-hidden",
                className
              )}
            >
              {/* Header */}
              <div className="relative bg-gradient-to-r from-blue-600 to-purple-600 text-white p-6 text-center">
                <button
                  onClick={handleDismiss}
                  className="absolute top-4 right-4 p-1 hover:bg-white hover:bg-opacity-20 rounded transition-all"
                >
                  <XMarkIcon className="w-5 h-5" />
                </button>
                
                <div className="mb-4">
                  {React.createElement(getDeviceIcon(), {
                    className: "w-12 h-12 mx-auto mb-2"
                  })}
                </div>
                
                <h2 className="text-xl font-bold mb-2">
                  Install Brain Researcher
                </h2>
                <p className="text-blue-100 text-sm">
                  Get the best research experience on your device
                </p>
              </div>

              {/* Content */}
              <div className="p-6">
                {installStep === 'prompt' && (
                  <>
                    {/* Benefits */}
                    <div className="space-y-3 mb-6">
                      {installBenefits.map((benefit, index) => (
                        <div key={index} className="flex items-center space-x-3">
                          <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                            <benefit.icon className="w-4 h-4 text-blue-600" />
                          </div>
                          <div>
                            <div className="text-sm font-medium text-gray-900">
                              {benefit.title}
                            </div>
                            <div className="text-xs text-gray-600">
                              {benefit.description}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Instructions */}
                    <div className="bg-gray-50 rounded-lg p-3 mb-6">
                      <div className="text-xs text-gray-600">
                        {getInstallInstructions()}
                      </div>
                    </div>
                  </>
                )}

                {installStep === 'installing' && (
                  <div className="text-center py-8">
                    <div className="animate-spin w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full mx-auto mb-4"></div>
                    <div className="text-sm text-gray-600">Installing Brain Researcher...</div>
                  </div>
                )}

                {installStep === 'success' && (
                  <div className="text-center py-8">
                    <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <ShieldCheckIcon className="w-6 h-6 text-green-600" />
                    </div>
                    <div className="text-sm font-medium text-gray-900 mb-2">Successfully Installed!</div>
                    <div className="text-xs text-gray-600">Brain Researcher is now available on your device</div>
                  </div>
                )}

                {installStep === 'error' && (
                  <div className="text-center py-8">
                    <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <XMarkIcon className="w-6 h-6 text-red-600" />
                    </div>
                    <div className="text-sm font-medium text-gray-900 mb-2">Installation Failed</div>
                    <div className="text-xs text-gray-600">Please try again or install manually</div>
                  </div>
                )}

                {/* Actions */}
                {installStep === 'prompt' && (
                  <div className="flex space-x-3">
                    <button
                      onClick={handleLater}
                      className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                    >
                      Later
                    </button>
                    <button
                      onClick={handleInstall}
                      disabled={isAnimating}
                      className="flex-1 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 flex items-center justify-center"
                    >
                      {isAnimating ? (
                        <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></div>
                      ) : (
                        <>
                          <CloudArrowDownIcon className="w-4 h-4 mr-2" />
                          Install Now
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    );
  }

  // Inline variant
  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className={cn(
            "bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-lg overflow-hidden",
            className
          )}
        >
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                <CloudArrowDownIcon className="w-5 h-5 text-blue-600" />
                <span className="text-sm font-medium text-gray-900">
                  Install Brain Researcher
                </span>
              </div>
              <button
                onClick={handleDismiss}
                className="text-gray-400 hover:text-gray-600"
              >
                <XMarkIcon className="w-4 h-4" />
              </button>
            </div>
            
            <p className="text-xs text-gray-600 mb-3">
              Install the app for faster performance and offline access to your brain research tools.
            </p>
            
            <div className="flex space-x-2">
              <button
                onClick={handleLater}
                className="px-3 py-1 text-xs font-medium text-gray-600 hover:text-gray-800 transition-colors"
              >
                Not now
              </button>
              <button
                onClick={handleInstall}
                disabled={isAnimating}
                className="px-3 py-1 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                {installStep === 'installing' ? 'Installing...' : 'Install'}
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default InstallPrompt;

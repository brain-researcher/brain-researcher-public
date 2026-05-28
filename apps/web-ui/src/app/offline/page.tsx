/**
 * Offline Page for Brain Researcher PWA
 * Displayed when users are offline and try to access unavailable content
 */

'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  WifiIcon,
  ArrowPathIcon,
  HomeIcon,
  BeakerIcon,
  ChartBarIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon
} from '@heroicons/react/24/outline';
import { motion } from 'framer-motion';
import { useOffline } from '@/hooks/use-offline';

interface OfflineCapability {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  available: boolean;
}

export default function OfflinePage() {
  const [isRetrying, setIsRetrying] = useState(false);
  const [connectionCheck, setConnectionCheck] = useState<boolean | null>(null);
  
  const { 
    isOffline, 
    offlineDuration, 
    lastOnline, 
    checkConnection,
    offlineFeatures 
  } = useOffline();

  // Available offline capabilities
  const offlineCapabilities: OfflineCapability[] = [
    {
      name: 'Dashboard',
      href: '/',
      icon: HomeIcon,
      available: true
    },
    {
      name: 'Cached Datasets',
      href: '/datasets',
      icon: ChartBarIcon,
      available: true
    },
    {
      name: 'Analysis Results',
      href: '/results',
      icon: BeakerIcon,
      available: true
    }
  ];

  const handleRetry = async () => {
    setIsRetrying(true);
    setConnectionCheck(null);

    try {
      const isConnected = await checkConnection();
      setConnectionCheck(isConnected);

      if (isConnected) {
        // Reload the page to go back to the original content
        setTimeout(() => {
          window.location.reload();
        }, 1000);
      }
    } catch (error) {
      setConnectionCheck(false);
    } finally {
      setIsRetrying(false);
    }
  };

  const formatOfflineDuration = (duration: number): string => {
    const minutes = Math.floor(duration / (1000 * 60));
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ${hours % 24}h`;
    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    if (minutes > 0) return `${minutes}m`;
    return 'Just now';
  };

  useEffect(() => {
    // Auto-retry connection every 30 seconds
    const interval = setInterval(() => {
      if (isOffline) {
        checkConnection().then(isConnected => {
          if (isConnected) {
            window.location.reload();
          }
        });
      }
    }, 30000);

    return () => clearInterval(interval);
  }, [isOffline, checkConnection]);

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white shadow-sm border-b">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 bg-amber-600 rounded-lg flex items-center justify-center">
              <ExclamationTriangleIcon className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-gray-900">
                You&apos;re Offline
              </h1>
              <p className="text-sm text-gray-600">
                Brain Researcher is working in offline mode
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1">
          {/* Connection Status */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white rounded-lg shadow-sm border p-6 mb-8"
          >
            <div className="text-center">
              <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <WifiIcon className="w-8 h-8 text-amber-600" />
              </div>
              
              <h2 className="text-lg font-semibold text-gray-900 mb-2">
                Connection Lost
              </h2>
              
              <p className="text-gray-600 mb-4">
                Your internet connection appears to be offline. Some features may be limited.
              </p>

              {/* Connection Details */}
              <div className="bg-gray-50 rounded-lg p-4 mb-6">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-gray-500">Offline Duration:</span>
                    <span className="ml-2 font-medium text-gray-900">
                      {formatOfflineDuration(offlineDuration)}
                    </span>
                  </div>
                  {lastOnline && (
                    <div>
                      <span className="text-gray-500">Last Online:</span>
                      <span className="ml-2 font-medium text-gray-900">
                        {lastOnline.toLocaleTimeString()}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Retry Button */}
              <div className="flex flex-col items-center space-y-3">
                <button
                  onClick={handleRetry}
                  disabled={isRetrying}
                  className="flex items-center space-x-2 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ArrowPathIcon className={`w-5 h-5 ${isRetrying ? 'animate-spin' : ''}`} />
                  <span>{isRetrying ? 'Checking Connection...' : 'Try Again'}</span>
                </button>

                {/* Connection Check Result */}
                {connectionCheck !== null && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className={`flex items-center space-x-2 text-sm ${
                      connectionCheck ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {connectionCheck ? (
                      <>
                        <CheckCircleIcon className="w-4 h-4" />
                        <span>Connection restored! Reloading...</span>
                      </>
                    ) : (
                      <>
                        <ExclamationTriangleIcon className="w-4 h-4" />
                        <span>Still offline. Please check your connection.</span>
                      </>
                    )}
                  </motion.div>
                )}
              </div>
            </div>
          </motion.div>

          {/* Available Features */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-white rounded-lg shadow-sm border p-6 mb-8"
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              What You Can Do Offline
            </h3>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {offlineCapabilities.map((capability, index) => (
                <Link
                  key={index}
                  href={capability.href}
                  className={`block p-4 rounded-lg border-2 transition-all ${
                    capability.available
                      ? 'border-green-200 bg-green-50 hover:border-green-300 hover:bg-green-100'
                      : 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-60'
                  }`}
                >
                  <div className="flex items-center space-x-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                      capability.available ? 'bg-green-100' : 'bg-gray-100'
                    }`}>
                      <capability.icon className={`w-5 h-5 ${
                        capability.available ? 'text-green-600' : 'text-gray-400'
                      }`} />
                    </div>
                    <div>
                      <div className={`font-medium ${
                        capability.available ? 'text-gray-900' : 'text-gray-500'
                      }`}>
                        {capability.name}
                      </div>
                      <div className="text-xs text-gray-500">
                        {capability.available ? 'Available offline' : 'Requires internet'}
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </motion.div>

          {/* Tips */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 }}
            className="bg-blue-50 rounded-lg border border-blue-200 p-6"
          >
            <h3 className="text-lg font-semibold text-blue-900 mb-3">
              Offline Tips
            </h3>
            
            <ul className="space-y-2 text-blue-800">
              <li className="flex items-start space-x-2">
                <span className="w-1.5 h-1.5 bg-blue-600 rounded-full mt-2 flex-shrink-0"></span>
                <span>Previously viewed brain datasets and analysis results are available offline</span>
              </li>
              <li className="flex items-start space-x-2">
                <span className="w-1.5 h-1.5 bg-blue-600 rounded-full mt-2 flex-shrink-0"></span>
                <span>Your settings and preferences are saved locally</span>
              </li>
              <li className="flex items-start space-x-2">
                <span className="w-1.5 h-1.5 bg-blue-600 rounded-full mt-2 flex-shrink-0"></span>
                <span>Changes will sync automatically when you reconnect</span>
              </li>
              <li className="flex items-start space-x-2">
                <span className="w-1.5 h-1.5 bg-blue-600 rounded-full mt-2 flex-shrink-0"></span>
                <span>New analysis requests require an internet connection</span>
              </li>
            </ul>
          </motion.div>
        </div>
      </div>

      {/* Auto-retry indicator */}
      <div className="bg-white border-t px-4 py-3">
        <div className="max-w-4xl mx-auto">
          <div className="text-center text-sm text-gray-500">
            <motion.div
              animate={{ opacity: [0.5, 1, 0.5] }}
              transition={{ repeat: Infinity, duration: 2 }}
              className="flex items-center justify-center space-x-2"
            >
              <ArrowPathIcon className="w-4 h-4" />
              <span>Automatically checking for connection...</span>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

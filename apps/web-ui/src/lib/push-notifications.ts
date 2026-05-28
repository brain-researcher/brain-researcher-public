import { serviceEndpoints } from './service-endpoints'

/**
 * Push Notifications Library for Brain Researcher PWA
 * Handles subscription management, notification display, and backend integration
 */

export interface PushSubscriptionData {
  endpoint: string;
  keys: {
    p256dh: string;
    auth: string;
  };
}

export interface NotificationPayload {
  type: 'analysis-complete' | 'data-update' | 'system-alert' | 'default';
  title?: string;
  body: string;
  analysisName?: string;
  analysisId?: string;
  datasetName?: string;
  message?: string;
  data?: Record<string, any>;
  actions?: NotificationAction[];
  requireInteraction?: boolean;
}

export interface NotificationAction {
  action: string;
  title: string;
  icon?: string;
}

export interface PushNotificationOptions {
  vapidPublicKey?: string;
  serviceWorkerPath?: string;
  subscriptionEndpoint?: string;
}

class PushNotificationManager {
  private vapidPublicKey: string;
  private serviceWorkerPath: string;
  private subscriptionEndpoint: string;
  private registration: ServiceWorkerRegistration | null = null;
  private subscription: PushSubscription | null = null;

  constructor(options: PushNotificationOptions = {}) {
    this.vapidPublicKey = options.vapidPublicKey || process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY || '';
    this.serviceWorkerPath = options.serviceWorkerPath || '/service-worker.js';
    this.subscriptionEndpoint = options.subscriptionEndpoint || '/api/push/subscribe';
    
    // Initialize if supported
    if (this.isSupported()) {
      this.initialize();
    }
  }

  /**
   * Check if push notifications are supported
   */
  isSupported(): boolean {
    return 'serviceWorker' in navigator && 
           'PushManager' in window && 
           'Notification' in window;
  }

  /**
   * Get current notification permission status
   */
  getPermissionStatus(): NotificationPermission {
    return Notification.permission;
  }

  /**
   * Check if notifications are currently enabled
   */
  async isEnabled(): Promise<boolean> {
    if (!this.isSupported()) return false;
    
    const permission = this.getPermissionStatus();
    if (permission !== 'granted') return false;
    
    const subscription = await this.getSubscription();
    return subscription !== null;
  }

  /**
   * Initialize the push notification system
   */
  private async initialize(): Promise<void> {
    try {
      this.registration = await navigator.serviceWorker.register(this.serviceWorkerPath);
      
      // Wait for service worker to be ready
      await navigator.serviceWorker.ready;
      
      console.log('Push notifications initialized');
    } catch (error) {
      console.error('Failed to initialize push notifications:', error);
    }
  }

  /**
   * Request notification permission from user
   */
  async requestPermission(): Promise<NotificationPermission> {
    if (!this.isSupported()) {
      throw new Error('Push notifications not supported');
    }

    const permission = await Notification.requestPermission();
    
    // Track permission grant for analytics
    if (permission === 'granted') {
      this.trackEvent('permission_granted');
    } else if (permission === 'denied') {
      this.trackEvent('permission_denied');
    }
    
    return permission;
  }

  /**
   * Subscribe to push notifications
   */
  async subscribe(): Promise<PushSubscription | null> {
    try {
      if (!this.isSupported()) {
        throw new Error('Push notifications not supported');
      }

      // Check permission
      let permission = this.getPermissionStatus();
      if (permission === 'default') {
        permission = await this.requestPermission();
      }
      
      if (permission !== 'granted') {
        throw new Error('Notification permission not granted');
      }

      // Get service worker registration
      if (!this.registration) {
        this.registration = await navigator.serviceWorker.ready;
      }

      // Check if already subscribed
      let subscription = await this.registration.pushManager.getSubscription();
      
      if (!subscription) {
        // Create new subscription
        const vapidKey = this.urlBase64ToUint8Array(this.vapidPublicKey);
        
        subscription = await this.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: vapidKey as unknown as BufferSource
        });
      }

      this.subscription = subscription;

      // Send subscription to backend
      await this.sendSubscriptionToBackend(subscription);

      this.trackEvent('subscribed');
      console.log('Push notification subscription successful');
      
      return subscription;
    } catch (error) {
      console.error('Failed to subscribe to push notifications:', error);
      this.trackEvent('subscription_failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Unsubscribe from push notifications
   */
  async unsubscribe(): Promise<void> {
    try {
      const subscription = await this.getSubscription();
      
      if (subscription) {
        // Unsubscribe from push manager
        await subscription.unsubscribe();
        
        // Notify backend
        await this.removeSubscriptionFromBackend(subscription);
        
        this.subscription = null;
        this.trackEvent('unsubscribed');
        console.log('Push notification unsubscription successful');
      }
    } catch (error) {
      console.error('Failed to unsubscribe from push notifications:', error);
      this.trackEvent('unsubscription_failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Get current subscription
   */
  async getSubscription(): Promise<PushSubscription | null> {
    if (!this.isSupported() || !this.registration) return null;
    
    try {
      this.subscription = await this.registration.pushManager.getSubscription();
      return this.subscription;
    } catch (error) {
      console.error('Failed to get subscription:', error);
      return null;
    }
  }

  /**
   * Send test notification (local)
   */
  async sendTestNotification(): Promise<void> {
    if (!this.isSupported()) {
      throw new Error('Notifications not supported');
    }

    const permission = this.getPermissionStatus();
    if (permission !== 'granted') {
      throw new Error('Notification permission not granted');
    }

    const notification = new Notification('Brain Researcher Test', {
      body: 'Push notifications are working correctly!',
      icon: '/icons/icon-192x192.png',
      tag: 'test-notification'
    });

    // Auto-close after 5 seconds
    setTimeout(() => notification.close(), 5000);

    this.trackEvent('test_notification_sent');
  }

  /**
   * Send subscription to backend
   */
  private async sendSubscriptionToBackend(subscription: PushSubscription): Promise<void> {
    try {
      const subscriptionData = this.subscriptionToData(subscription);
      
      const response = await fetch(this.subscriptionEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          subscription: subscriptionData,
          userAgent: navigator.userAgent,
          timestamp: new Date().toISOString()
        })
      });

      if (!response.ok) {
        throw new Error(`Backend subscription failed: ${response.status}`);
      }

      console.log('Subscription sent to backend successfully');
    } catch (error) {
      console.error('Failed to send subscription to backend:', error);
      throw error;
    }
  }

  /**
   * Remove subscription from backend
   */
  private async removeSubscriptionFromBackend(subscription: PushSubscription): Promise<void> {
    try {
      const subscriptionData = this.subscriptionToData(subscription);
      
      const response = await fetch(this.subscriptionEndpoint, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          subscription: subscriptionData
        })
      });

      if (!response.ok) {
        console.warn('Failed to remove subscription from backend:', response.status);
      } else {
        console.log('Subscription removed from backend successfully');
      }
    } catch (error) {
      console.error('Failed to remove subscription from backend:', error);
    }
  }

  /**
   * Convert PushSubscription to serializable data
   */
  private subscriptionToData(subscription: PushSubscription): PushSubscriptionData {
    return {
      endpoint: subscription.endpoint,
      keys: {
        p256dh: this.arrayBufferToBase64(subscription.getKey('p256dh')!),
        auth: this.arrayBufferToBase64(subscription.getKey('auth')!)
      }
    };
  }

  /**
   * Convert VAPID public key from base64 to Uint8Array
   */
  private urlBase64ToUint8Array(base64String: string): Uint8Array {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
      .replace(/-/g, '+')
      .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  /**
   * Convert ArrayBuffer to base64 string
   */
  private arrayBufferToBase64(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
  }

  /**
   * Track events for analytics
   */
  private trackEvent(event: string, data?: Record<string, any>): void {
    // Send to analytics service
    if (typeof window !== 'undefined' && (window as any).gtag) {
      (window as any).gtag('event', event, {
        event_category: 'push_notifications',
        ...data
      });
    }

    // Send to internal telemetry
    const telemetryEndpoint = serviceEndpoints.orchestrator('/api/telemetry/event');
    fetch(telemetryEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'push_notification_event',
        event,
        data,
        timestamp: new Date().toISOString()
      })
    }).catch(() => {
      // Ignore telemetry errors
    });
  }
}

/**
 * Notification Templates for Brain Researcher use cases
 */
export class BrainNotificationTemplates {
  static analysisComplete(analysisName: string, analysisId: string): NotificationPayload {
    return {
      type: 'analysis-complete',
      title: 'Analysis Complete',
      body: `Your brain analysis "${analysisName}" has finished processing.`,
      analysisName,
      analysisId,
      actions: [
        { action: 'view', title: 'View Results' },
        { action: 'dismiss', title: 'Dismiss' }
      ]
    };
  }

  static datasetUpdate(datasetName: string, updateType: string = 'update'): NotificationPayload {
    return {
      type: 'data-update',
      title: 'Dataset Update',
      body: `New brain data available: ${datasetName}`,
      datasetName,
      data: { updateType },
      actions: [
        { action: 'sync', title: 'Sync Now' },
        { action: 'later', title: 'Later' }
      ]
    };
  }

  static systemAlert(message: string, severity: 'low' | 'medium' | 'high' = 'medium'): NotificationPayload {
    return {
      type: 'system-alert',
      title: 'Brain Researcher Alert',
      body: message,
      message,
      data: { severity },
      requireInteraction: severity === 'high'
    };
  }

  static processingUpdate(progress: number, analysisName: string): NotificationPayload {
    return {
      type: 'default',
      title: 'Processing Update',
      body: `Analysis "${analysisName}" is ${progress}% complete`,
      data: { progress, analysisName }
    };
  }

  static offlineDataSync(syncedItems: number): NotificationPayload {
    return {
      type: 'default',
      title: 'Offline Sync Complete',
      body: `${syncedItems} items synchronized while offline`,
      data: { syncedItems }
    };
  }
}

/**
 * Utility functions for push notifications
 */
export class PushNotificationUtils {
  /**
   * Check if browser supports push notifications
   */
  static isSupported(): boolean {
    return 'serviceWorker' in navigator && 
           'PushManager' in window && 
           'Notification' in window;
  }

  /**
   * Get user-friendly permission status message
   */
  static getPermissionMessage(permission: NotificationPermission): string {
    switch (permission) {
      case 'granted':
        return 'Notifications are enabled';
      case 'denied':
        return 'Notifications are blocked. Please enable them in browser settings.';
      case 'default':
        return 'Click to enable notifications';
      default:
        return 'Unknown notification status';
    }
  }

  /**
   * Check if device is likely mobile
   */
  static isMobileDevice(): boolean {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  }

  /**
   * Get optimal notification timing based on user activity
   */
  static getOptimalNotificationTime(): Date {
    const now = new Date();
    const hour = now.getHours();
    
    // Avoid late night/early morning notifications
    if (hour >= 22 || hour <= 7) {
      const nextDay = new Date(now);
      nextDay.setDate(nextDay.getDate() + 1);
      nextDay.setHours(9, 0, 0, 0);
      return nextDay;
    }
    
    return now;
  }

  /**
   * Format notification body for brain research context
   */
  static formatBrainNotificationBody(type: string, data: Record<string, any>): string {
    switch (type) {
      case 'analysis-complete':
        return `Brain analysis "${data.analysisName}" completed. ${data.significantFindings ? 'Significant findings detected!' : 'Results ready for review.'}`;
      
      case 'dataset-ready':
        return `Dataset "${data.datasetName}" (${data.subjectCount} subjects) is ready for analysis.`;
      
      case 'processing-error':
        return `Analysis "${data.analysisName}" encountered an error. Technical support has been notified.`;
      
      case 'collaboration-invite':
        return `${data.inviterName} invited you to collaborate on "${data.projectName}".`;
      
      default:
        return data.body || 'Brain Researcher notification';
    }
  }
}

// Create singleton instance
export const pushNotificationManager = new PushNotificationManager();

// Export types and classes
export { PushNotificationManager };

// Default export
export default pushNotificationManager;

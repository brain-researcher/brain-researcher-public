"use client"

import * as React from "react"
import { Eye, EyeOff, Mail, Lock, Loader2 } from "lucide-react"
import { getProviders } from "next-auth/react"
import { useRouter } from "next/navigation"
import { useAuth } from "@/hooks/use-auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"

export interface LoginFormProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onSubmit'> {
  onSubmit?: (data: LoginFormData) => Promise<void> | void
  onForgotPassword?: () => void
  onSignUp?: () => void
  onSocialLogin?: (provider: 'google' | 'github' | 'microsoft') => Promise<void> | void
  loading?: boolean
  errorMessage?: string
  redirectTo?: string
  showSocialLogin?: boolean
  showRememberMe?: boolean
  showForgotPassword?: boolean
  showSignUpLink?: boolean
}

export interface LoginFormData {
  email: string
  password: string
  rememberMe?: boolean
}

const sanitizeCallbackUrl = (value?: string | null) => {
  const candidate = typeof value === 'string' ? value.trim() : ''
  if (!candidate) return '/'
  if (!candidate.startsWith('/')) return '/'
  if (candidate.startsWith('/auth')) return '/'
  return candidate
}

const LoginForm = React.forwardRef<HTMLDivElement, LoginFormProps>(
  ({
    className,
    onSubmit,
    onForgotPassword,
    onSignUp,
    onSocialLogin,
    loading = false,
    errorMessage,
    redirectTo,
    showSocialLogin = true,
    showRememberMe = true,
    showForgotPassword = true,
    showSignUpLink = true,
    ...props
  }, ref) => {
    const router = useRouter()
    const { login, loginWithProvider, authProvider } = useAuth()
    const usesSupabase = authProvider === 'supabase' || authProvider === 'both'
    const [isHydrated, setIsHydrated] = React.useState(false)
    const [formData, setFormData] = React.useState<LoginFormData>({
      email: '',
      password: '',
      rememberMe: false,
    })
    const [showPassword, setShowPassword] = React.useState(false)
    const [errors, setErrors] = React.useState<Partial<LoginFormData>>({})
    const [generalError, setGeneralError] = React.useState<string | null>(null)
    const [isSubmitting, setIsSubmitting] = React.useState(false)
    const [availableProviders, setAvailableProviders] = React.useState<Record<string, any> | null>(null)

    React.useEffect(() => {
      setIsHydrated(true)
    }, [])

    const resolveSupabaseProviders = (raw?: string | null) => {
      const defaultProviders = ['google', 'github']
      const normalized = (raw || '')
        .split(',')
        .map((p) => p.trim().toLowerCase())
        .filter(Boolean)
      return normalized.length ? normalized : defaultProviders
    }

    const [supabaseProviders, setSupabaseProviders] = React.useState<string[] | null>(null)

    React.useEffect(() => {
      let cancelled = false

      const loadSupabaseProviders = () => {
        fetch('/api/config', { cache: 'no-store' })
          .then((res) => (res.ok ? res.json() : null))
          .then((cfg) => {
            if (cancelled) return
            const raw = cfg?.auth?.supabase?.providers as string[] | undefined
            if (Array.isArray(raw) && raw.length > 0) {
              setSupabaseProviders(raw.map((p) => String(p).toLowerCase()))
              return
            }
            setSupabaseProviders(
              resolveSupabaseProviders(process.env.NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS)
            )
          })
          .catch(() => {
            if (cancelled) return
            setSupabaseProviders(
              resolveSupabaseProviders(process.env.NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS)
            )
          })
      }

      const loadNextAuthProviders = async () => {
        try {
          const providers = await getProviders()
          if (!cancelled) {
            setAvailableProviders((providers ?? {}) as Record<string, any>)
          }
        } catch {
          if (!cancelled) {
            setAvailableProviders({})
          }
        }
      }

      if (usesSupabase) {
        loadSupabaseProviders()
        if (authProvider === 'supabase') {
          setAvailableProviders({ supabase: true })
          return () => {
            cancelled = true
          }
        }
      }

      void loadNextAuthProviders()

      return () => {
        cancelled = true
      }
    }, [authProvider, usesSupabase])

    const getCallbackUrl = () => {
      if (redirectTo) return sanitizeCallbackUrl(redirectTo)
      if (typeof window !== 'undefined') {
        const params = new URLSearchParams(window.location.search)
        return sanitizeCallbackUrl(params.get('callbackUrl'))
      }
      return '/'
    }

    const handleProviderSignIn = async (provider: 'google' | 'github' | 'microsoft') => {
      await loginWithProvider(provider)
    }

    const validateForm = (): boolean => {
      const newErrors: Partial<LoginFormData> = {}
      
      if (!formData.email) {
        newErrors.email = 'Email is required'
      } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
        newErrors.email = 'Please enter a valid email address'
      }
      
      if (!formData.password) {
        newErrors.password = 'Password is required'
      } else if (formData.password.length < 6) {
        newErrors.password = 'Password must be at least 6 characters'
      }
      
      setErrors(newErrors)
      return Object.keys(newErrors).length === 0
    }

    const handleSubmit = async (e: React.FormEvent) => {
      e.preventDefault()
      
      if (!validateForm() || loading || isSubmitting) return
      
      setIsSubmitting(true)
      setGeneralError(null)
      
      try {
        if (onSubmit) {
          await onSubmit(formData)
        } else {
          const result = await login(formData.email, formData.password)
          if (result.success) {
            if (redirectTo) {
              router.push(redirectTo)
            }
          } else {
            setGeneralError(result.error || 'Login failed')
          }
        }
      } catch (error) {
        console.error('Login error:', error)
        setGeneralError('Network error. Please try again.')
      } finally {
        setIsSubmitting(false)
      }
    }

    const handleInputChange = (field: keyof LoginFormData) => (
      e: React.ChangeEvent<HTMLInputElement>
    ) => {
      const value = field === 'rememberMe' ? e.target.checked : e.target.value
      setFormData(prev => ({ ...prev, [field]: value }))
      
      // Clear error when user starts typing
      if (errors[field]) {
        setErrors(prev => ({ ...prev, [field]: undefined }))
      }
      if (generalError) {
        setGeneralError(null)
      }
    }

    const handleSocialLogin = async (provider: 'google' | 'github' | 'microsoft') => {
      if (loading || isSubmitting) return

      try {
        if (onSocialLogin) {
          await Promise.resolve(onSocialLogin(provider))
        } else {
          await handleProviderSignIn(provider)
        }
      } catch (error) {
        console.error(`${provider} login error:`, error)
      }
    }

    const isLoading = loading || isSubmitting
    const inputsDisabled = isLoading || !isHydrated
    const oauthProviders = React.useMemo(() => {
      if (!availableProviders && !usesSupabase) return []

      const providers: Array<{ id: 'google' | 'github' | 'microsoft'; label: string }> = []

      if (usesSupabase) {
        const enabled = supabaseProviders || resolveSupabaseProviders(null)
        if (enabled.includes('google')) providers.push({ id: 'google', label: 'Google' })
        if (enabled.includes('github')) providers.push({ id: 'github', label: 'GitHub' })
        if (enabled.includes('microsoft') || enabled.includes('azure')) {
          providers.push({ id: 'microsoft', label: 'Microsoft' })
        }
      }

      if (authProvider !== 'supabase' && availableProviders) {
        if (availableProviders.google) providers.push({ id: 'google', label: 'Google' })
        if (availableProviders.github) providers.push({ id: 'github', label: 'GitHub' })
        if (availableProviders['azure-ad']) providers.push({ id: 'microsoft', label: 'Microsoft' })
      }

      const seen = new Set<string>()
      return providers.filter((provider) => {
        if (seen.has(provider.id)) return false
        seen.add(provider.id)
        return true
      })
    }, [availableProviders, authProvider, supabaseProviders, usesSupabase])

    const hasCredentialsProvider = React.useMemo(() => {
      if (!availableProviders) return true
      if (usesSupabase) return true
      return Boolean(availableProviders.credentials)
    }, [availableProviders, authProvider, usesSupabase])

    const canUseEmailPassword = Boolean(onSubmit) || hasCredentialsProvider
    const showOAuthSection = showSocialLogin && oauthProviders.length > 0

    return (
      <div
        ref={ref}
        className={cn("w-full", className)}
        data-auth-ready={isHydrated ? 'true' : 'false'}
        {...props}
      >
        <Card className="w-full max-w-md mx-auto">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-bold text-center">
              Sign in to your account
            </CardTitle>
            <CardDescription className="text-center">
              {canUseEmailPassword
                ? "Enter your email and password to access Brain Researcher"
                : showOAuthSection
                  ? "Continue with a provider to access Brain Researcher"
                  : "Sign-in is not configured for this deployment."}
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {(errorMessage || generalError) && (
              <div
                role="alert"
                className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {errorMessage || generalError}
              </div>
            )}
            {showOAuthSection && (
              <>
                <div className="grid grid-cols-1 gap-2">
                  {oauthProviders.some((p) => p.id === 'google') && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => handleSocialLogin('google')}
                      disabled={inputsDisabled}
                      className="w-full"
                    >
                      <svg className="w-4 h-4 mr-2" viewBox="0 0 24 24">
                        <path
                          fill="currentColor"
                          d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                        />
                        <path
                          fill="currentColor"
                          d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                        />
                        <path
                          fill="currentColor"
                          d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                        />
                        <path
                          fill="currentColor"
                          d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                        />
                      </svg>
                      Continue with Google
                    </Button>
                  )}

                  {oauthProviders.some((p) => p.id === 'github') && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => handleSocialLogin('github')}
                      disabled={inputsDisabled}
                      className="w-full"
                    >
                      <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                        <path
                          fillRule="evenodd"
                          d="M10 0C4.477 0 0 4.484 0 10.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0110 4.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.203 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.942.359.31.678.921.678 1.856 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0020 10.017C20 4.484 15.522 0 10 0z"
                          clipRule="evenodd"
                        />
                      </svg>
                      Continue with GitHub
                    </Button>
                  )}

                  {oauthProviders.some((p) => p.id === 'microsoft') && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => handleSocialLogin('microsoft')}
                      disabled={inputsDisabled}
                      className="w-full"
                    >
                      Continue with Microsoft
                    </Button>
                  )}
                </div>

                {canUseEmailPassword && (
                  <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                      <Separator className="w-full" />
                    </div>
                    <div className="relative flex justify-center text-xs uppercase">
                      <span className="bg-background px-2 text-muted-foreground">
                        Or continue with email
                      </span>
                    </div>
                  </div>
                )}
              </>
            )}

            {canUseEmailPassword ? (
              <form onSubmit={handleSubmit} className="space-y-4" autoComplete="on">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="Email address"
                    value={formData.email}
                    onChange={handleInputChange('email')}
                    disabled={inputsDisabled}
                    className={cn(
                      "pl-9",
                      errors.email && "border-destructive focus-visible:ring-destructive"
                    )}
                  />
                </div>
                {errors.email && (
                  <p className="text-sm text-destructive">{errors.email}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="Enter your password"
                    value={formData.password}
                    onChange={handleInputChange('password')}
                    disabled={inputsDisabled}
                    className={cn(
                      "pl-9 pr-9",
                      errors.password && "border-destructive focus-visible:ring-destructive"
                    )}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent"
                    onClick={() => setShowPassword(!showPassword)}
                    disabled={inputsDisabled}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                    <span className="sr-only">
                      {showPassword ? "Hide password" : "Show password"}
                    </span>
                  </Button>
                </div>
                {errors.password && (
                  <p className="text-sm text-destructive">{errors.password}</p>
                )}
              </div>

              {showRememberMe && (
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="remember"
                    checked={formData.rememberMe}
                    onCheckedChange={(checked) =>
                      setFormData(prev => ({ ...prev, rememberMe: !!checked }))
                    }
                    disabled={inputsDisabled}
                  />
                  <Label
                    htmlFor="remember"
                    className="text-sm font-normal cursor-pointer"
                  >
                    Remember me for 30 days
                  </Label>
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={inputsDisabled}
              >
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isLoading ? "Signing in..." : "Sign in"}
              </Button>
              </form>
            ) : (
              <div className="rounded-md border border-dashed bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
                Email/password sign-in is not enabled for this deployment.
              </div>
            )}
          </CardContent>

          <CardFooter className="flex flex-col space-y-4">
            {showForgotPassword && canUseEmailPassword && onForgotPassword && (
              <Button
                type="button"
                variant="link"
                className="text-sm"
                onClick={onForgotPassword}
                disabled={isLoading}
              >
                Forgot your password?
              </Button>
            )}
            
            {showSignUpLink && onSignUp && (
              <div className="text-center text-sm text-muted-foreground">
                Don't have an account?{" "}
                <Button
                  type="button"
                  variant="link"
                  className="p-0 h-auto font-semibold text-primary"
                  onClick={onSignUp}
                  disabled={isLoading}
                >
                  Sign up
                </Button>
              </div>
            )}
          </CardFooter>
        </Card>
      </div>
    )
  }
)
LoginForm.displayName = "LoginForm"

export { LoginForm }

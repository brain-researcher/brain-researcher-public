"use client"

import * as React from "react"
import { getProviders } from "next-auth/react"
import Link from "next/link"
import { Eye, EyeOff, Mail, Lock, User, Loader2, Check, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Separator } from "@/components/ui/separator"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import { useAuth } from "@/hooks/use-auth"

export interface SignupFormProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onSubmit'> {
  onSubmit?: (data: SignupFormData) => Promise<void> | void
  onSignIn?: () => void
  onSocialLogin?: (provider: 'google' | 'github' | 'microsoft') => Promise<void> | void
  loading?: boolean
  showSocialLogin?: boolean
  showSignInLink?: boolean
  showPasswordStrength?: boolean
  requireTermsAcceptance?: boolean
}

export interface SignupFormData {
  firstName: string
  lastName: string
  email: string
  password: string
  confirmPassword: string
  acceptTerms?: boolean
  marketingOptIn?: boolean
}

interface PasswordStrength {
  score: number
  feedback: string[]
  requirements: {
    length: boolean
    uppercase: boolean
    lowercase: boolean
    number: boolean
    special: boolean
  }
}

const SignupForm = React.forwardRef<HTMLDivElement, SignupFormProps>(
  ({
    className,
    onSubmit,
    onSignIn,
    onSocialLogin,
    loading = false,
    showSocialLogin = true,
    showSignInLink = true,
    showPasswordStrength = true,
    requireTermsAcceptance = true,
    ...props
  }, ref) => {
    const { loginWithProvider, authProvider } = useAuth()
    const usesSupabase = authProvider === 'supabase' || authProvider === 'both'
    const [availableProviders, setAvailableProviders] = React.useState<Record<string, any> | null>(null)
    const [supabaseProviders, setSupabaseProviders] = React.useState<string[] | null>(null)
    const [formData, setFormData] = React.useState<SignupFormData>({
      firstName: '',
      lastName: '',
      email: '',
      password: '',
      confirmPassword: '',
      acceptTerms: false,
      marketingOptIn: false,
    })
    const [showPassword, setShowPassword] = React.useState(false)
    const [showConfirmPassword, setShowConfirmPassword] = React.useState(false)
    const [errors, setErrors] = React.useState<Partial<Record<keyof SignupFormData, string>>>({})
    const [isSubmitting, setIsSubmitting] = React.useState(false)
    const [passwordStrength, setPasswordStrength] = React.useState<PasswordStrength>({
      score: 0,
      feedback: [],
      requirements: {
        length: false,
        uppercase: false,
        lowercase: false,
        number: false,
        special: false,
      }
    })

    const resolveSupabaseProviders = (raw?: string | null) => {
      const defaultProviders = ['google', 'github']
      const normalized = (raw || '')
        .split(',')
        .map((p) => p.trim().toLowerCase())
        .filter(Boolean)
      return normalized.length ? normalized : defaultProviders
    }

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

    const calculatePasswordStrength = (password: string): PasswordStrength => {
      const requirements = {
        length: password.length >= 8,
        uppercase: /[A-Z]/.test(password),
        lowercase: /[a-z]/.test(password),
        number: /\d/.test(password),
        special: /[!@#$%^&*(),.?":{}|<>]/.test(password),
      }

      const score = Object.values(requirements).filter(Boolean).length
      const feedback: string[] = []

      if (!requirements.length) feedback.push("At least 8 characters")
      if (!requirements.uppercase) feedback.push("One uppercase letter")
      if (!requirements.lowercase) feedback.push("One lowercase letter")
      if (!requirements.number) feedback.push("One number")
      if (!requirements.special) feedback.push("One special character")

      return { score, feedback, requirements }
    }

    React.useEffect(() => {
      if (formData.password) {
        setPasswordStrength(calculatePasswordStrength(formData.password))
      }
    }, [formData.password])

    const validateForm = (): boolean => {
      const newErrors: Partial<Record<keyof SignupFormData, string>> = {}
      
      if (!formData.firstName.trim()) {
        newErrors.firstName = 'First name is required'
      }
      
      if (!formData.lastName.trim()) {
        newErrors.lastName = 'Last name is required'
      }
      
      if (!formData.email) {
        newErrors.email = 'Email is required'
      } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
        newErrors.email = 'Please enter a valid email address'
      }
      
      if (!formData.password) {
        newErrors.password = 'Password is required'
      } else if (passwordStrength.score < 4) {
        newErrors.password = 'Password is not strong enough'
      }
      
      if (!formData.confirmPassword) {
        newErrors.confirmPassword = 'Please confirm your password'
      } else if (formData.password !== formData.confirmPassword) {
        newErrors.confirmPassword = 'Passwords do not match'
      }
      
      if (requireTermsAcceptance && !formData.acceptTerms) {
        newErrors.acceptTerms = 'You must accept the terms and conditions'
      }
      
      setErrors(newErrors)
      return Object.keys(newErrors).length === 0
    }

    const handleSubmit = async (e: React.FormEvent) => {
      e.preventDefault()
      
      if (!validateForm() || loading || isSubmitting) return
      
      setIsSubmitting(true)
      
      try {
        await onSubmit?.(formData)
      } catch (error) {
        console.error('Signup error:', error)
      } finally {
        setIsSubmitting(false)
      }
    }

    const handleInputChange = (field: keyof SignupFormData) => (
      e: React.ChangeEvent<HTMLInputElement>
    ) => {
      const value = ['acceptTerms', 'marketingOptIn'].includes(field) 
        ? e.target.checked 
        : e.target.value
      
      setFormData(prev => ({ ...prev, [field]: value }))
      
      // Clear error when user starts typing
      if (errors[field]) {
        setErrors(prev => ({ ...prev, [field]: undefined }))
      }
    }

    const handleSocialLogin = async (provider: 'google' | 'github' | 'microsoft') => {
      if (loading || isSubmitting) return
      
      try {
        if (onSocialLogin) {
          await Promise.resolve(onSocialLogin(provider))
        } else {
          await loginWithProvider(provider)
        }
      } catch (error) {
        console.error(`${provider} signup error:`, error)
      }
    }

    const getPasswordStrengthColor = (score: number) => {
      if (score <= 1) return "bg-red-500"
      if (score <= 2) return "bg-orange-500"
      if (score <= 3) return "bg-yellow-500"
      if (score <= 4) return "bg-green-500"
      return "bg-green-600"
    }

    const getPasswordStrengthText = (score: number) => {
      if (score <= 1) return "Weak"
      if (score <= 2) return "Fair"
      if (score <= 3) return "Good"
      if (score <= 4) return "Strong"
      return "Very Strong"
    }

    const isLoading = loading || isSubmitting
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
    const showOAuthSection = showSocialLogin && oauthProviders.length > 0

    return (
      <div ref={ref} className={cn("w-full", className)} {...props}>
        <Card className="w-full max-w-md mx-auto">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-bold text-center">
              Create your account
            </CardTitle>
            <CardDescription className="text-center">
              Join Brain Researcher to access advanced neuroimaging analysis
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {showOAuthSection && (
              <>
                <div className="grid grid-cols-1 gap-2">
                  {oauthProviders.map((provider) => (
                    <Button
                      key={provider.id}
                      type="button"
                      variant="outline"
                      onClick={() => handleSocialLogin(provider.id)}
                      disabled={isLoading}
                      className="w-full"
                    >
                      {provider.id === 'google' && (
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
                      )}
                      {provider.id === 'github' && (
                        <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                          <path
                            fillRule="evenodd"
                            d="M10 0C4.477 0 0 4.484 0 10.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0110 4.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.203 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.942.359.31.678.921.678 1.856 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0020 10.017C20 4.484 15.522 0 10 0z"
                            clipRule="evenodd"
                          />
                        </svg>
                      )}
                      {provider.id === 'microsoft' && (
                        <svg className="w-4 h-4 mr-2" viewBox="0 0 24 24">
                          <path fill="currentColor" d="M2 2h9v9H2zM13 2h9v9h-9zM2 13h9v9H2zM13 13h9v9h-9z" />
                        </svg>
                      )}
                      Sign up with {provider.label}
                    </Button>
                  ))}
                </div>
                
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <Separator className="w-full" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-background px-2 text-muted-foreground">
                      Or create with email
                    </span>
                  </div>
                </div>
              </>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="firstName">First name</Label>
                  <div className="relative">
                    <User className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="firstName"
                      type="text"
                      placeholder="First name"
                      value={formData.firstName}
                      onChange={handleInputChange('firstName')}
                      disabled={isLoading}
                      className={cn(
                        "pl-9",
                        errors.firstName && "border-destructive focus-visible:ring-destructive"
                      )}
                    />
                  </div>
                  {errors.firstName && (
                    <p className="text-sm text-destructive">{errors.firstName}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="lastName">Last name</Label>
                  <Input
                    id="lastName"
                    type="text"
                    placeholder="Last name"
                    value={formData.lastName}
                    onChange={handleInputChange('lastName')}
                    disabled={isLoading}
                    className={cn(
                      errors.lastName && "border-destructive focus-visible:ring-destructive"
                    )}
                  />
                  {errors.lastName && (
                    <p className="text-sm text-destructive">{errors.lastName}</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    placeholder="Email address"
                    value={formData.email}
                    onChange={handleInputChange('email')}
                    disabled={isLoading}
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
                    placeholder="Create a strong password"
                    value={formData.password}
                    onChange={handleInputChange('password')}
                    disabled={isLoading}
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
                    disabled={isLoading}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                
                {showPasswordStrength && formData.password && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Password strength:</span>
                      <span className={cn(
                        "font-medium",
                        passwordStrength.score <= 2 ? "text-destructive" : "text-green-600"
                      )}>
                        {getPasswordStrengthText(passwordStrength.score)}
                      </span>
                    </div>
                    <Progress 
                      value={(passwordStrength.score / 5) * 100} 
                      className="h-2"
                    />
                    <div className="space-y-1">
                      {Object.entries(passwordStrength.requirements).map(([key, met]) => (
                        <div key={key} className="flex items-center text-xs">
                          {met ? (
                            <Check className="h-3 w-3 text-green-600 mr-2" />
                          ) : (
                            <X className="h-3 w-3 text-muted-foreground mr-2" />
                          )}
                          <span className={cn(
                            met ? "text-green-600" : "text-muted-foreground"
                          )}>
                            {key === 'length' && "At least 8 characters"}
                            {key === 'uppercase' && "One uppercase letter"}
                            {key === 'lowercase' && "One lowercase letter"}
                            {key === 'number' && "One number"}
                            {key === 'special' && "One special character"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                {errors.password && (
                  <p className="text-sm text-destructive">{errors.password}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="confirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="Confirm your password"
                    value={formData.confirmPassword}
                    onChange={handleInputChange('confirmPassword')}
                    disabled={isLoading}
                    className={cn(
                      "pl-9 pr-9",
                      errors.confirmPassword && "border-destructive focus-visible:ring-destructive"
                    )}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    disabled={isLoading}
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                {errors.confirmPassword && (
                  <p className="text-sm text-destructive">{errors.confirmPassword}</p>
                )}
              </div>

              <div className="space-y-3">
                {requireTermsAcceptance && (
                  <div className="flex items-start space-x-2">
                    <Checkbox
                      id="acceptTerms"
                      checked={formData.acceptTerms}
                      onCheckedChange={(checked) =>
                        setFormData(prev => ({ ...prev, acceptTerms: !!checked }))
                      }
                      disabled={isLoading}
                      className="mt-0.5"
                    />
                    <div className="space-y-1 leading-none">
                      <Label
                        htmlFor="acceptTerms"
                        className={cn(
                          "text-sm font-normal cursor-pointer",
                          errors.acceptTerms && "text-destructive"
                        )}
                      >
                        I agree to the{" "}
                        <Link
                          href="/terms"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline text-primary"
                        >
                          Terms of Service
                        </Link>{" "}
                        and{" "}
                        <Link
                          href="/privacy"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline text-primary"
                        >
                          Privacy Policy
                        </Link>
                      </Label>
                      {errors.acceptTerms && (
                        <p className="text-xs text-destructive">{errors.acceptTerms}</p>
                      )}
                    </div>
                  </div>
                )}

                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="marketingOptIn"
                    checked={formData.marketingOptIn}
                    onCheckedChange={(checked) =>
                      setFormData(prev => ({ ...prev, marketingOptIn: !!checked }))
                    }
                    disabled={isLoading}
                  />
                  <Label
                    htmlFor="marketingOptIn"
                    className="text-sm font-normal cursor-pointer"
                  >
                    Send me product updates and research insights
                  </Label>
                </div>
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={isLoading || (requireTermsAcceptance && !formData.acceptTerms)}
              >
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isLoading ? "Creating account..." : "Create account"}
              </Button>
            </form>
          </CardContent>

          <CardFooter>
            {showSignInLink && (
              <div className="text-center text-sm text-muted-foreground w-full">
                Already have an account?{" "}
                <Button
                  type="button"
                  variant="link"
                  className="p-0 h-auto font-semibold text-primary"
                  onClick={onSignIn}
                  disabled={isLoading}
                >
                  Sign in
                </Button>
              </div>
            )}
          </CardFooter>
        </Card>
      </div>
    )
  }
)
SignupForm.displayName = "SignupForm"

export { SignupForm }

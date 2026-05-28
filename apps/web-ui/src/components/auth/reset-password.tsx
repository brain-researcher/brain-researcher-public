"use client"

import * as React from "react"
import { ArrowLeft, Mail, Loader2, CheckCircle, Lock, Eye, EyeOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"

export interface ResetPasswordProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onSubmit'> {
  onSubmit?: (data: ResetPasswordFormData) => Promise<void> | void
  onBackToLogin?: () => void
  loading?: boolean
  mode?: 'request' | 'reset'
  token?: string
}

export interface ResetPasswordFormData {
  email?: string
  password?: string
  confirmPassword?: string
  token?: string
}

interface PasswordStrength {
  score: number
  requirements: {
    length: boolean
    uppercase: boolean
    lowercase: boolean
    number: boolean
    special: boolean
  }
}

const ResetPassword = React.forwardRef<HTMLDivElement, ResetPasswordProps>(
  ({
    className,
    onSubmit,
    onBackToLogin,
    loading = false,
    mode = 'request',
    token,
    ...props
  }, ref) => {
    const [formData, setFormData] = React.useState<ResetPasswordFormData>({
      email: '',
      password: '',
      confirmPassword: '',
      token: token || '',
    })
    const [showPassword, setShowPassword] = React.useState(false)
    const [showConfirmPassword, setShowConfirmPassword] = React.useState(false)
    const [errors, setErrors] = React.useState<Partial<ResetPasswordFormData>>({})
    const [isSubmitting, setIsSubmitting] = React.useState(false)
    const [isSubmitted, setIsSubmitted] = React.useState(false)
    const [passwordStrength, setPasswordStrength] = React.useState<PasswordStrength>({
      score: 0,
      requirements: {
        length: false,
        uppercase: false,
        lowercase: false,
        number: false,
        special: false,
      }
    })

    const calculatePasswordStrength = (password: string): PasswordStrength => {
      const requirements = {
        length: password.length >= 8,
        uppercase: /[A-Z]/.test(password),
        lowercase: /[a-z]/.test(password),
        number: /\d/.test(password),
        special: /[!@#$%^&*(),.?":{}|<>]/.test(password),
      }

      const score = Object.values(requirements).filter(Boolean).length

      return { score, requirements }
    }

    React.useEffect(() => {
      if (formData.password && mode === 'reset') {
        setPasswordStrength(calculatePasswordStrength(formData.password))
      }
    }, [formData.password, mode])

    const validateForm = (): boolean => {
      const newErrors: Partial<ResetPasswordFormData> = {}
      
      if (mode === 'request') {
        if (!formData.email) {
          newErrors.email = 'Email is required'
        } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
          newErrors.email = 'Please enter a valid email address'
        }
      } else {
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
        if (mode === 'request') {
          setIsSubmitted(true)
        }
      } catch (error) {
        console.error('Reset password error:', error)
      } finally {
        setIsSubmitting(false)
      }
    }

    const handleInputChange = (field: keyof ResetPasswordFormData) => (
      e: React.ChangeEvent<HTMLInputElement>
    ) => {
      setFormData(prev => ({ ...prev, [field]: e.target.value }))
      
      // Clear error when user starts typing
      if (errors[field]) {
        setErrors(prev => ({ ...prev, [field]: undefined }))
      }
    }

    const isLoading = loading || isSubmitting

    // Success state for email sent
    if (mode === 'request' && isSubmitted) {
      return (
        <div ref={ref} className={cn("w-full", className)} {...props}>
          <Card className="w-full max-w-md mx-auto">
            <CardHeader className="text-center space-y-4">
              <div className="mx-auto w-12 h-12 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center">
                <CheckCircle className="w-6 h-6 text-green-600" />
              </div>
              <CardTitle className="text-2xl font-bold">
                Check your email
              </CardTitle>
              <CardDescription>
                We've sent a password reset link to{" "}
                <span className="font-medium text-foreground">{formData.email}</span>
              </CardDescription>
            </CardHeader>
            
            <CardContent className="text-center space-y-4">
              <p className="text-sm text-muted-foreground">
                Didn't receive the email? Check your spam folder or try again.
              </p>
              
              <Button
                variant="outline"
                onClick={() => setIsSubmitted(false)}
                className="w-full"
              >
                Try again
              </Button>
            </CardContent>
            
            <CardFooter className="justify-center">
              <Button
                variant="link"
                onClick={onBackToLogin}
                className="text-sm"
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to sign in
              </Button>
            </CardFooter>
          </Card>
        </div>
      )
    }

    return (
      <div ref={ref} className={cn("w-full", className)} {...props}>
        <Card className="w-full max-w-md mx-auto">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl font-bold text-center">
              {mode === 'request' ? 'Reset your password' : 'Set new password'}
            </CardTitle>
            <CardDescription className="text-center">
              {mode === 'request' 
                ? 'Enter your email address and we\'ll send you a link to reset your password'
                : 'Create a new password for your account'
              }
            </CardDescription>
          </CardHeader>

          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {mode === 'request' ? (
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
              ) : (
                <>
                  <div className="space-y-2">
                    <Label htmlFor="password">New password</Label>
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
                    
                    {formData.password && (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">Password strength:</span>
                          <span className={cn(
                            "font-medium",
                            passwordStrength.score <= 2 ? "text-destructive" : "text-green-600"
                          )}>
                            {passwordStrength.score <= 1 ? "Weak" : 
                             passwordStrength.score <= 2 ? "Fair" : 
                             passwordStrength.score <= 3 ? "Good" : 
                             passwordStrength.score <= 4 ? "Strong" : "Very Strong"}
                          </span>
                        </div>
                        <Progress 
                          value={(passwordStrength.score / 5) * 100} 
                          className="h-2"
                        />
                      </div>
                    )}
                    
                    {errors.password && (
                      <p className="text-sm text-destructive">{errors.password}</p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="confirmPassword">Confirm new password</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="confirmPassword"
                        type={showConfirmPassword ? "text" : "password"}
                        placeholder="Confirm your new password"
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
                </>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={isLoading}
              >
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isLoading 
                  ? (mode === 'request' ? "Sending link..." : "Updating password...")
                  : (mode === 'request' ? "Send reset link" : "Update password")
                }
              </Button>
            </form>
          </CardContent>

          <CardFooter className="justify-center">
            <Button
              variant="link"
              onClick={onBackToLogin}
              className="text-sm"
              disabled={isLoading}
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to sign in
            </Button>
          </CardFooter>
        </Card>
      </div>
    )
  }
)
ResetPassword.displayName = "ResetPassword"

export { ResetPassword }

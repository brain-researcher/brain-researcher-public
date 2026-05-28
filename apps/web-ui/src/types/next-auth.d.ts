// Minimal module augmentation for NextAuth Session fields used by the app.
import 'next-auth'

declare module 'next-auth' {
  interface User {
    id?: string
    role?: string
    provider?: string
    tenant_id?: string
    orchestrator_access_token?: string
    name?: string | null
    email?: string | null
    image?: string | null
  }

  interface Session {
    error?: string
    accessToken?: string
    user?: User
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    tenant_id?: string
    role?: string
    provider?: string
    orchestrator_access_token?: string
  }
}

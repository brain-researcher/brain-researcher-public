import NextAuth from 'next-auth'
import { authOptions } from '@/lib/next-auth-config'
export const dynamic = 'force-dynamic'

const handler = NextAuth(authOptions)

export { handler as GET, handler as POST }

import { redirect } from 'next/navigation'

export default function ResourcesRedirect() {
  // Redirect to dashboard resources view
  redirect('/dashboard?view=resources')
}

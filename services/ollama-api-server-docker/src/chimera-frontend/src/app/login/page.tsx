// chimera-frontend/src/app/login/page.tsx
import { UserAuthForm } from '@/components/UserAuthForm';
import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';

export default async function LoginPage() {
  const session = await getServerSession();

  if (session) {
    redirect('/dashboard');
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
      <UserAuthForm />
    </div>
  );
}

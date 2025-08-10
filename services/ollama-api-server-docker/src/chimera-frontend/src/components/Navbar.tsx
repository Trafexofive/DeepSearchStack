// chimera-frontend/src/components/Navbar.tsx
'use client';

import Link from 'next/link';
import { useSession, signOut } from 'next-auth/react';
import { Button } from './ui/button';

export default function Navbar() {
  const { data: session, status } = useSession();

  return (
    <nav className="flex items-center justify-between p-4 bg-background border-b">
      <div className="flex items-center">
        <Link href="/" className="text-xl font-bold">
          Chimera
        </Link>
      </div>
      <div className="flex items-center gap-4">
        {status === 'loading' ? (
          <div className="text-sm">Loading...</div>
        ) : session ? (
          <>
            <Link href="/dashboard">Dashboard</Link>
            <Button variant="ghost" onClick={() => signOut({ callbackUrl: '/' })}>
              Logout
            </Button>
          </>
        ) : (
          <Button asChild>
            <Link href="/login">Login</Link>
          </Button>
        )}
      </div>
    </nav>
  );
}
